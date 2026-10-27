"""Read host capacity before installing/downloading; never starts a training job."""

import argparse
import csv
import io
import json
import platform
import shutil
import subprocess
from pathlib import Path

GIB = 1024**3


def read_memory(proc: Path = Path("/proc"), cgroup: Path = Path("/sys/fs/cgroup")) -> dict:
    """Use visible cgroup limits; hidden parent limits still need the rental console."""
    physical = None
    try:
        for line in (proc / "meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                physical = int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    limits = []
    candidates = {cgroup / "memory.max", cgroup / "memory/memory.limit_in_bytes"}
    try:
        for line in (proc / "self/cgroup").read_text().splitlines():
            _, controllers, relative = line.split(":", 2)
            relative_path = Path(relative.lstrip("/"))
            if ".." in relative_path.parts:
                continue
            if not controllers:
                base, filename = cgroup, "memory.max"
            elif "memory" in controllers.split(","):
                base, filename = cgroup / "memory", "memory.limit_in_bytes"
            else:
                continue
            for parent in [relative_path, *relative_path.parents]:
                candidates.add(base / parent / filename)
    except (OSError, ValueError):
        pass
    for path in candidates:
        try:
            value = int(path.read_text().strip())
            # cgroup v1 uses a near-LONG_MAX sentinel for "unlimited".
            if 0 <= value < 2**60:
                limits.append(value)
        except (OSError, ValueError):
            continue
    visible_limit = min(limits) if limits else None
    known = [value for value in (physical, visible_limit) if value is not None]
    return {
        "physical_total_bytes": physical,
        "visible_cgroup_limit_bytes": visible_limit,
        "known_capacity_bound_bytes": min(known) if known else None,
        "rental_console_memory_still_required": True,
    }


def parse_gpus(output: str) -> list[dict]:
    devices = []
    for row in csv.reader(io.StringIO(output)):
        if len(row) != 5:
            raise ValueError("unexpected GPU query columns")
        index, name, total, free, driver = (value.strip() for value in row)
        total_bytes, free_bytes = int(total) * 1024**2, int(free) * 1024**2
        if int(index) < 0 or not 0 <= free_bytes <= total_bytes or not name:
            raise ValueError("invalid GPU query values")
        devices.append(
            {
                "physical_index": int(index),
                "name": name,
                "total_memory_bytes": total_bytes,
                "free_memory_bytes": free_bytes,
                "driver_version": driver,
            }
        )
    return devices


def inspect_host(storage: Path) -> dict:
    issues, warnings = [], []
    system, machine = platform.system(), platform.machine()
    if system != "Linux" or machine not in {"x86_64", "AMD64"}:
        issues.append("REFERENCE_HOST_REQUIRES_LINUX_X86_64")
    disk_free = None
    try:
        disk_free = shutil.disk_usage(storage).free
        if disk_free < 60 * GIB:
            warnings.append("LESS_THAN_RECOMMENDED_60_GIB_FREE_DISK")
    except OSError:
        issues.append("STORAGE_PATH_UNAVAILABLE")
    memory = read_memory()
    bound = memory["known_capacity_bound_bytes"]
    if bound is None or bound < 32 * GIB:
        warnings.append("CHECK_STARTING_32_GIB_RAM_IN_RENTAL_CONSOLE")
    if memory["visible_cgroup_limit_bytes"] is None:
        warnings.append("CONTAINER_MEMORY_LIMIT_UNKNOWN")
    devices = []
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.free,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        devices = parse_gpus(result.stdout)
        if not devices:
            issues.append("NO_VISIBLE_NVIDIA_GPU")
    except (OSError, ValueError, subprocess.SubprocessError):
        issues.append("NVIDIA_QUERY_FAILED")
    if devices:
        # nvidia-smi is physical inventory, not CUDA_VISIBLE_DEVICES process mapping.
        warnings.append("CHECK_SELECTED_GPU_DRIVER_AND_FREE_MEMORY_BEFORE_TRAINING")
    return {
        "system": system,
        "machine": machine,
        "storage_free_bytes": disk_free,
        "memory": memory,
        "physical_gpu_inventory": devices,
        "blocking_issues": issues,
        "warnings": warnings,
        "training_verified": False,
        "model_downloaded": False,
        "cuda_runtime_verified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage", type=Path, required=True, help="existing data disk directory")
    args = parser.parse_args()
    report = inspect_host(args.storage.expanduser())
    print(json.dumps(report, indent=2))
    raise SystemExit(2 if report["blocking_issues"] else 0)


if __name__ == "__main__":
    main()
