"""Generate a private macOS launchd definition without installing or starting it."""

import os
import plistlib
from pathlib import Path

from chattwin.storage import Store


def write_launch_agent(
    destination: Path, executable: Path, data_dir: Path, port: int = 8765, allowed_host: str = ""
) -> dict:
    destination = destination.expanduser().absolute()
    executable = executable.expanduser().absolute()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("Use the installed chattwin executable, not a shell command")
    if not 1024 <= port <= 65535:
        raise ValueError("Use an unprivileged TCP port")
    if allowed_host and (
        "/" in allowed_host
        or ":" in allowed_host
        or "*" in allowed_host
        or any(c.isspace() for c in allowed_host)
    ):
        raise ValueError("Use an exact tailnet DNS hostname, without scheme or port")
    if destination.is_symlink() or destination.exists():
        raise ValueError("Destination must be a new regular file")
    if any((p / ".git").exists() for p in (destination.parent, *destination.parents)):
        raise ValueError("Host paths and configuration must stay outside Git")
    store = Store(data_dir)
    root = store.root
    store.close()
    environment = {"CHATTWIN_DATA_DIR": str(root), "CHATTWIN_REQUIRE_SESSION": "1"}
    if allowed_host:
        environment["CHATTWIN_ALLOWED_HOSTS"] = allowed_host
    definition = {
        "Label": "local.chattwin.owner",
        "ProgramArguments": [str(executable), "serve", "--port", str(port)],
        "WorkingDirectory": str(root),
        "EnvironmentVariables": environment,
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 15,
        "StandardOutPath": str(root / "service.stdout.log"),
        "StandardErrorPath": str(root / "service.stderr.log"),
        "Umask": 0o077,
    }
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with destination.open("xb") as handle:
        destination.chmod(0o600)
        plistlib.dump(definition, handle)
    return {
        "path": str(destination),
        "label": definition["Label"],
        "installed": False,
        "started": False,
        "qq_enabled": False,
    }
