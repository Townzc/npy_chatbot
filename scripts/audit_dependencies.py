"""Query public lockfile packages only; never read runtime data or credentials.

Exit 0: complete OSV query with no findings; 1: findings; 2: incomplete/error.
Registry license metadata is an inventory, not a license compatibility decision.
"""

import argparse
import hashlib
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
LOCKS = ("uv.lock", "training/uv.lock", "apps/web/pnpm-lock.yaml")
OSV = "https://api.osv.dev/v1"


def request_json(url, payload=None):
    request = urllib.request.Request(
        url,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "ChatTwin-lock-audit/1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def read_inventory(root=ROOT):
    inventory = json.loads((root / "docs/sbom.cdx.json").read_text())
    properties = {p["name"]: p["value"] for p in inventory["metadata"]["properties"]}
    hashes = {}
    for name in LOCKS:
        hashes[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if properties.get("chattwin:lock:" + name) != hashes[name]:
            raise ValueError("SBOM is stale; run scripts/export_sbom.py first")
    for component in inventory["components"]:
        if not component["purl"].startswith(("pkg:pypi/", "pkg:npm/")):
            raise ValueError("Only public PyPI and npm inventory packages are supported")
    return inventory["components"], hashes


def query_packages(components, request=request_json):
    queries = [
        {
            "package": {
                "name": component["name"],
                "ecosystem": "PyPI" if component["purl"].startswith("pkg:pypi/") else "npm",
            },
            "version": component["version"],
        }
        for component in components
    ]
    found: list[set[str]] = [set() for _ in queries]
    pending = list(enumerate(queries))
    seen_pages: set[tuple[int, str]] = set()
    for _ in range(100):
        result = request(OSV + "/querybatch", {"queries": [q for _, q in pending]})
        if len(result["results"]) != len(pending):
            raise ValueError("OSV returned an incomplete batch")
        following = []
        for (index, query), item in zip(pending, result["results"], strict=True):
            found[index].update(v["id"] for v in item.get("vulns", []))
            if token := item.get("next_page_token"):
                if (index, token) in seen_pages:
                    raise ValueError("OSV repeated a pagination token")
                seen_pages.add((index, token))
                following.append((index, {**query, "page_token": token}))
        if not following:
            return found
        pending = following
    raise ValueError("OSV pagination limit exceeded; results are incomplete")


def advisory(identifier):
    data = request_json(OSV + "/vulns/" + quote(identifier, safe=""))
    return identifier, {
        "id": data["id"],
        "aliases": data.get("aliases", []),
        "modified": data["modified"],
        "withdrawn": data.get("withdrawn"),
        "severity": data.get("database_specific", {}).get("severity"),
        "severity_vectors": data.get("severity", []),
        "affected": [
            {"package": item["package"], "ranges": item.get("ranges", [])}
            for item in data.get("affected", [])
        ],
        "references": data.get("references", []),
    }


def registry_license(component):
    name, version = quote(component["name"], safe=""), quote(component["version"], safe="")
    if component["purl"].startswith("pkg:pypi/"):
        url = f"https://pypi.org/pypi/{name}/{version}/json"
        info = request_json(url)["info"]
    else:
        url = f"https://registry.npmjs.org/{name}/{version}"
        info = request_json(url)
    value = info.get("license_expression") or info.get("license")
    if isinstance(value, dict):
        value = value.get("type")
    # Some registries place the entire license in this field. Do not duplicate it.
    full_text = isinstance(value, str) and (len(value) > 200 or "\n" in value)
    return {
        "source": url,
        "declared_license": None if full_text else value,
        "full_license_text_in_registry": full_text,
        "classifiers": [v for v in info.get("classifiers", []) if v.startswith("License ::")],
        "reviewed_for_redistribution": False,
    }


def run(output: Path, licenses: bool):
    report = {
        "schema_version": "1.0",
        "checked_at": datetime.now(UTC).isoformat(),
        "source": OSV,
        "scope": "all locked packages including development and conditional platforms",
        "status": "incomplete",
        "components_checked": None,
        "limitations": [
            "OSV findings may alias one another; identifiers are not independent vulnerability counts",
            "No findings is not proof of safety or an application security review",
            "Registry license metadata is not a redistribution or legal compatibility approval",
            "External QQ/QCE binaries and model weights are outside this lockfile inventory",
        ],
    }
    try:
        components, lock_hashes = read_inventory()
        report["lock_hashes"] = lock_hashes
        report["components_checked"] = len(components)
        found = query_packages(components)
        ids = sorted(set().union(*found))
        with ThreadPoolExecutor(max_workers=6) as pool:
            details = dict(pool.map(advisory, ids))
            license_info = list(pool.map(registry_license, components)) if licenses else []
        report["advisories"] = details
        report["packages"] = [
            {
                "purl": component["purl"],
                "source_locks": [p["value"] for p in component["properties"]],
                "advisories": sorted(v for v in matches if not details[v]["withdrawn"]),
                **({"license_metadata": license_info[index]} if licenses else {}),
            }
            for index, (component, matches) in enumerate(zip(components, found, strict=True))
        ]
        report["affected_packages"] = sum(bool(p["advisories"]) for p in report["packages"])
        report["status"] = "findings" if report["affected_packages"] else "no_known_findings"
        code = 1 if report["affected_packages"] else 0
    except Exception as exc:
        # Error type is sufficient; do not echo network/proxy environment details.
        report["error_type"] = type(exc).__name__
        code = 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("status", "components_checked", "affected_packages")
                if key in report
            }
        )
    )
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--licenses", action="store_true", help="Also query public registry metadata"
    )
    args = parser.parse_args()
    raise SystemExit(run(args.output, args.licenses))
