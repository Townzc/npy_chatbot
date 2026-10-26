"""Resolve pinned worker resources in both source checkouts and installed wheels."""

import hashlib
import json
import os
from pathlib import Path

SOURCE_ASSETS = (
    "pyproject.toml",
    "uv.lock",
    "LICENSE",
    "training/pyproject.toml",
    "training/uv.lock",
)


def package_root() -> Path:
    return Path(__file__).resolve().parent


def source_root() -> Path:
    package = package_root()
    checkout = package.parent.parent
    if (
        package.parent.name == "src"
        and (checkout / "pyproject.toml").is_file()
        and (checkout / "src/chattwin/runtime_paths.py").resolve() == Path(__file__).resolve()
    ):
        return checkout
    installed = package / "resources/source"
    if not all((installed / asset).is_file() for asset in SOURCE_ASSETS):
        raise ValueError("installed ChatTwin package is missing pinned training resources")
    return installed


def source_asset(relative: str) -> Path:
    if relative not in SOURCE_ASSETS:
        raise ValueError("unknown packaged source asset")
    path = source_root() / relative
    if not path.is_file():
        raise ValueError("required training resource is missing")
    return path


def training_lock_path() -> Path:
    return source_asset("training/uv.lock")


def training_code_hash(package: Path | None = None) -> str:
    """Content identity, independent of checkout/install path and Git availability.

    Only the executable training package and its resource resolver are included;
    the full application/jobs/UI are intentionally absent from portable bundles.
    """
    root = package or package_root()
    training = root / "training"
    files = [root / "runtime_paths.py", *sorted(training.rglob("*.py"))]
    if training.is_symlink() or not (training / "worker.py").is_file():
        raise ValueError("training source package is missing or unsafe")
    hashes = {}
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError("training source files must be regular non-symlink files")
        if any((root / parent).is_symlink() for parent in path.relative_to(root).parents):
            raise ValueError("training source directories must not be symlinks")
        hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(
        json.dumps(hashes, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def training_python_path() -> Path:
    override = os.environ.get("CHATTWIN_TRAINING_PYTHON")
    if override:
        value = Path(override).expanduser()
        if not value.is_absolute():
            raise ValueError("CHATTWIN_TRAINING_PYTHON must name an absolute interpreter path")
        # Do not resolve: venv interpreters commonly symlink to a shared Python;
        # invoking the original venv path is what selects its installed packages.
        return value
    binary = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return source_root() / "training/.venv" / binary
