"""Serialize source-dependent mutations with deletion and identity remapping."""

from contextlib import contextmanager
from functools import wraps

from filelock import FileLock, Timeout

from chattwin.domain import DomainError


@contextmanager
def source_lease(store):
    # An in-flight bounded HTTP generation owns the same lock for up to 35 s.
    try:
        with FileLock(store.root / "data-management.lock", timeout=45):
            yield
    except Timeout as exc:
        raise DomainError("DATA_BUSY", "来源数据正在使用或更新，请稍后重试。", 409) from exc


def source_guard(function):
    @wraps(function)
    def guarded(service, *args, **kwargs):
        with source_lease(service.store):
            return function(service, *args, **kwargs)

    return guarded
