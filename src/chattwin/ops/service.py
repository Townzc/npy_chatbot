"""Private backup catalog and a deliberately content-free diagnostic report."""

from __future__ import annotations

import hashlib
import os
import platform
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from chattwin import __version__
from chattwin.domain import DomainError
from chattwin.storage import Store

from .backup import (
    BACKUP_VERSION,
    SUPPORTED_REVISIONS,
    _canonical_location,
    _digest,
    _file_info,
    _read_json,
    _regular_file,
    _schema_columns,
    create_backup,
    inspect_backup,
)


class BackupEntry(BaseModel):
    id: str
    created_at: str
    bytes: int


class BackupReport(BaseModel):
    database_revision: str
    created_at: str
    row_counts: dict[str, int]
    files_count: int
    bytes: int
    revoked_datasets_omitted: int
    contains_private_chat_data: Literal[True] = True
    encrypted: Literal[False] = False
    excluded: list[str]


class BackupCreated(BaseModel):
    id: str
    report: BackupReport


class DiagnosticsReport(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    database_revision: str
    app_version: str
    platform: str
    counts: dict[str, int]
    states: dict[str, dict[str, int]]
    storage: dict[str, int]
    privacy: dict[str, bool]
    checks: dict[str, bool]
    generated_at: str


class EmptyBackupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _backup_id(value: str) -> str:
    try:
        if str(UUID(value)) != value:
            raise ValueError()
    except ValueError as exc:
        raise DomainError("INVALID_BACKUP_ID", "Backup ID must be a canonical UUID", 422) from exc
    return value


class OperationsService:
    def __init__(self, store: Store):
        self.store = store
        self.root = store.root.parent / (store.root.name + ".backups")

    def _root(self, *, create: bool = False) -> Path:
        root = _canonical_location(self.root)
        if root.is_relative_to(self.store.root):
            raise ValueError("backup catalog must be outside live data")
        if (root / "chattwin.sqlite3").exists():
            raise ValueError("backup catalog collides with an application data directory")
        if create:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            root.chmod(0o700)
        return root

    def list_backups(self) -> list[BackupEntry]:
        root = self._root()
        if not root.exists():
            return []
        result = []
        for directory in root.iterdir():
            try:
                backup_id = _backup_id(directory.name)
            except DomainError:
                continue
            if directory.is_symlink():
                raise ValueError("backup catalog contains a symbolic link")
            if not directory.is_dir():
                continue
            manifest = _read_json(directory, "backup-manifest.json")
            if (
                manifest.get("schema_version") != BACKUP_VERSION
                or manifest.get("database_revision") not in SUPPORTED_REVISIONS
                or manifest.get("manifest_hash")
                != _digest({k: v for k, v in manifest.items() if k != "manifest_hash"})
            ):
                raise ValueError("stored backup manifest is invalid")
            total = sum(info["size"] for info in manifest["files"].values())
            total += _file_info(directory, "backup-manifest.json")["size"]
            result.append(BackupEntry(id=backup_id, created_at=manifest["created_at"], bytes=total))
        return sorted(result, key=lambda entry: entry.created_at, reverse=True)

    def create(self) -> BackupCreated:
        root = self._root(create=True)
        backup_id = str(uuid4())
        manifest = create_backup(self.store, root / backup_id)
        total = sum(info["size"] for info in manifest["files"].values())
        total += _file_info(root / backup_id, "backup-manifest.json")["size"]
        return BackupCreated(
            id=backup_id,
            report=BackupReport(
                database_revision=manifest["database_revision"],
                created_at=manifest["created_at"],
                row_counts=manifest["row_counts"],
                files_count=len(manifest["files"]),
                bytes=total,
                revoked_datasets_omitted=len(manifest.get("revoked_datasets", [])),
                excluded=manifest["excluded"],
            ),
        )

    def download(self, backup_id: str) -> Path:
        root = self._root()
        directory = root / _backup_id(backup_id)
        if directory.is_symlink():
            raise DomainError("INVALID_BACKUP_PATH", "Backup links are not accepted", 422)
        if not directory.is_dir():
            raise DomainError("BACKUP_NOT_FOUND", "Backup not found", 404)
        manifest = inspect_backup(directory)
        descriptor, filename = tempfile.mkstemp(prefix=".download-", suffix=".zip", dir=root)
        os.close(descriptor)
        archive = Path(filename)
        try:
            entries = manifest["files"] | {
                "backup-manifest.json": _file_info(directory, "backup-manifest.json")
            }
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as writer:
                for relative, info in entries.items():
                    digest, size = hashlib.sha256(), 0
                    with (
                        _regular_file(directory, relative) as reader,
                        writer.open(relative, "w") as output,
                    ):
                        for block in iter(lambda: reader.read(1024 * 1024), b""):
                            output.write(block)
                            digest.update(block)
                            size += len(block)
                    if digest.hexdigest() != info["sha256"] or size != info["size"]:
                        raise ValueError("backup changed while packaging download")
            return archive
        except BaseException:
            archive.unlink(missing_ok=True)
            raise

    def diagnostics(self) -> DiagnosticsReport:
        with self.store.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            revision: str = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one()
            if revision not in SUPPORTED_REVISIONS:
                raise ValueError("unsupported diagnostic schema")
            counts: dict[str, int] = {
                name: connection.exec_driver_sql(f'SELECT COUNT(*) FROM "{name}"').scalar_one()
                for name in _schema_columns(revision)
            }
            states: dict[str, dict[str, int]] = {}
            categories = {
                "sessions": ("mode_sessions", "mode", {"HUMAN", "ENABLING", "AI_ACTIVE", "PAUSED"}),
                "outbox": (
                    "outbox",
                    "status",
                    {
                        "planned",
                        "claimed",
                        "submitting",
                        "confirmed",
                        "rejected",
                        "unknown",
                        "cancelled",
                    },
                ),
                "jobs": (
                    "jobs",
                    "status",
                    {
                        "queued",
                        "validating",
                        "running",
                        "succeeded",
                        "failed",
                        "cancelled",
                        "interrupted",
                    },
                ),
                "deployments": (
                    "model_deployments",
                    "status",
                    {"unverified", "ready", "active", "revoked", "unavailable"},
                ),
            }
            for key, (table, column, allowed) in categories.items():
                states[key] = {}
                if table not in _schema_columns(revision):
                    continue
                for value, count in connection.exec_driver_sql(
                    f'SELECT "{column}",COUNT(*) FROM "{table}" GROUP BY "{column}"'
                ):
                    label = value if value in allowed else "other"
                    states[key][label] = states[key].get(label, 0) + int(str(count))
            foreign_keys_ok = not bool(
                connection.exec_driver_sql("PRAGMA foreign_key_check").first()
            )
        database_bytes = sum(
            path.stat().st_size
            for path in (self.store.path, Path(str(self.store.path) + "-wal"))
            if path.exists() and not path.is_symlink()
        )
        try:
            backup_count, catalog_ok = len(self.list_backups()), True
        except (OSError, ValueError, KeyError, TypeError):
            backup_count, catalog_ok = 0, False
        return DiagnosticsReport(
            database_revision=revision,
            app_version=__version__,
            platform=platform.system(),
            counts=counts,
            states=states,
            storage={"database_bytes": database_bytes, "backups_count": backup_count},
            privacy={
                "chat_content_included": False,
                "secrets_included": False,
                "paths_included": False,
            },
            checks={"foreign_keys_ok": foreign_keys_ok, "backup_catalog_ok": catalog_ok},
            generated_at=datetime.now(UTC).isoformat(),
        )
