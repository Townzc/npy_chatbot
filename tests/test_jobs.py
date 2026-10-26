import asyncio
import hashlib
import io
import json
import shutil
import subprocess
import sys
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from filelock import FileLock

from chattwin.api.job_routes import job_router
from chattwin.domain import DomainError
from chattwin.importers import DataService
from chattwin.jobs import JobManager, TrainingEnvironment, TrainingJobRequest
from chattwin.jobs.bundle import create_training_bundle
from chattwin.jobs.environment import training_python
from chattwin.storage import Store, datasets
from chattwin.training.spec import TrainingSpec
from chattwin.training.worker import worker_environment


@pytest.fixture
def system(tmp_path):
    store = Store(tmp_path / "private")
    store.migrate()
    service = DataService(store)
    persona = service.create_persona("Synthetic job owner")
    relationship = service.create_relationship(persona["id"], "Synthetic job friend")
    fixture = Path(__file__).resolve().parents[1] / "examples/chatlab_wechat.synthetic.jsonl"
    service.import_file(
        fixture, persona["id"], relationship["id"], "demo_owner", "demo-account", confirm_human=True
    )
    dataset = service.build_dataset(persona["id"], relationship["id"])
    request = TrainingJobRequest(
        dataset_id=dataset["id"],
        persona_id=persona["id"],
        relationship_id=relationship["id"],
        max_steps=2,
    )
    yield store, request
    store.close()


async def terminal(manager, job_id, timeout=15):
    async with asyncio.timeout(timeout):
        while manager.detail(job_id).status not in {
            "succeeded",
            "failed",
            "cancelled",
            "interrupted",
        }:
            await asyncio.sleep(0.03)
    return manager.detail(job_id)


def available_fixture_environment(_python):
    """Process-control fixture only; this does not assert actual CUDA compatibility."""
    return TrainingEnvironment(
        python_available=True,
        dependencies_available=True,
        platform="Linux",
        cuda_available=True,
        cuda_bf16_supported=True,
        supports_reference_training=True,
        tiny_available=True,
        reference_model={},
    )


async def test_unavailable_environment_is_durable_failure_without_model_download(system, tmp_path):
    store, request = system
    manager = JobManager(store, python=tmp_path / "missing-python")
    await manager.startup()
    job = manager.submit(request)
    result = await terminal(manager, job.id)
    assert result.status == "failed"
    assert result.error_code == "TRAINING_ENVIRONMENT_MISSING"
    assert not (Path(result.output_path) / "adapter").exists()
    spec = TrainingSpec.model_validate_json((manager.root / job.id / "spec.json").read_text())
    assert spec.local_files_only
    await manager.close()
    with pytest.raises(ValueError):
        TrainingJobRequest.model_validate(request.model_dump() | {"output_path": "/elsewhere"})


async def test_queue_cancellation_and_process_stop_are_nonblocking(system, monkeypatch, tmp_path):
    store, request = system
    monkeypatch.setattr("chattwin.jobs.manager.inspect_environment", available_fixture_environment)
    manager = JobManager(store, python=Path(sys.executable), poll_interval=0.02)
    sleeper = tmp_path / "process_fixture.py"
    sleeper.write_text("import time\ntime.sleep(30)\n")
    monkeypatch.setattr(manager, "_command", lambda job_id: [sys.executable, str(sleeper)])
    await manager.startup()
    active = manager.submit(request)
    async with asyncio.timeout(3):
        while manager.detail(active.id).status != "running":
            await asyncio.sleep(0.02)
    queued = manager.submit(request)
    assert manager.cancel(queued.id).status == "cancelled"
    manager.cancel(active.id)
    result = await terminal(manager, active.id, timeout=3)
    assert result.status == "cancelled" and result.cancel_requested
    assert manager.process is None
    await manager.close()


async def test_manager_single_lease_and_restart_never_auto_resumes(system):
    store, request = system
    manager = JobManager(store)
    await manager.startup()
    competing = JobManager(store)
    with pytest.raises(DomainError, match="already has"):
        await competing.startup()
    job = manager.submit(request)
    await manager.close()
    recovered = JobManager(store)
    await recovered.startup()
    assert recovered.detail(job.id).status == "interrupted"
    assert recovered.detail(job.id).error_code == "PROCESS_RESTARTED"
    await recovered.close()


async def test_raw_process_output_is_not_exposed_in_job_logs(system, monkeypatch, tmp_path):
    store, request = system
    monkeypatch.setattr("chattwin.jobs.manager.inspect_environment", available_fixture_environment)
    manager = JobManager(store, python=Path(sys.executable), poll_interval=0.02)
    script = tmp_path / "error_fixture.py"
    script.write_text(
        "import sys\nprint('PRIVATE_CHAT_BODY_AND_SECRET')\nprint('PRIVATE_CHAT_BODY_AND_SECRET',file=sys.stderr)\nraise SystemExit(1)\n"
    )
    monkeypatch.setattr(manager, "_command", lambda job_id: [sys.executable, str(script)])
    await manager.startup()
    job = manager.submit(request)
    result = await terminal(manager, job.id)
    assert result.status == "failed"
    assert "PRIVATE_CHAT" not in result.model_dump_json() + manager.logs(job.id).model_dump_json()
    assert len(manager.logs(job.id).events) <= 100
    await manager.close()


async def test_orphan_execution_lease_prevents_second_child(system, monkeypatch):
    store, request = system
    monkeypatch.setattr("chattwin.jobs.manager.inspect_environment", available_fixture_environment)
    manager = JobManager(store, python=Path(sys.executable), poll_interval=0.02)
    await manager.startup()
    with FileLock(manager.execution_lease):
        job = manager.submit(request)
        result = await terminal(manager, job.id)
        assert result.error_code == "EXECUTION_LEASE_BUSY"
        assert result.status == "failed"
        assert not Path(result.output_path).exists()
    await manager.close()


def test_private_bundle_contains_exact_dataset_and_portable_worker_without_credentials(
    system, tmp_path
):
    from chattwin.runtime_paths import training_code_hash

    store, request = system
    (store.root / "owner-token").write_text("synthetic-super-secret-token")
    manager = JobManager(store)
    archive, manifest = create_training_bundle(manager, request)
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert {
            "dataset/train.jsonl",
            "dataset/validation.jsonl",
            "dataset/test.jsonl",
            "training/uv.lock",
            "src/chattwin/training/worker.py",
            "run_training.py",
        } <= names
        assert not any(
            "owner-token" in name or ".env" in name or "safetensors" in name for name in names
        )
        assert all(".." not in Path(name).parts and not Path(name).is_absolute() for name in names)
        for name, info in manifest["files"].items():
            content = bundle.read(name)
            assert hashlib.sha256(content).hexdigest() == info["sha256"]
            assert b"synthetic-super-secret-token" not in content
        compile(bundle.read("run_training.py"), "run_training.py", "exec")
        bundle.extractall(tmp_path / "exported")
    assert manifest["training_code_version"] == "source:" + training_code_hash()
    extracted = tmp_path / "exported/src/chattwin"
    assert training_code_hash(extracted) == training_code_hash()
    resolver = extracted / "runtime_paths.py"
    resolver.write_text(resolver.read_text() + "\n# synthetic drift regression\n")
    assert training_code_hash(extracted) != training_code_hash()
    assert manifest["credentials_included"] is False
    assert manifest["contains_private_training_data"] is True


def test_router_auth_export_and_scope_contract(system, monkeypatch, tmp_path):
    store, request = system
    manager = JobManager(store, python=tmp_path / "missing-runtime")

    @asynccontextmanager
    async def lifespan(_app):
        await manager.startup()
        yield
        await manager.close()

    async def authenticate(authorization: str | None = Header(default=None)):
        if authorization != "Bearer test-token":
            raise HTTPException(401)

    app = FastAPI(lifespan=lifespan)

    @app.exception_handler(DomainError)
    async def error(_request, exc):
        return JSONResponse({"code": exc.code, "detail": exc.detail}, status_code=exc.status)

    app.include_router(job_router(store, lambda: None, authenticate, manager=manager))
    with TestClient(app) as client:
        assert client.get("/api/v1/jobs").status_code == 401
        headers = {"Authorization": "Bearer test-token"}
        assert (
            client.get("/api/v1/training-environment", headers=headers).json()["python_available"]
            is False
        )
        assert client.get("/api/v1/jobs?persona_id=one", headers=headers).status_code == 422
        wrong = request.model_dump() | {"relationship_id": "wrong-scope"}
        assert client.post("/api/v1/training-jobs", json=wrong, headers=headers).status_code == 404
        response = client.post("/api/v1/training-jobs", json=request.model_dump(), headers=headers)
        assert response.status_code == 202
        exported = client.post(
            "/api/v1/training-bundles", json=request.model_dump(), headers=headers
        )
        assert exported.status_code == 200
        assert "dataset/manifest.json" in zipfile.ZipFile(io.BytesIO(exported.content)).namelist()
        assert not list((store.root / "training-bundles").glob("*.zip"))


@pytest.mark.skipif(
    not training_python().is_file(), reason="optional isolated training runtime not installed"
)
async def test_job_manager_executes_actual_tiny_lora_worker(system, tmp_path):
    store, _ = system
    tiny_root = tmp_path / "tiny-source"
    code = "from pathlib import Path; import sys; from chattwin.training.smoke import create_smoke_spec; create_smoke_spec(Path(sys.argv[1]))"
    subprocess.run(
        [str(training_python()), "-c", code, str(tiny_root)],
        env=worker_environment(),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    spec = TrainingSpec.model_validate_json((tiny_root / "spec.json").read_text())
    # The tiny IDs are synthetic; register their actual manifest as a frozen local dataset.
    from chattwin.storage import personas, relationships

    destination = store.root / "datasets" / spec.dataset_version
    shutil.copytree(spec.dataset_path, destination)
    manifest = json.loads((destination / "manifest.json").read_text())
    with store.transaction() as connection:
        connection.execute(personas.insert().values(id=spec.persona_id, payload={"name": "tiny"}))
        connection.execute(
            relationships.insert().values(
                id=spec.relationship_id, persona_id=spec.persona_id, payload={"name": "tiny"}
            )
        )
        connection.execute(
            datasets.insert().values(
                id=spec.dataset_version,
                persona_id=spec.persona_id,
                relationship_id=spec.relationship_id,
                payload=manifest,
            )
        )
    managed_spec = TrainingSpec.model_validate(spec.model_dump() | {"dataset_path": destination})
    manager = JobManager(store, poll_interval=0.03)
    await manager.startup()
    job = manager.submit_spec(managed_spec)
    result = await terminal(manager, job.id, timeout=30)
    assert result.status == "succeeded", result.model_dump()
    assert result.artifact_ready
    report = json.loads((Path(result.output_path) / "training_report.json").read_text())
    assert report["max_parameter_update"] > 0
    assert report["training_pid"] != report["reload_comparison"]["pid"]
    assert report["evidence"] == "tiny_cpu_smoke"
    await manager.close()
