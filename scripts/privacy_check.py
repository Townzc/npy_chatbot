"""Check indexed paths and bytes before code publication, never read private inputs."""

import re
import subprocess
from pathlib import PurePosixPath

paths = list(filter(None, subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")))
blocked = []
secret_patterns = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}\b"),
    re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{24,}\b"),
]
for value in paths:
    path = PurePosixPath(value)
    if (
        path.parts[0] in {"chat_record", "data", "private", "artifacts", "datasets", "backups"}
        or path.name in {"owner-token", ".env"}
        or (path.name.startswith(".env.") and path.name not in {".env.example", ".env.template"})
        or path.suffix
        in {
            ".sqlite",
            ".sqlite3",
            ".db",
            ".safetensors",
            ".pt",
            ".pth",
            ".ckpt",
            ".gguf",
            ".bin",
            ".pem",
            ".zip",
            ".bak",
        }
    ):
        blocked.append((value, "private runtime path"))
        continue
    content = subprocess.check_output(["git", "show", ":" + value])
    if content.startswith((b"SQLite header 3\0", b"SQLite format 3\0")):
        blocked.append((value, "database file signature"))
    if any(pattern.search(content) for pattern in secret_patterns):
        blocked.append((value, "credential signature"))
if blocked:
    # Never print matched bytes or credentials.
    raise SystemExit("Publication guard failed: " + ", ".join(f"{p} ({why})" for p, why in blocked))
print(
    f"Git index privacy guard passed ({len(paths)} paths, high-confidence credential signatures checked)."
)
print(
    "This is a guard, not proof that arbitrary private text is absent; review staged changes as well."
)
