"""Owner-only diagnostics and local backups; restore remains an offline operation."""

import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from chattwin.domain import DomainError
from chattwin.ops.service import (
    BackupCreated,
    BackupEntry,
    DiagnosticsReport,
    EmptyBackupRequest,
    OperationsService,
)
from chattwin.storage import Store


def ops_router(store: Store, authenticate) -> APIRouter:
    service = OperationsService(store)
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)])

    @router.get("/diagnostics", response_model=DiagnosticsReport)
    async def diagnostics():
        try:
            return await asyncio.to_thread(service.diagnostics)
        except (OSError, ValueError) as exc:
            raise DomainError(
                "DIAGNOSTICS_FAILED", "Local diagnostics could not be completed", 409
            ) from exc

    @router.get("/backups", response_model=list[BackupEntry])
    async def backups():
        try:
            return await asyncio.to_thread(service.list_backups)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise DomainError(
                "BACKUP_CATALOG_INVALID", "A stored backup failed catalog validation", 409
            ) from exc

    @router.post("/backups", response_model=BackupCreated, status_code=201)
    async def create(_body: EmptyBackupRequest):
        try:
            return await asyncio.to_thread(service.create)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise DomainError(
                "BACKUP_FAILED", "Backup was not published; local validation failed", 409
            ) from exc

    @router.get("/backups/{backup_id}/download")
    async def download(backup_id: str):
        try:
            archive = await asyncio.to_thread(service.download, backup_id)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise DomainError(
                "BACKUP_INVALID", "Backup failed validation; download was not created", 409
            ) from exc
        return FileResponse(
            archive,
            media_type="application/zip",
            filename="chattwin-private-backup.zip",
            background=BackgroundTask(archive.unlink, missing_ok=True),
            headers={"Cache-Control": "no-store", "X-ChatTwin-Private-Data": "true"},
        )

    return router
