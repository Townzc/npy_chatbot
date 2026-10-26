"""Capacity parser contracts, not evidence that any remote GPU has been tested."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "check_gpu_host", Path(__file__).parents[1] / "scripts/check_gpu_host.py"
)
assert spec and spec.loader
host_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host_check)


def test_container_bound_includes_visible_parent_and_ignores_unlimited(tmp_path):
    proc, cgroup = tmp_path / "proc", tmp_path / "cgroup"
    (proc / "self").mkdir(parents=True)
    (proc / "meminfo").write_text(f"MemTotal: {256 * 1024**2} kB\n")
    (proc / "self/cgroup").write_text("0::/tenant/job\n")
    (cgroup / "tenant/job").mkdir(parents=True)
    (cgroup / "memory.max").write_text("max")
    (cgroup / "tenant/memory.max").write_text(str(32 * host_check.GIB))
    (cgroup / "tenant/job/memory.max").write_text(str(64 * host_check.GIB))
    memory = host_check.read_memory(proc, cgroup)
    assert memory["physical_total_bytes"] == 256 * host_check.GIB
    assert memory["known_capacity_bound_bytes"] == 32 * host_check.GIB
    assert memory["rental_console_memory_still_required"] is True


def test_cgroup_v1_and_missing_memory_are_not_reported_as_unlimited(tmp_path):
    proc, cgroup = tmp_path / "proc", tmp_path / "cgroup"
    (proc / "self").mkdir(parents=True)
    (proc / "self/cgroup").write_text("7:cpu,memory:/job\n")
    (cgroup / "memory/job").mkdir(parents=True)
    (cgroup / "memory/memory.limit_in_bytes").write_text(str(2**63 - 4096))
    (cgroup / "memory/job/memory.limit_in_bytes").write_text(str(48 * host_check.GIB))
    assert host_check.read_memory(proc, cgroup)["known_capacity_bound_bytes"] == 48 * host_check.GIB
    (cgroup / "memory/job/memory.limit_in_bytes").unlink()
    assert host_check.read_memory(proc, cgroup)["known_capacity_bound_bytes"] is None
    assert (
        host_check.read_memory(tmp_path / "missing", tmp_path / "missing")[
            "known_capacity_bound_bytes"
        ]
        is None
    )


def test_gpu_inventory_units_and_failures(monkeypatch, tmp_path):
    gpu = host_check.parse_gpus("0, NVIDIA GeForce RTX 4090, 24564, 24100, 570.124.06\n")[0]
    assert gpu["total_memory_bytes"] == 24564 * 1024**2
    assert gpu["driver_version"] == "570.124.06"
    with pytest.raises(ValueError):
        host_check.parse_gpus("0, GPU, 24564, 25000, 570.124.06\n")
    with pytest.raises(ValueError):
        host_check.parse_gpus("0, GPU, N/A, N/A, driver\n")

    def unavailable(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(host_check.subprocess, "run", unavailable)
    report = host_check.inspect_host(tmp_path / "missing")
    assert "NVIDIA_QUERY_FAILED" in report["blocking_issues"]
    assert "STORAGE_PATH_UNAVAILABLE" in report["blocking_issues"]
    assert report["training_verified"] is False
    assert report["cuda_runtime_verified"] is False
