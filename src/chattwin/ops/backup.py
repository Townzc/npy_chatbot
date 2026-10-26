"""Consistent SQLite snapshots with referenced immutable datasets, restored paused."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterator

from filelock import FileLock

from chattwin.storage import Store
from chattwin.storage.schema_v1 import metadata as schema_v1

BACKUP_VERSION = "1.0"
SUPPORTED_REVISIONS = {"0001", "0002"}
DATASET_FILES = {"manifest.json", "train.jsonl", "validation.jsonl", "test.jsonl"}
EXCLUSIONS = [
    "owner-token and environment credentials (regenerate owner authentication after restore)",
    "raw imported files and temporary uploads; normalized message contents are in SQLite",
    "QQ sessions, bridge configuration, process locks and runtime caches",
    "base model weights, adapter binaries, optimizer checkpoints and external training outputs",
    "unregistered files and unreferenced dataset directories",
]


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _canonical_location(path: Path | str) -> Path:
    original = Path(path).expanduser().absolute()
    if any(component.is_symlink() for component in (original, *original.parents)):
        raise ValueError(
            "backup/restore location or parent must not be a symlink; use its canonical path"
        )
    return original.resolve()


def _relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or str(path) != value
        or "\x00" in value
    ):
        raise ValueError("invalid backup path; traversal is forbidden")
    return path


def _allowed_file(value: str) -> bool:
    path = _relative(value)
    if value == "chattwin.sqlite3":
        return True
    if len(path.parts) == 3 and re.fullmatch(r"[A-Za-z0-9_-]+", path.parts[1]):
        return (path.parts[0] == "datasets" and path.parts[2] in DATASET_FILES) or (
            path.parts[0] == "model_manifests" and path.parts[2] == "manifest.json"
        )
    return False


@contextmanager
def _regular_file(root: Path, relative: str) -> Iterator[BinaryIO]:
    """Open each directory and the leaf with O_NOFOLLOW; reject non-regular files."""
    parts = _relative(relative).parts
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError("backup content must consist of regular files")
        with os.fdopen(descriptor, "rb") as handle:
            yield handle
    finally:
        os.close(directory)


def _read_json(root: Path, relative: str) -> dict[str, Any]:
    with _regular_file(root, relative) as handle:
        result = json.load(handle)
    if not isinstance(result, dict):
        raise ValueError("expected a JSON object")
    return result


def _file_info(root: Path, relative: str) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with _regular_file(root, relative) as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return {"sha256": digest.hexdigest(), "size": size}


def _copy_regular(source: Path, relative: str, target: Path) -> dict[str, Any]:
    destination = target / relative
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    with _regular_file(source, relative) as reader:
        descriptor = os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "wb") as writer:
            for block in iter(lambda: reader.read(1024 * 1024), b""):
                writer.write(block)
                digest.update(block)
                size += len(block)
            writer.flush()
            os.fsync(writer.fileno())
    return {"sha256": digest.hexdigest(), "size": size}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_database(path: Path) -> sqlite3.Connection:
    # Snapshot files have no WAL dependencies. immutable avoids writing sidecars.
    connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.execute("PRAGMA trusted_schema=OFF")
    return connection


def _database_revision(connection: sqlite3.Connection) -> str:
    values = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    if len(values) != 1 or values[0][0] not in SUPPORTED_REVISIONS:
        raise ValueError("unsupported database schema revision")
    return values[0][0]


def _schema_columns(revision: str) -> dict[str, list[str]]:
    columns = {name: list(table.columns.keys()) for name, table in schema_v1.tables.items()}
    if revision == "0002":
        columns["model_deployments"] = [
            "id",
            "persona_id",
            "relationship_id",
            "artifact_id",
            "status",
            "payload",
        ]
    return columns


def _validate_database(path: Path, expected_revision: str | None = None) -> dict[str, int]:
    connection = _read_database(path)
    try:
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("SQLite foreign key check failed")
        revision = _database_revision(connection)
        if expected_revision and revision != expected_revision:
            raise ValueError("database schema revision does not match backup manifest")
        schema = _schema_columns(revision)
        objects = connection.execute(
            "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if any(kind in {"trigger", "view"} for kind, _ in objects):
            raise ValueError("unexpected executable SQLite schema object")
        tables = {name for kind, name in objects if kind == "table"}
        if tables != set(schema) | {"alembic_version"}:
            raise ValueError("database table schema differs from supported revision")
        counts = {}
        for name, expected_columns in schema.items():
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{name}")')]
            if columns != expected_columns:
                raise ValueError("database column schema differs from supported revision")
            counts[name] = connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        return counts
    finally:
        connection.close()


def _validate_datasets(root: Path, files: dict[str, Any]) -> None:
    connection = _read_database(root / "chattwin.sqlite3")
    try:
        for dataset_id, payload in connection.execute("SELECT id, payload FROM dataset_versions"):
            if not re.fullmatch(r"[A-Za-z0-9_-]+", dataset_id):
                raise ValueError("invalid dataset identifier")
            disk_path = f"datasets/{dataset_id}/manifest.json"
            stored = json.loads(payload)
            if stored.get("status") == "revoked":
                if any(name.startswith(f"datasets/{dataset_id}/") for name in files):
                    raise ValueError("revoked dataset contents must not be included or restored")
                continue
            if disk_path not in files:
                raise ValueError("snapshot references a dataset absent from the backup")
            disk = _read_json(root, disk_path)
            if disk != stored or disk.get("id") != dataset_id:
                raise ValueError("dataset manifest does not match database snapshot")
            if disk.get("dataset_hash") != _digest(
                {k: v for k, v in disk.items() if k not in {"dataset_hash", "path"}}
            ):
                raise ValueError("dataset manifest hash mismatch")
            for name in DATASET_FILES - {"manifest.json"}:
                entry = files.get(f"datasets/{dataset_id}/{name}", {})
                if entry.get("sha256") != disk.get("files", {}).get(name):
                    raise ValueError("dataset split hash mismatch")
    finally:
        connection.close()


def create_backup(store: Store, destination: Path | str) -> dict[str, Any]:
    """Create a new backup directory atomically, never overwrite an existing path."""
    # Deletion/identity changes use this same lock while quarantining datasets.
    with FileLock(store.root / "data-management.lock", timeout=10):
        return _create_backup_locked(store, destination)


def _create_backup_locked(store: Store, destination: Path | str) -> dict[str, Any]:
    destination = _canonical_location(destination)
    if destination.exists() or destination.is_relative_to(store.root):
        raise ValueError("backup destination must be new and outside the live data directory")
    if any((parent / ".git").exists() for parent in (destination, *destination.parents)):
        raise ValueError("private backups must stay outside Git checkouts")
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".chattwin-backup-", dir=destination.parent))
    try:
        if store.path.is_symlink():
            raise ValueError("database file must not be a symlink")
        source = sqlite3.connect(store.path.as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(stage / "chattwin.sqlite3")
        try:
            source.backup(target, pages=256)
            target.execute("PRAGMA journal_mode=DELETE")
        finally:
            source.close()
            target.close()
        (stage / "chattwin.sqlite3").chmod(0o600)
        counts = _validate_database(stage / "chattwin.sqlite3")
        files = {"chattwin.sqlite3": _file_info(stage, "chattwin.sqlite3")}
        omitted_models = []
        revoked_datasets = []
        connection = _read_database(stage / "chattwin.sqlite3")
        try:
            revision = _database_revision(connection)
            for dataset_id, payload in connection.execute(
                "SELECT id,payload FROM dataset_versions"
            ):
                if not re.fullmatch(r"[A-Za-z0-9_-]+", dataset_id):
                    raise ValueError("invalid dataset identifier")
                if json.loads(payload).get("status") == "revoked":
                    revoked_datasets.append(
                        {"dataset_id": dataset_id, "status": "revoked", "contents_included": False}
                    )
                    continue
                for name in sorted(DATASET_FILES):
                    relative = f"datasets/{dataset_id}/{name}"
                    files[relative] = _copy_regular(store.root, relative, stage)
            for artifact_id, payload in connection.execute(
                "SELECT id, payload FROM model_artifacts"
            ):
                row = json.loads(payload)
                location = row.get("artifact_path") or row.get("path")
                reason = "model binaries excluded; metadata retained in database"
                if row.get("status") == "revoked":
                    omitted_models.append(
                        {"artifact_id": artifact_id, "reason": "revoked artifact; files excluded"}
                    )
                    continue
                if location and re.fullmatch(r"[A-Za-z0-9_-]+", artifact_id):
                    path = Path(location).expanduser()
                    path = path if path.is_absolute() else store.root / path
                    # Reject links before resolving and never traverse outside this private root.
                    if path.is_symlink():
                        raise ValueError("model artifact path must not be a symlink")
                    if path.is_relative_to(store.root):
                        relative = str((path / "manifest.json").relative_to(store.root))
                        artifact_manifest = _read_json(store.root, relative)
                        local = f"model_manifests/{artifact_id}/manifest.json"
                        (stage / local).parent.mkdir(parents=True, mode=0o700)
                        _write_json(stage / local, artifact_manifest)
                        files[local] = _file_info(stage, local)
                    else:
                        reason = "external artifact files excluded; metadata retained in database"
                omitted_models.append({"artifact_id": artifact_id, "reason": reason})
        finally:
            connection.close()
        _validate_datasets(stage, files)
        manifest = {
            "schema_version": BACKUP_VERSION,
            "database_revision": revision,
            "created_at": datetime.now(UTC).isoformat(),
            "files": files,
            "row_counts": counts,
            "excluded": EXCLUSIONS,
            "model_artifacts": omitted_models,
            "revoked_datasets": revoked_datasets,
            "contains_private_chat_data": True,
            "encrypted": False,
            "restore_policy": "empty target; archive bindings; pause sessions; no queued sends",
        }
        manifest["manifest_hash"] = _digest(manifest)
        _write_json(stage / "backup-manifest.json", manifest)
        inspect_backup(stage)
        if destination.exists():
            raise ValueError("backup destination appeared during snapshot; refusing overwrite")
        stage.rename(destination)
        return {**manifest, "path": str(destination)}
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def inspect_backup(path: Path | str) -> dict[str, Any]:
    root = _canonical_location(path)
    manifest = _read_json(root, "backup-manifest.json")
    if (
        manifest.get("schema_version") != BACKUP_VERSION
        or manifest.get("database_revision") not in SUPPORTED_REVISIONS
    ):
        raise ValueError("unsupported backup/schema version")
    if manifest.get("manifest_hash") != _digest(
        {k: v for k, v in manifest.items() if k != "manifest_hash"}
    ):
        raise ValueError("backup manifest hash mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict) or "chattwin.sqlite3" not in files:
        raise ValueError("backup has no SQLite snapshot")
    for relative, info in files.items():
        if not _allowed_file(relative):
            raise ValueError("unexpected backup file path")
        if _file_info(root, relative) != info:
            raise ValueError(f"backup checksum mismatch: {relative}")
    # Reject hidden extras, symlinks and unlisted files, including injected secrets.
    found = set()
    for current, directories, filenames in os.walk(root, followlinks=False):
        for name in directories + filenames:
            if (Path(current) / name).is_symlink():
                raise ValueError("backup must not contain symlinks")
        for name in filenames:
            found.add(str((Path(current) / name).relative_to(root)))
    if found != set(files) | {"backup-manifest.json"}:
        raise ValueError("backup contains unlisted or missing files")
    counts = _validate_database(root / "chattwin.sqlite3", manifest["database_revision"])
    if counts != manifest.get("row_counts"):
        raise ValueError("backup database counts do not match manifest")
    _validate_datasets(root, files)
    return {**manifest, "path": str(root), "verified": True}


def _pause_restored_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA foreign_keys=ON")
        with connection:
            revision = _database_revision(connection)
            connection.execute("UPDATE bindings SET active=0")
            connection.execute(
                "UPDATE mode_sessions SET mode='PAUSED', control_epoch=control_epoch+1"
            )
            connection.execute(
                "UPDATE outbox SET status='cancelled' WHERE status IN ('planned','claimed')"
            )
            connection.execute("UPDATE outbox SET status='unknown' WHERE status='submitting'")
            connection.execute(
                "UPDATE jobs SET status='interrupted' WHERE status IN ('queued','validating','running')"
            )
            for binding_id, payload in connection.execute(
                "SELECT binding_id,payload FROM mode_sessions"
            ).fetchall():
                value = json.loads(payload)
                value.update(model_deployment_id="mock-v1", restore_requires_review=True)
                connection.execute(
                    "UPDATE mode_sessions SET payload=? WHERE binding_id=?",
                    (json.dumps(value), binding_id),
                )
            for artifact_id, payload in connection.execute(
                "SELECT id,payload FROM model_artifacts"
            ).fetchall():
                value = json.loads(payload)
                value.update(
                    status="revoked" if value.get("status") == "revoked" else "unavailable",
                    deployment_status="unavailable",
                    restore_requires_verification=True,
                    restore_reason="model binaries were not included in this backup",
                )
                connection.execute(
                    "UPDATE model_artifacts SET payload=? WHERE id=?",
                    (json.dumps(value), artifact_id),
                )
            if revision == "0002":
                for deployment_id, payload in connection.execute(
                    "SELECT id,payload FROM model_deployments"
                ).fetchall():
                    value = json.loads(payload)
                    value.update(
                        status="revoked",
                        restore_requires_verification=True,
                        revoked_reason="backup_restore_requires_revalidation",
                    )
                    connection.execute(
                        "UPDATE model_deployments SET status='revoked',payload=? WHERE id=?",
                        (json.dumps(value), deployment_id),
                    )
            connection.execute(
                "INSERT INTO audit_events(id,kind,payload) VALUES(?,?,?)",
                (
                    str(uuid.uuid4()),
                    "backup_restored",
                    json.dumps(
                        {
                            "at": datetime.now(UTC).isoformat(),
                            "bindings_archived": True,
                            "owner_authentication": "regenerate",
                            "model_weights_restored": False,
                        }
                    ),
                ),
            )
    finally:
        connection.close()


def restore_backup(path: Path | str, target: Path | str) -> dict[str, Any]:
    """Restore only into an empty/new directory under an exclusive maintenance lock."""
    backup = _canonical_location(path)
    target = _canonical_location(target)
    if target == backup or target.is_relative_to(backup):
        raise ValueError("restore target cannot be inside the backup")
    if any((parent / ".git").exists() for parent in (target, *target.parents)):
        raise ValueError("private restored data must stay outside Git checkouts")
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    lock = target.parent / ("." + target.name + ".maintenance.lock")
    with FileLock(lock, timeout=0):
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ValueError(
                "restore requires an empty target; running/existing instances cannot be overwritten"
            )
        manifest = inspect_backup(backup)
        stage = Path(tempfile.mkdtemp(prefix=".chattwin-restore-", dir=target.parent))
        try:
            for relative, info in manifest["files"].items():
                if _copy_regular(backup, relative, stage) != info:
                    raise ValueError("backup changed while restoring")
            _validate_database(stage / "chattwin.sqlite3")
            _validate_datasets(stage, manifest["files"])
            _pause_restored_database(stage / "chattwin.sqlite3")
            if target.exists() and (not target.is_dir() or any(target.iterdir())):
                raise ValueError("restore target became nonempty; refusing overwrite")
            os.replace(stage, target)
            return {
                "path": str(target),
                "status": "restored_paused",
                "bindings_archived": True,
                "owner_token_restored": False,
                "model_weights_restored": False,
                "backup_manifest_hash": manifest["manifest_hash"],
            }
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise
