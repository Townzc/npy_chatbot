"""Release audit must not turn stale inventories or partial network results green."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "audit_dependencies", Path(__file__).parents[1] / "scripts/audit_dependencies.py"
)
assert spec and spec.loader
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def components():
    return [
        {"name": name, "version": "1.0.0", "purl": f"pkg:pypi/{name}@1.0.0"}
        for name in ("fictional-first", "fictional-second")
    ]


def test_stale_lockfile_stops_audit_before_network(tmp_path):
    properties = []
    for name in audit.LOCKS:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic lock content")
        properties.append(
            {
                "name": "chattwin:lock:" + name,
                "value": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/sbom.cdx.json").write_text(
        json.dumps({"metadata": {"properties": properties}, "components": components()})
    )
    assert len(audit.read_inventory(tmp_path)[0]) == 2
    (tmp_path / audit.LOCKS[-1]).write_bytes(b"changed lock")
    with pytest.raises(ValueError, match="stale"):
        audit.read_inventory(tmp_path)


def test_paginated_results_remain_attached_to_original_package():
    calls = []

    def request(url, payload):
        calls.append(payload)
        if len(calls) == 1:
            return {
                "results": [
                    {},
                    {"vulns": [{"id": "SYNTHETIC-1"}], "next_page_token": "second-page"},
                ]
            }
        assert payload["queries"][0]["package"]["name"] == "fictional-second"
        assert payload["queries"][0]["page_token"] == "second-page"
        return {"results": [{"vulns": [{"id": "SYNTHETIC-1"}, {"id": "SYNTHETIC-2"}]}]}

    assert audit.query_packages(components(), request) == [set(), {"SYNTHETIC-1", "SYNTHETIC-2"}]
    assert len(calls) == 2


def test_truncated_batch_is_not_a_clean_result():
    with pytest.raises(ValueError, match="incomplete"):
        audit.query_packages(components(), lambda *_: {"results": [{}]})


def test_repeated_page_does_not_silently_finish_or_loop():
    with pytest.raises(ValueError, match="repeated"):
        audit.query_packages(
            components()[:1], lambda *_: {"results": [{"next_page_token": "same-page"}]}
        )


@pytest.mark.parametrize("failed_step", ["read_inventory", "query_packages"])
def test_failed_query_writes_incomplete_without_network_error_details(
    tmp_path, monkeypatch, failed_step
):
    monkeypatch.setattr(audit, "read_inventory", lambda: (components(), {}))

    def fail(*args):
        raise RuntimeError("synthetic proxy credential must not appear in report")

    monkeypatch.setattr(audit, failed_step, fail)
    output = tmp_path / "audit.json"
    assert audit.run(output, licenses=False) == 2
    report = json.loads(output.read_text())
    assert report["status"] == "incomplete"
    assert report["error_type"] == "RuntimeError"
    assert "proxy credential" not in output.read_text()
    assert "affected_packages" not in report
