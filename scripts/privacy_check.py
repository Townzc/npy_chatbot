"""Fail on private runtime artifacts in the Git index; no private source reads."""

import subprocess
from pathlib import PurePosixPath

paths = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
blocked = []
for value in filter(None, paths):
    path = PurePosixPath(value)
    if (
        path.parts[0] in {"chat_record", "data", "private", "artifacts", "datasets"}
        or path.name in {"owner-token", ".env"}
        or path.suffix in {".sqlite", ".sqlite3", ".db", ".safetensors", ".pt", ".bin", ".pem"}
    ):
        blocked.append(value)
if blocked:
    raise SystemExit("Private artifact paths found in index: " + ", ".join(blocked))
print(f"Git privacy path check passed ({len(list(filter(None, paths)))} tracked paths).")
