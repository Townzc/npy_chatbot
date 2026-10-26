"""SQLite durable jobs with an isolated single child worker and explicit recovery."""

from __future__ import annotations

import asyncio
import json
import math
import os
import signal
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from filelock import FileLock, Timeout
from sqlalchemy import select

from chattwin.domain import DomainError
from chattwin.storage import Store, datasets, jobs
from chattwin.training.spec import TrainingSpec, prepare_spec, validate_dataset
from chattwin.training.worker import verify_artifact, worker_environment, write_json

from .environment import inspect_environment, training_python
from .models import JobLogs, JobView, TrainingJobRequest

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


class JobManager:
    def __init__(self, store: Store, *, python: Path | None = None, poll_interval: float = 0.25):
        self.store = store
        self.python = python or training_python()
        self.poll_interval = poll_interval
        self.root = store.root / "training-jobs"
        self.lease = FileLock(store.root / "jobs-worker.lock", timeout=0)
        self.data_lock = FileLock(store.root / "data-management.lock", timeout=10)
        self.execution_lease = store.root / "training-execution.lock"
        self.task: asyncio.Task | None = None
        self.wake = asyncio.Event()
        self.started = False
        self.closing = False
        self.process: subprocess.Popen | None = None
        self.active_id: str | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    async def startup(self) -> None:
        if self.started:
            return
        try:
            self.lease.acquire()
        except Timeout as exc:
            raise DomainError(
                "JOB_WORKER_ALREADY_RUNNING", "This data directory already has a job worker"
            ) from exc
        self.root.mkdir(mode=0o700, exist_ok=True)
        # Previous queued jobs also need a new owner action; no hidden restart/resume.
        for row in self.store.rows(jobs, jobs.c.kind == "training"):
            if row["status"] not in TERMINAL:
                self._update(
                    row["id"],
                    status="interrupted",
                    phase="recovered",
                    error_code="PROCESS_RESTARTED",
                    error_summary="服务已重启；任务未自动恢复。",
                    event="interrupted",
                )
        self.started, self.closing = True, False
        self.loop = asyncio.get_running_loop()
        self.task = asyncio.create_task(self._loop())

    def _notify(self) -> None:
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.wake.set)

    async def close(self) -> None:
        if not self.started:
            return
        self.closing = True
        self._notify()
        if self.task:
            await self.task
        self.started = False
        self.lease.release()

    def _row(self, job_id: str) -> dict[str, Any]:
        rows = self.store.rows(jobs, jobs.c.id == job_id, jobs.c.kind == "training")
        if not rows:
            raise DomainError("JOB_NOT_FOUND", "Training job not found", 404)
        return rows[0]

    def _update(self, job_id: str, *, event: str | None = None, **changes: Any) -> None:
        with self.store.transaction() as connection:
            row = connection.execute(select(jobs).where(jobs.c.id == job_id)).mappings().one()
            payload = dict(row["payload"])
            payload.update(changes, updated_at=timestamp())
            if event:
                events = list(payload.get("events", []))
                events.append(
                    {
                        "at": timestamp(),
                        "event": event,
                        "detail": str(changes.get("error_code") or changes.get("phase") or event)[
                            :160
                        ],
                    }
                )
                payload["events"] = events[-100:]
            connection.execute(
                jobs.update()
                .where(jobs.c.id == job_id)
                .values(status=changes.get("status", row["status"]), payload=payload)
            )

    def detail(self, job_id: str) -> JobView:
        row = self._row(job_id)
        payload = row["payload"]
        fields = {name: payload[name] for name in JobView.model_fields if name in payload}
        if payload.get("invalidated"):
            fields.update(
                artifact_ready=False,
                error_code="DATASET_REVOKED",
                error_summary="训练来源已撤销；已有权重不代表已遗忘，不能启用。",
            )
        return JobView.model_validate(
            {**fields, "id": row["id"], "kind": row["kind"], "status": row["status"]}
        )

    def list(
        self, persona_id: str | None = None, relationship_id: str | None = None
    ) -> list[JobView]:
        if bool(persona_id) != bool(relationship_id):
            raise DomainError("SCOPE_REQUIRED", "Specify both persona_id and relationship_id", 422)
        rows = self.store.rows(jobs, jobs.c.kind == "training")
        result = [
            self.detail(row["id"])
            for row in rows
            if not persona_id
            or (row["payload"].get("persona_id"), row["payload"].get("relationship_id"))
            == (persona_id, relationship_id)
        ]
        return sorted(result, key=lambda row: row.created_at, reverse=True)[:200]

    def logs(self, job_id: str) -> JobLogs:
        return JobLogs(events=self._row(job_id)["payload"].get("events", [])[-100:])

    def spec_for_request(self, request: TrainingJobRequest, output: Path) -> TrainingSpec:
        with self.data_lock:
            return self._spec_for_request_locked(request, output)

    def _spec_for_request_locked(self, request: TrainingJobRequest, output: Path) -> TrainingSpec:
        rows = self.store.rows(
            datasets,
            datasets.c.id == request.dataset_id,
            datasets.c.persona_id == request.persona_id,
            datasets.c.relationship_id == request.relationship_id,
        )
        if not rows:
            raise DomainError("DATASET_NOT_FOUND", "No frozen dataset exists in this scope", 404)
        if rows[0]["payload"].get("status") == "revoked":
            raise DomainError("DATASET_REVOKED", "Training source was revoked", 409)
        dataset_path = self.store.root / "datasets" / request.dataset_id
        if dataset_path.is_symlink():
            raise DomainError("DATASET_PATH_INVALID", "Dataset links are not accepted", 422)
        spec = prepare_spec(dataset_path, output)
        changes = request.model_dump(
            exclude={"dataset_id", "persona_id", "relationship_id", "allow_model_download"}
        )
        changes["local_files_only"] = not request.allow_model_download
        return TrainingSpec.model_validate(spec.model_dump() | changes)

    def submit(self, request: TrainingJobRequest) -> JobView:
        with self.data_lock:
            job_id = str(uuid4())
            spec = self.spec_for_request(request, self.root / job_id / "artifact")
            return self.submit_spec(spec, job_id=job_id)

    def submit_spec(self, spec: TrainingSpec, *, job_id: str | None = None) -> JobView:
        """Internal integration hook; destinations are always reassigned by the manager."""
        with self.data_lock:
            return self._submit_spec_locked(spec, job_id=job_id)

    def _submit_spec_locked(self, spec: TrainingSpec, *, job_id: str | None = None) -> JobView:
        if not self.started or self.closing:
            raise DomainError("JOB_WORKER_OFFLINE", "Training worker is not running", 503)
        if len([row for row in self.store.rows(jobs) if row["status"] not in TERMINAL]) >= 20:
            raise DomainError("JOB_QUEUE_FULL", "Finish or cancel queued jobs first", 429)
        expected_path = (self.store.root / "datasets" / spec.dataset_version).resolve()
        if spec.dataset_path.resolve() != expected_path:
            raise DomainError(
                "DATASET_PATH_INVALID", "Jobs only read this instance's frozen datasets", 422
            )
        registered = self.store.rows(
            datasets,
            datasets.c.id == spec.dataset_version,
            datasets.c.persona_id == spec.persona_id,
            datasets.c.relationship_id == spec.relationship_id,
        )
        if not registered or registered[0]["payload"].get("status") == "revoked":
            raise DomainError("DATASET_REVOKED", "Training source was revoked or removed", 409)
        manifest = validate_dataset(spec)
        if not registered or registered[0]["payload"] != manifest:
            raise DomainError(
                "DATASET_MISMATCH", "Dataset manifest differs from the registered snapshot", 422
            )
        job_id = job_id or str(uuid4())
        # Only caller-generated UUIDs can determine a directory; never a request path.
        from uuid import UUID

        if str(UUID(job_id)) != job_id:
            raise ValueError("job id must be a canonical UUID")
        work = self.root / job_id
        work.mkdir(mode=0o700)
        managed = TrainingSpec.model_validate(
            spec.model_dump()
            | {"output_path": work / "artifact", "cancel_path": work / "cancel.requested"}
        )
        write_json(work / "spec.json", managed.model_dump(mode="json"))
        created = timestamp()
        payload = {
            "persona_id": managed.persona_id,
            "relationship_id": managed.relationship_id,
            "dataset_id": managed.dataset_version,
            "created_at": created,
            "updated_at": created,
            "phase": "queued",
            "step": 0,
            "progress": 0,
            "cancel_requested": False,
            "output_path": str(managed.output_path),
            "max_steps": managed.max_steps,
            "events": [{"at": created, "event": "queued", "detail": "owner_requested"}],
        }
        with self.store.transaction() as connection:
            self._require_source(connection, managed, manifest)
            connection.execute(
                jobs.insert().values(id=job_id, kind="training", status="queued", payload=payload)
            )
        self._notify()
        return self.detail(job_id)

    def _require_source(self, connection, spec: TrainingSpec, manifest: dict | None = None) -> None:
        registered = (
            connection.execute(
                select(datasets).where(
                    datasets.c.id == spec.dataset_version,
                    datasets.c.persona_id == spec.persona_id,
                    datasets.c.relationship_id == spec.relationship_id,
                )
            )
            .mappings()
            .first()
        )
        if (
            not registered
            or registered["payload"].get("status") == "revoked"
            or registered["payload"].get("dataset_hash") != spec.dataset_hash
            or (manifest is not None and registered["payload"] != manifest)
        ):
            raise DomainError(
                "DATASET_REVOKED", "Training source was removed, changed or revoked", 409
            )

    def _spawn_guarded(self, job_id: str, spec: TrainingSpec) -> subprocess.Popen:
        with self.data_lock:
            # Revoked datasets may already be quarantined/deleted from disk.
            # Preserve the precise invalidation outcome instead of an I/O failure.
            with self.store.engine.connect() as connection:
                self._require_source(connection, spec)
            manifest = validate_dataset(spec)
            with self.store.transaction() as connection:
                self._require_source(connection, spec, manifest)
                row = connection.execute(select(jobs).where(jobs.c.id == job_id)).mappings().one()
                if (
                    self.closing
                    or row["payload"].get("cancel_requested")
                    or row["payload"].get("invalidated")
                ):
                    raise DomainError(
                        "JOB_CANCELLED", "Training job was cancelled or invalidated", 409
                    )
                return subprocess.Popen(
                    self._command(job_id),
                    env=worker_environment(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

    def _finish_guarded(self, job_id: str, spec: TrainingSpec, state: dict) -> None:
        with self.data_lock, self.store.transaction() as connection:
            self._require_source(connection, spec)
            row = connection.execute(select(jobs).where(jobs.c.id == job_id)).mappings().one()
            if row["payload"].get("cancel_requested") or row["payload"].get("invalidated"):
                raise DomainError("JOB_CANCELLED", "Training job was cancelled or invalidated", 409)
            payload = dict(row["payload"])
            payload.update(
                status="succeeded",
                phase="complete",
                progress=1,
                step=int(state.get("step", 0)),
                artifact_ready=True,
                heartbeat=timestamp(),
                updated_at=timestamp(),
            )
            payload["events"] = (
                payload.get("events", [])
                + [{"at": timestamp(), "event": "succeeded", "detail": "complete"}]
            )[-100:]
            connection.execute(
                jobs.update().where(jobs.c.id == job_id).values(status="succeeded", payload=payload)
            )

    def cancel(self, job_id: str) -> JobView:
        row = self._row(job_id)
        if row["status"] in TERMINAL:
            return self.detail(job_id)
        (self.root / job_id / "cancel.requested").touch(mode=0o600)
        changes = {"cancel_requested": True, "phase": "cancellation_requested"}
        if row["status"] == "queued":
            changes.update(status="cancelled", progress=0)
        self._update(job_id, event="cancel_requested", **changes)
        self._notify()
        return self.detail(job_id)

    async def _loop(self) -> None:
        while not self.closing:
            queued = [
                row
                for row in self.store.rows(jobs, jobs.c.kind == "training")
                if row["status"] == "queued"
            ]
            if queued:
                queued.sort(key=lambda row: row["payload"]["created_at"])
                await self._execute(queued[0]["id"])
                continue
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=1)
            except TimeoutError:
                pass

    def _command(self, job_id: str) -> Sequence[str]:
        work = self.root / job_id
        return [
            str(self.python),
            "-m",
            "chattwin.jobs.runner",
            "--spec",
            str(work / "spec.json"),
            "--lease",
            str(self.execution_lease),
            "--result",
            str(work / "manager-result.json"),
        ]

    async def _stop_child(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            await asyncio.to_thread(process.wait, 5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await asyncio.to_thread(process.wait)

    async def _execute(self, job_id: str) -> None:
        if self._row(job_id)["status"] != "queued":
            return
        self.active_id = job_id
        self._update(
            job_id,
            status="validating",
            phase="environment_preflight",
            heartbeat=timestamp(),
            event="validating",
        )
        try:
            spec = TrainingSpec.model_validate_json((self.root / job_id / "spec.json").read_text())
            environment = await asyncio.to_thread(inspect_environment, self.python)
            row = self._row(job_id)
            if self.closing or row["payload"].get("cancel_requested"):
                state = "cancelled" if row["payload"].get("cancel_requested") else "interrupted"
                self._update(job_id, status=state, phase=state, event=state)
                return
            blocker = None
            if not environment.dependencies_available:
                blocker = "TRAINING_ENVIRONMENT_MISSING"
            elif not spec.synthetic_smoke and not environment.supports_reference_training:
                blocker = (
                    "CUDA_UNAVAILABLE"
                    if not environment.cuda_available
                    else "REFERENCE_HOST_UNVERIFIED"
                )
            elif spec.precision == "bfloat16" and not environment.cuda_bf16_supported:
                blocker = "BF16_UNAVAILABLE"
            if blocker:
                self._update(
                    job_id,
                    status="failed",
                    phase="preflight_failed",
                    error_code=blocker,
                    error_summary="训练环境未满足要求；未下载模型、未开始训练。",
                    event="failed",
                )
                return
            self.process = await asyncio.to_thread(self._spawn_guarded, job_id, spec)
            self._update(
                job_id, status="running", phase="training", heartbeat=timestamp(), event="running"
            )
            last_step = -1
            while self.process.poll() is None:
                row = self._row(job_id)
                if self.closing or row["payload"].get("cancel_requested"):
                    await self._stop_child()
                    break
                status_path = spec.output_path / "status.json"
                if status_path.exists():
                    try:
                        status = json.loads(status_path.read_text())
                        step = max(0, min(int(status.get("step", 0)), spec.max_steps))
                        loss = status.get("loss")
                        loss = (
                            float(loss)
                            if isinstance(loss, (int, float)) and math.isfinite(loss)
                            else None
                        )
                        self._update(
                            job_id,
                            step=step,
                            loss=loss,
                            heartbeat=timestamp(),
                            progress=min(0.99, step / spec.max_steps),
                            phase="reload" if status.get("phase") == "reload" else "training",
                            event="progress" if step != last_step else None,
                        )
                        last_step = step
                    except (ValueError, OSError):
                        pass
                await asyncio.sleep(self.poll_interval)
            row = self._row(job_id)
            if self.closing or row["payload"].get("cancel_requested"):
                state = "cancelled" if row["payload"].get("cancel_requested") else "interrupted"
                self._update(job_id, status=state, phase=state, heartbeat=timestamp(), event=state)
            elif self.process.returncode == 0:
                await asyncio.to_thread(verify_artifact, spec.output_path)
                state = json.loads((spec.output_path / "status.json").read_text())
                if state.get("status") != "succeeded":
                    raise ValueError("worker exited without verified success")
                await asyncio.to_thread(self._finish_guarded, job_id, spec, state)
            else:
                result_path = self.root / job_id / "manager-result.json"
                code = "TRAINING_FAILED"
                if result_path.exists():
                    data = json.loads(result_path.read_text())
                    if data.get("error_code") == "EXECUTION_LEASE_BUSY":
                        code = "EXECUTION_LEASE_BUSY"
                self._update(
                    job_id,
                    status="failed",
                    phase="failed",
                    error_code=code,
                    error_summary="训练进程未完成；原始错误仅保留于私有目录。",
                    event="failed",
                )
        except DomainError as exc:
            state = "cancelled" if exc.code in {"DATASET_REVOKED", "JOB_CANCELLED"} else "failed"
            self._update(
                job_id,
                status=state,
                phase=state,
                error_code=exc.code,
                error_summary="训练来源或任务状态已失效；未登记可用产物。",
                artifact_ready=False,
                event=state,
            )
        except Exception:
            self._update(
                job_id,
                status="failed",
                phase="failed",
                error_code="JOB_EXECUTION_FAILED",
                error_summary="作业配置、文件校验或进程执行失败。",
                event="failed",
            )
        finally:
            if self.process and self.process.poll() is None:
                await self._stop_child()
            self.process, self.active_id = None, None
