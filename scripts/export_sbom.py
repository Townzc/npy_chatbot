"""Reproducible CycloneDX inventory from the three committed lockfiles.

Includes dev and platform-conditional dependencies. This is a locked inventory,
not a claim that every component is shipped, licensed-reviewed or vulnerability-free.
"""

import hashlib
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
components: dict[str, dict] = {}
properties = []
for filename in ("uv.lock", "training/uv.lock", "apps/web/pnpm-lock.yaml"):
    content = (ROOT / filename).read_bytes()
    properties.append(
        {"name": "chattwin:lock:" + filename, "value": hashlib.sha256(content).hexdigest()}
    )
    if filename.endswith(".lock"):
        packages = [
            (p["name"], p["version"], "pypi")
            for p in tomllib.loads(content.decode())["package"]
            if "registry" in p.get("source", {})
        ]
    else:
        block = content.decode().split("\npackages:\n", 1)[1].split("\nsnapshots:\n", 1)[0]
        packages = []
        for match in re.finditer(r"^  ('?)(\S[^\n]*?)\1:\s*$", block, re.MULTILINE):
            key = match[2]
            name, version = key.rsplit("@", 1)
            if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.]+)?", version):
                raise ValueError(f"Unsupported npm lock key: {key}")
            packages.append((name, version, "npm"))
    for name, version, ecosystem in packages:
        purl = f"pkg:{ecosystem}/{quote(name, safe='/')}@{version}"
        component = components.setdefault(
            purl,
            {
                "type": "library",
                "bom-ref": purl,
                "name": name,
                "version": version,
                "purl": purl,
                "properties": [],
            },
        )
        component["properties"].append({"name": "chattwin:source-lock", "value": filename})
identity = json.dumps(properties, sort_keys=True)
output = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.6",
    "version": 1,
    "serialNumber": "urn:uuid:" + str(uuid5(NAMESPACE_URL, identity)),
    "metadata": {
        "component": {
            "type": "application",
            "name": "ChatTwin",
            "version": tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"],
        },
        "properties": properties
        + [
            {
                "name": "chattwin:inventory-scope",
                "value": "All lockfile components including development and conditional platform dependencies; license and vulnerability review pending.",
            }
        ],
    },
    "components": [components[key] for key in sorted(components)],
}
path = ROOT / "docs" / "sbom.cdx.json"
path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
print(f"Wrote {len(components)} locked components to {path.relative_to(ROOT)}")
