"""Authenticated routes. Parent application owns manager lifespan and coordinator."""

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from chattwin.jobs import JobLogs, JobManager, JobView, TrainingEnvironment, TrainingJobRequest
from chattwin.jobs.bundle import create_training_bundle
from chattwin.jobs.environment import inspect_environment
from chattwin.storage import Store


def job_router(
    store: Store,
    get_coordinator: Callable[[], Any],
    authenticate: Callable,
    *,
    manager: JobManager,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)])

    @router.get("/training-environment", response_model=TrainingEnvironment)
    async def environment():
        return await asyncio.to_thread(inspect_environment, manager.python)

    @router.post("/training-jobs", response_model=JobView, status_code=202)
    async def submit(body: TrainingJobRequest):
        return await asyncio.to_thread(manager.submit, body)

    @router.get("/training-jobs", response_model=list[JobView])
    @router.get("/jobs", response_model=list[JobView])
    async def listing(persona_id: str | None = None, relationship_id: str | None = None):
        return manager.list(persona_id, relationship_id)

    @router.get("/training-jobs/{job_id}", response_model=JobView)
    @router.get("/jobs/{job_id}", response_model=JobView)
    async def detail(job_id: str):
        return manager.detail(job_id)

    @router.post("/training-jobs/{job_id}/cancel", response_model=JobView)
    async def cancel(job_id: str):
        return manager.cancel(job_id)

    @router.get("/jobs/{job_id}/logs", response_model=JobLogs)
    async def logs(job_id: str):
        return manager.logs(job_id)

    @router.post("/training-bundles")
    async def bundle(body: TrainingJobRequest):
        path, _manifest = await asyncio.to_thread(create_training_bundle, manager, body)
        return FileResponse(
            path,
            media_type="application/zip",
            filename="chattwin-private-training.zip",
            background=BackgroundTask(path.unlink, missing_ok=True),
            headers={"Cache-Control": "no-store", "X-ChatTwin-Private-Data": "true"},
        )

    return router
