"""CUDA metadata only; no model load, downloads, credentials or device UUIDs."""

from typing import Any


def inspect_cuda(torch: Any) -> dict[str, Any]:
    available = torch.cuda.is_available()
    devices = []
    for index in range(torch.cuda.device_count() if available else 0):
        properties = torch.cuda.get_device_properties(index)
        free, total = torch.cuda.mem_get_info(index)
        devices.append(
            {
                "index": index,
                "name": properties.name,
                "total_memory_bytes": total,
                "free_memory_bytes": free,
                "compute_capability": [properties.major, properties.minor],
            }
        )
    return {
        "cuda_available": available,
        "cuda_runtime": torch.version.cuda,
        "cuda_devices": devices,
        "active_cuda_device": torch.cuda.current_device() if available else None,
        "cuda_bf16_supported": bool(
            available and torch.cuda.is_bf16_supported(including_emulation=False)
        ),
    }
