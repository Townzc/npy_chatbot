"""Hardware API contracts only; fixtures are not evidence of a physical CUDA run."""

from types import SimpleNamespace

from chattwin.training.hardware import inspect_cuda


def test_probe_retains_individual_gpu_memory_and_selected_device():
    calls = []

    def memory(index):
        calls.append(index)
        return ((10 + index) * 1024**3, 24 * 1024**3)

    def bf16(*, including_emulation):
        assert including_emulation is False
        return True

    cuda = SimpleNamespace(
        is_available=lambda: True,
        device_count=lambda: 2,
        get_device_properties=lambda index: SimpleNamespace(
            name=f"Fixture GPU {index}", major=8, minor=9
        ),
        mem_get_info=memory,
        current_device=lambda: 1,
        is_bf16_supported=bf16,
    )
    result = inspect_cuda(SimpleNamespace(cuda=cuda, version=SimpleNamespace(cuda="12.8")))
    assert calls == [0, 1] and result["active_cuda_device"] == 1
    assert [device["free_memory_bytes"] for device in result["cuda_devices"]] == [
        10 * 1024**3,
        11 * 1024**3,
    ]
    assert all(device["total_memory_bytes"] == 24 * 1024**3 for device in result["cuda_devices"])


def test_no_cuda_probe_does_not_initialize_or_query_devices():
    cuda = SimpleNamespace(is_available=lambda: False)
    result = inspect_cuda(SimpleNamespace(cuda=cuda, version=SimpleNamespace(cuda=None)))
    assert not result["cuda_available"] and not result["cuda_bf16_supported"]
    assert result["cuda_devices"] == [] and result["active_cuda_device"] is None
