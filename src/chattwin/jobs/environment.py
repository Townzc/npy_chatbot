"""Read-only training hardware probe: imports dependencies, never a model."""

import json
import platform
import subprocess
from pathlib import Path

from chattwin.runtime_paths import training_python_path
from chattwin.training.spec import QWEN_REVISION, QWEN_TEMPLATE_HASH
from chattwin.training.worker import worker_environment

from .models import CudaDevice, TrainingEnvironment


def training_python() -> Path:
    return training_python_path()


PROBE_CODE = """
import importlib.metadata, json, platform
result = {'platform': platform.system(), 'python_version': platform.python_version()}
try:
 import torch
 from chattwin.training.hardware import inspect_cuda
 result.update(dependencies={n: importlib.metadata.version(n) for n in ('torch','transformers','peft','accelerate','safetensors')})
 result.update(inspect_cuda(torch))
except ImportError:
 result['dependency_error'] = True
print(json.dumps(result))
"""


def inspect_environment(python: Path | None = None) -> TrainingEnvironment:
    python = python or training_python()
    result = TrainingEnvironment(
        python_available=python.is_file(),
        dependencies_available=False,
        platform=platform.system(),
        reference_model={
            "id": "Qwen/Qwen3-4B-Instruct-2507",
            "revision": QWEN_REVISION,
            "chat_template_hash": QWEN_TEMPLATE_HASH,
        },
    )
    if not python.is_file():
        result.blockers = ["TRAINING_ENVIRONMENT_MISSING"]
        return result
    try:
        probe = subprocess.run(
            [str(python), "-c", PROBE_CODE],
            env=worker_environment(),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if probe.returncode:
            result.blockers = ["TRAINING_ENVIRONMENT_INVALID"]
            return result
        data = json.loads(probe.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        result.blockers = ["TRAINING_ENVIRONMENT_INVALID"]
        return result
    pins = {
        "torch": "2.9.1",
        "transformers": "4.57.6",
        "peft": "0.18.1",
        "accelerate": "1.12.0",
        "safetensors": "0.7.0",
    }
    result.dependencies = data.get("dependencies", {})
    result.dependencies_available = all(
        result.dependencies.get(name, "").split("+")[0] == version for name, version in pins.items()
    )
    result.platform = data.get("platform", result.platform)
    result.python_version = data.get("python_version")
    result.cuda_available = data.get("cuda_available", False)
    result.cuda_bf16_supported = data.get("cuda_bf16_supported", False)
    result.cuda_runtime = data.get("cuda_runtime")
    result.cuda_devices = [
        CudaDevice.model_validate(device) for device in data.get("cuda_devices", [])
    ]
    result.active_cuda_device = data.get("active_cuda_device")
    result.tiny_available = result.dependencies_available
    result.supports_reference_training = (
        result.dependencies_available and result.cuda_available and result.platform == "Linux"
    )
    if not result.dependencies_available:
        result.blockers.append("TRAINING_DEPENDENCIES_MISMATCH")
    if not result.cuda_available:
        result.blockers.append("CUDA_UNAVAILABLE")
    if result.platform != "Linux":
        result.blockers.append("REFERENCE_HOST_UNVERIFIED")
    return result
