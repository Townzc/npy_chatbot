"""Synthetic data lifecycle tests; never delete or read a user's private records."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from chattwin.api.data_routes import data_router
from chattwin.channels import FakeChannel
from chattwin.domain import Binding, DomainError, ModeCommand, now, uid
from chattwin.importers import DataService
from chattwin.importers.management import recover_data_operations
from chattwin.importers.parsers import file_hash
from chattwin.outbox import Coordinator
from chattwin.storage import (
    Store,
    artifacts,
    audit,
    datasets,
    imports,
    jobs,
    memories,
    messages,
    model_deployments,
    sessions,
    styles,
)

FIXTURE = Path(__file__).parents[1] / "examples" / "chatlab_wechat.synthetic.jsonl"


@pytest.fixture
def data_system(tmp_path):
    store = Store(tmp_path / "private")
    store.migrate()
    service = DataService(store)
    persona = service.create_persona("虚构数据生命周期")
    relation = service.create_relationship(persona["id"], "虚构数据管理关系")
    report = service.import_file(
        FIXTURE,
        persona["id"],
        relation["id"],
        "demo_owner",
        "synthetic-account",
        confirm_human=True,
    )
    yield store, service, persona["id"], relation["id"], report
    store.close()


def seed_derived(store, service, p, r):
    source = service.list_messages(p, r)
    owner = next(item for item in source if item["use_context"]["sender_role"] == "owner")
    style = service.save_style(p, r, "简短温和", [owner["id"]], confirmed=True, expected_version=0)
    memory = service.add_memory(p, r, "虚构偏好：喜欢安静展览", [source[0]["id"]], confirmed=True)
    dataset = service.build_dataset(p, r)
    artifact_id, deployment_id, job_id = uid(), uid(), uid()
    with store.transaction() as conn:
        conn.execute(
            artifacts.insert().values(
                id=artifact_id,
                persona_id=p,
                relationship_id=r,
                payload={
                    "id": artifact_id,
                    "status": "validated",
                    "manifest": {"dataset_version": dataset["id"]},
                },
            )
        )
        conn.execute(
            model_deployments.insert().values(
                id=deployment_id,
                persona_id=p,
                relationship_id=r,
                artifact_id=artifact_id,
                status="active",
                payload={
                    "id": deployment_id,
                    "status": "active",
                    "artifact_id": artifact_id,
                    "endpoint": "http://127.0.0.1:9",
                },
            )
        )
        conn.execute(
            jobs.insert().values(
                id=job_id,
                kind="training",
                status="running",
                payload={"spec": {"dataset_version": dataset["id"]}},
            )
        )
    return style, memory, dataset, artifact_id, deployment_id, job_id


def test_style_approval_is_distinct_versioned_and_scoped(data_system):
    store, service, p, r, _ = data_system
    draft = service.build_style(p, r)
    assert draft["status"] == "draft" and store.rows(styles) == []
    selected = draft["examples"][0]["message_id"]
    approved = service.save_style(p, r, "短句，不替本人做承诺", [selected], confirmed=True)
    assert service.get_approved_style(p, r)["id"] == approved["id"]
    saved_draft = service.save_style(p, r, "待确认修改", [], expected_version=1)
    assert saved_draft["status"] == "draft"
    assert service.get_approved_style(p, r)["id"] == approved["id"]
    with pytest.raises(DomainError, match="refresh"):
        service.save_style(p, r, "stale", [], expected_version=1)
    second = service.save_style(p, r, "已确认修改", [], confirmed=True, expected_version=2)
    assert second["version"] == 3
    assert service.get_approved_style(p, r)["id"] == second["id"]
    other = service.create_relationship(p, "其他虚构关系")
    with pytest.raises(DomainError, match="Examples"):
        service.save_style(p, other["id"], "错误范围", [selected])
    assert service.style_state(p, r)["version"] == 3


def test_memory_correction_expiry_and_optimistic_version(data_system):
    _, service, p, r, _ = data_system
    source = service.list_messages(p, r)[0]
    memory = service.add_memory(p, r, "初稿", [source["id"]], confirmed=True)
    changed = service.update_memory(memory["id"], p, r, text="修正内容", expected_version=1)
    assert not changed["confirmed"] and changed["history"][0]["text"] == "初稿"
    with pytest.raises(DomainError, match="refresh"):
        service.update_memory(memory["id"], p, r, confirmed=True, expected_version=1)
    service.update_memory(
        memory["id"],
        p,
        r,
        confirmed=True,
        expected_version=2,
        expires_at=now() - timedelta(seconds=1),
    )
    assert service.retrieve_memories(p, r, "修正") == []
    service.update_memory(memory["id"], p, r, expires_at=None, expected_version=3)
    assert service.retrieve_memories(p, r, "修正")[0]["text"] == "修正内容"


def test_canonical_sidecar_hash_count_scope_and_kind(data_system, tmp_path):
    _, service, p, r, _ = data_system
    path = tmp_path / "synthetic-export.jsonl"
    manifest = service.export_canonical(p, r, path)
    report = service.inspect(path)
    assert report["manifest_validation"]["hash_verified"]
    assert report["manifest_validation"]["count"] == 4
    assert (
        service.import_file(path, p, r, "demo_owner", "synthetic-account", confirm_human=True)[
            "duplicates"
        ]
        == 4
    )
    sidecar = path.with_suffix(".jsonl.manifest.json")
    invalid = {**manifest, "count": 999}
    sidecar.write_text(json.dumps(invalid))
    with pytest.raises(DomainError, match="count"):
        service.inspect(path)
    sidecar.write_text(json.dumps({**manifest, "file_sha256": "0" * 64}))
    with pytest.raises(DomainError, match="hash"):
        service.inspect(path)
    sidecar.write_text(json.dumps(manifest))
    other = service.create_relationship(p, "不相同的范围")
    with pytest.raises(DomainError, match="scope"):
        service.import_file(path, p, other["id"], "demo_owner", "synthetic-account")
    manifest["conversations"][0]["kind"] = "group"
    sidecar.write_text(json.dumps(manifest))
    with pytest.raises(DomainError, match="kind"):
        service.inspect(path)
    assert file_hash(path) == manifest["file_sha256"]


def test_source_delete_revokes_all_derivatives_and_removes_training_files(data_system):
    store, service, p, r, report = data_system
    style, memory, dataset, artifact_id, deployment_id, job_id = seed_derived(store, service, p, r)
    impact = service.deletion_impact(report["id"], p, r)
    assert impact["counts"]["raw_messages_removed"] == 4
    assert impact["revoked_dataset_ids"] == [dataset["id"]]
    assert impact["cancel_job_ids"] == [job_id]
    deleted = service.delete_import(report["id"], p, r, impact["impact_hash"])
    assert deleted["weights_forgotten"] is False
    assert store.rows(messages) == [] and store.rows(imports) == []
    assert not Path(dataset["path"]).exists()
    assert store.rows(styles)[0]["payload"]["status"] == "revoked"
    assert store.rows(styles)[0]["payload"]["examples"] == []
    revoked_memory = store.rows(memories)[0]["payload"]
    assert revoked_memory["text"] == "" and revoked_memory["history"] == []
    assert service.get_approved_style(p, r) is None
    assert store.rows(datasets)[0]["payload"]["status"] == "revoked"
    assert store.rows(artifacts)[0]["payload"]["weights_forgotten"] is False
    assert store.rows(model_deployments)[0]["status"] == "revoked"
    assert store.rows(model_deployments)[0]["payload"]["endpoint"] == "http://127.0.0.1:9"
    with pytest.raises(DomainError, match="revoked"):
        service.update_memory(memory["id"], p, r, confirmed=True)


def seed_evaluation(store, p, r, source_ids):
    id = uid()
    directory = store.root / "evaluations" / id
    directory.mkdir(parents=True)
    manifest = {
        "id": id,
        "persona_id": p,
        "relationship_id": r,
        "source_message_ids": source_ids,
        "status": "completed",
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "cases.json").write_text('[{"context":"synthetic only"}]')
    (directory / "prompts.json").write_text('[{"text":"synthetic only"}]')
    return id, directory


def test_source_deletion_removes_dependent_evaluation_copies_only(data_system):
    store, service, p, r, report = data_system
    source = service.list_messages(p, r)[0]["id"]
    dependent_id, dependent = seed_evaluation(store, p, r, [source])
    _, independent = seed_evaluation(store, p, r, [])
    other = service.create_relationship(p, "其他虚构评测关系")
    _, other_scope = seed_evaluation(store, p, other["id"], [source])
    impact = service.deletion_impact(report["id"], p, r)
    assert impact["revoked_evaluation_ids"] == [dependent_id]
    assert impact["counts"]["evaluations"] == 1
    result = service.delete_import(report["id"], p, r, impact["impact_hash"])
    assert result["revoked_evaluation_ids"] == [dependent_id]
    assert not dependent.exists()
    assert independent.exists() and other_scope.exists()


def test_evaluation_lineage_changes_invalidate_preview_and_rollback_restores(
    data_system, monkeypatch
):
    from chattwin.importers import management

    store, service, p, r, report = data_system
    preview = service.deletion_impact(report["id"], p, r)
    _, evaluation = seed_evaluation(store, p, r, [service.list_messages(p, r)[0]["id"]])
    with pytest.raises(DomainError, match="preview again"):
        service.delete_import(report["id"], p, r, preview["impact_hash"])
    current = service.deletion_impact(report["id"], p, r)

    def fail(*args, **kwargs):
        assert not evaluation.exists(), "evaluation must be quarantined before DB mutation"
        raise RuntimeError("injected evaluation rollback")

    monkeypatch.setattr(management, "revoke_derived", fail)
    with pytest.raises(RuntimeError, match="injected"):
        service.delete_import(report["id"], p, r, current["impact_hash"])
    assert (evaluation / "cases.json").is_file()
    assert (evaluation / "prompts.json").is_file()
    assert len(service.list_messages(p, r)) == 4


def test_shared_raw_source_retains_other_persona_reference(data_system):
    store, service, p, r, first = data_system
    other = service.create_persona("第二个虚构档案")
    other_r = service.create_relationship(other["id"], "第二个虚构关系")
    second = service.import_file(
        FIXTURE, other["id"], other_r["id"], "demo_owner", "synthetic-account", confirm_human=True
    )
    assert second["duplicates"] == 4
    first_dataset = service.build_dataset(p, r)
    second_dataset = service.build_dataset(other["id"], other_r["id"])
    impact = service.deletion_impact(first["id"], p, r)
    assert impact["counts"]["raw_messages_retained_by_other_imports"] == 4
    service.delete_import(first["id"], p, r, impact["impact_hash"])
    assert service.list_messages(p, r) == []
    assert len(service.list_messages(other["id"], other_r["id"])) == 4
    assert len(store.rows(messages)) == 4
    assert all(row["batch_id"] == second["id"] for row in store.rows(messages))
    assert not Path(first_dataset["path"]).exists()
    assert Path(second_dataset["path"]).exists()


def test_stale_deletion_preview_and_db_failure_restore_dataset_files(data_system, monkeypatch):
    from chattwin.importers import management

    store, service, p, r, report = data_system
    dataset = service.build_dataset(p, r)
    stale = service.deletion_impact(report["id"], p, r)
    service.add_memory(p, r, "后来确认的虚构事实", [service.list_messages(p, r)[0]["id"]])
    with pytest.raises(DomainError, match="preview again"):
        service.delete_import(report["id"], p, r, stale["impact_hash"])
    current = service.deletion_impact(report["id"], p, r)
    original = management.revoke_derived

    def fail_after_revoke(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected DB transaction failure")

    monkeypatch.setattr(management, "revoke_derived", fail_after_revoke)
    with pytest.raises(RuntimeError, match="injected"):
        service.delete_import(report["id"], p, r, current["impact_hash"])
    assert Path(dataset["path"]).is_dir()
    assert len(store.rows(messages)) == 4
    assert store.rows(datasets)[0]["payload"].get("status") != "revoked"
    assert not list((store.root / "maintenance" / "data-operations").glob("*.json"))


def test_identity_remap_keeps_raw_senders_and_revokes_old_labels(data_system):
    store, service, p, r, _ = data_system
    _, _, dataset, _, _, _ = seed_derived(store, service, p, r)
    raw_senders = {row["id"]: row["payload"]["sender_id"] for row in store.rows(messages)}
    identities = service.identities(p)
    assert len(identities["participants"]) == 2
    result = service.remap_identity(
        p, "synthetic-account", "demo_partner", confirm_human=True, expected_mapping_version=1
    )
    assert result["mapping_version"] == 2
    assert not Path(dataset["path"]).exists()
    for message in service.list_messages(p, r):
        assert message["sender_id"] == raw_senders[message["id"]]
        assert message["use_context"]["identity_mapping_version"] == 2
        assert message["use_context"]["use_policy"]["training_target"] == (
            message["sender_id"] == "demo_partner"
        )
    with pytest.raises(DomainError, match="refresh"):
        service.remap_identity(p, "synthetic-account", "demo_owner", expected_mapping_version=1)


def test_import_cannot_create_conflicting_owner_mapping(data_system, tmp_path):
    _, service, p, r, _ = data_system
    path = tmp_path / "new-synthetic-messages.jsonl"
    path.write_text(FIXTURE.read_text().replace("synthetic-wx-", "new-synthetic-wx-"))
    with pytest.raises(DomainError, match="explicit identity remapping"):
        service.import_file(path, p, r, "demo_partner", "synthetic-account", confirm_human=True)
    assert len(service.list_messages(p, r)) == 4


def test_import_mapping_snapshot_serializes_with_identity_remap(data_system, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from filelock import FileLock, Timeout

    store, service, p, r, _ = data_system
    entered, release = threading.Event(), threading.Event()
    original_persona = service._persona

    def read_then_wait(*args):
        persona = original_persona(*args)
        entered.set()
        assert release.wait(3)
        return persona

    monkeypatch.setattr(service, "_persona", read_then_wait)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            importing = pool.submit(
                service.import_file, FIXTURE, p, r, "demo_owner", "synthetic-account"
            )
            assert entered.wait(3)
            with pytest.raises(Timeout):
                FileLock(store.root / "data-management.lock", timeout=0).acquire()
            remapping = pool.submit(
                service.remap_identity, p, "synthetic-account", "demo_partner", True, 1
            )
            release.set()
            importing.result(timeout=3)
            assert remapping.result(timeout=3)["mapping_version"] == 2
        assert all(
            row["use_context"]["identity_mapping_version"] == 2
            and (row["use_context"]["sender_role"] == "owner")
            == (row["sender_id"] == "demo_partner")
            for row in service.list_messages(p, r)
        )
    finally:
        release.set()


async def test_preloaded_evaluation_cannot_recreate_deleted_source_copy(
    data_system, tmp_path, monkeypatch
):
    from datetime import UTC, datetime

    from chattwin.evaluation.cases import frozen_test_cases
    from chattwin.evaluation.contracts import EvaluationSpec, ModelPin
    from chattwin.evaluation.runner import EvaluationRunner

    store, service, _, _, _ = data_system
    p = service.create_persona("虚构删除评测来源")["id"]
    r = service.create_relationship(p, "虚构评测关系")["id"]
    lines = ["conversation,sender_id,occurred_at,text,message_id"]
    questions = ["吃饭", "天气", "爬山", "咖啡", "旅行", "电影", "音乐", "跑步", "小说", "比赛"]
    answers = ["吃面条", "晴朗", "去高山", "拿铁", "海边", "喜剧", "爵士", "五公里", "科幻", "篮球"]
    for i, (question, answer) in enumerate(zip(questions, answers, strict=True)):
        time = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i)
        lines.extend(
            [
                f"conv,friend,{time.isoformat()},{question},q{i}",
                f"conv,owner,{(time + timedelta(seconds=30)).isoformat()},{answer},a{i}",
            ]
        )
    path = tmp_path / "evaluation-synthetic.csv"
    path.write_text("\n".join(lines))
    batch = service.import_file(
        path,
        p,
        r,
        "owner",
        "synthetic-evaluation",
        confirm_human=True,
        mapping={"conversation_kind": "private"},
    )
    dataset = service.build_dataset(p, r)
    cases = frozen_test_cases(service, dataset["id"], p, r)
    assert cases and cases[0].reference
    impact = service.deletion_impact(batch["id"], p, r)
    service.delete_import(batch["id"], p, r, impact["impact_hash"])
    spec = EvaluationSpec(
        persona_id=p,
        relationship_id=r,
        base_deployment_id="unused-no-network",
        adapter_deployment_id="unused-no-network",
        base_pin=ModelPin(
            base_model_id="synthetic-fixture-only",
            base_model_revision="a" * 40,
            tokenizer_revision="a" * 40,
            chat_template_hash="b" * 64,
        ),
    )
    runner = EvaluationRunner(store, service, None)
    # Isolate source validation; no real/model protocol evidence is claimed here.
    monkeypatch.setattr(runner, "_model_records", lambda spec: {})
    with pytest.raises(DomainError, match="revoked"):
        await runner.run(spec, cases)
    assert not list((store.root / "evaluations").glob("*/*"))


def test_crash_recovery_uses_database_decision(data_system):
    store, _, _, _, _ = data_system
    for committed in (False, True):
        op = uid()
        original = store.root / "datasets" / "synthetic-recovery"
        quarantine = store.root / "quarantine" / op / "synthetic-recovery"
        quarantine.mkdir(parents=True)
        (quarantine / "train.jsonl").write_text("synthetic recovery fixture")
        directory = store.root / "maintenance" / "data-operations"
        directory.mkdir(parents=True, exist_ok=True)
        journal = directory / f"{op}.json"
        journal.write_text(
            json.dumps(
                {
                    "id": op,
                    "moves": [
                        {
                            "original": str(original.relative_to(store.root)),
                            "quarantined": str(quarantine.relative_to(store.root)),
                        }
                    ],
                }
            )
        )
        if committed:
            with store.transaction() as conn:
                conn.execute(audit.insert().values(id=op, kind="data_revocation", payload={}))
        result = recover_data_operations(store)
        assert result == [{"id": op, "committed": committed}]
        assert not quarantine.exists()
        if not committed:
            assert original.is_dir()
            (original / "train.jsonl").unlink()
            original.rmdir()
        else:
            assert not original.exists()


def test_data_router_owner_auth_mutations_and_sample_preview(data_system):
    store, service, p, r, report = data_system
    coordinator = Coordinator(store, FakeChannel())
    coordinator.create_binding(
        Binding(
            id="data-binding",
            persona_id=p,
            relationship_id=r,
            channel_account_id=coordinator.channel.account_id,
            conversation_id="data-conversation",
            recipient_id="synthetic-peer",
        )
    )
    app = FastAPI()

    async def authenticate(authorization: str | None = Header(None)):
        if authorization != "Bearer synthetic-test":
            raise DomainError("UNAUTHENTICATED", "test only", 401)

    @app.exception_handler(DomainError)
    async def failure(request, exc):
        return JSONResponse({"code": exc.code, "detail": exc.detail}, status_code=exc.status)

    called = []

    async def callback(result):
        called.append(result["revoked_dataset_ids"])

    coordinator.on_sources_revoked = callback
    app.include_router(data_router(store, lambda: coordinator, authenticate))
    scope = {"persona_id": p, "relationship_id": r}
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/styles", params=scope).status_code == 401
            client.headers["Authorization"] = "Bearer synthetic-test"
            state = client.get("/api/v1/styles", params=scope).json()
            saved = client.put(
                "/api/v1/styles",
                json={
                    **scope,
                    "rules": "虚构温和语气",
                    "example_message_ids": [],
                    "confirmed": True,
                    "expected_version": state["version"],
                },
            )
            assert saved.status_code == 200 and saved.json()["status"] == "approved"
            dataset = service.build_dataset(p, r)
            preview = client.get(f"/api/v1/datasets/{dataset['id']}/preview", params=scope)
            assert preview.status_code == 200 and preview.json()["examples"]["train"]
            assert client.get("/api/v1/identities", params={"persona_id": p}).json()["participants"]
            impact = client.get(
                f"/api/v1/imports/{report['id']}/deletion-impact", params=scope
            ).json()
            deleted = client.request(
                "DELETE",
                f"/api/v1/imports/{report['id']}",
                params=scope,
                json={"impact_hash": impact["impact_hash"]},
            )
            assert deleted.status_code == 200, deleted.text
            assert called == [[dataset["id"]]]
            assert (
                client.get(f"/api/v1/datasets/{dataset['id']}/preview", params=scope).status_code
                == 409
            )
            assert store.rows(sessions)[0]["mode"] == "HUMAN"
    finally:
        coordinator.process_lock.release()


async def test_new_binding_inherits_nested_scope_update_barrier(data_system):
    import asyncio

    store, _, p, r, _ = data_system
    coordinator = Coordinator(store, FakeChannel())
    try:
        async with coordinator.scope_update(p, r):
            async with coordinator.scope_update(p, r):
                binding = Binding(
                    id="new-during-update",
                    persona_id=p,
                    relationship_id=r,
                    channel_account_id=coordinator.channel.account_id,
                    conversation_id="new-conversation",
                    recipient_id="synthetic-peer",
                )
                # Match FastAPI's sync handler thread, not just same-loop registration.
                await asyncio.to_thread(coordinator.create_binding, binding)
                assert coordinator.status(binding.id)["payload"]["scope_updates"] == 2
                with pytest.raises(DomainError, match="being updated"):
                    await coordinator.command(
                        binding.id,
                        ModeCommand(
                            command_id="too-early", action="enable", expected_control_epoch=0
                        ),
                    )
            assert coordinator.status(binding.id)["payload"]["scope_updates"] == 1
            with pytest.raises(DomainError, match="being updated"):
                await coordinator.command(
                    binding.id,
                    ModeCommand(
                        command_id="still-early", action="enable", expected_control_epoch=0
                    ),
                )
        assert coordinator.status(binding.id)["payload"]["scope_updates"] == 0
        await coordinator.command(
            binding.id,
            ModeCommand(command_id="after-complete", action="enable", expected_control_epoch=0),
        )
        await coordinator.settle()
        assert coordinator.status(binding.id)["mode"] == "AI_ACTIVE"
    finally:
        await coordinator.close()


def test_training_registration_and_source_delete_are_serialized(data_system, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from filelock import FileLock, Timeout

    from chattwin.jobs import JobManager
    from chattwin.jobs import manager as manager_module
    from chattwin.training.spec import prepare_spec

    store, service, p, r, batch = data_system
    dataset = service.build_dataset(p, r)
    manager = JobManager(store)
    manager.started = True  # exercise registration only: no worker or training is started
    manager.root.mkdir()
    spec = prepare_spec(Path(dataset["path"]), store.root / "not-started")
    impact = service.deletion_impact(batch["id"], p, r)
    entered, release, deleting = threading.Event(), threading.Event(), threading.Event()
    validate = manager_module.validate_dataset

    def controlled_validation(candidate):
        manifest = validate(candidate)
        entered.set()
        assert release.wait(3)
        return manifest

    def deletion():
        deleting.set()
        return service.delete_import(batch["id"], p, r, impact["impact_hash"])

    monkeypatch.setattr(manager_module, "validate_dataset", controlled_validation)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            submission = executor.submit(manager.submit_spec, spec)
            assert entered.wait(3)
            # If this succeeds, source removal can interleave after validation.
            with pytest.raises(Timeout):
                FileLock(store.root / "data-management.lock", timeout=0).acquire()
            removal = executor.submit(deletion)
            assert deleting.wait(3)
            release.set()
            job = submission.result(timeout=3)
            with pytest.raises(DomainError, match="preview again"):
                removal.result(timeout=3)
        assert manager.detail(job.id).status == "queued"
        assert Path(dataset["path"]).is_dir()
        assert len(store.rows(imports)) == 1
    finally:
        release.set()
        manager.started = False


def test_prepared_training_spec_cannot_register_after_source_revocation(data_system):
    from chattwin.jobs import JobManager
    from chattwin.training.spec import prepare_spec

    store, service, p, r, batch = data_system
    dataset = service.build_dataset(p, r)
    spec = prepare_spec(Path(dataset["path"]), store.root / "not-started")
    impact = service.deletion_impact(batch["id"], p, r)
    service.delete_import(batch["id"], p, r, impact["impact_hash"])
    manager = JobManager(store)
    manager.started = True
    manager.root.mkdir()
    try:
        with pytest.raises((DomainError, OSError, ValueError)):
            manager.submit_spec(spec)
        assert store.rows(jobs) == []
    finally:
        manager.started = False


@pytest.mark.parametrize("operation_name", ["memory", "style", "dataset"])
def test_source_dependent_creation_cannot_race_deletion(data_system, monkeypatch, operation_name):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from filelock import FileLock, Timeout

    store, service, p, r, batch = data_system
    original_list = service.list_messages
    source = original_list(p, r)
    owner_id = next(item["id"] for item in source if item["use_context"]["sender_role"] == "owner")
    entered, release = threading.Event(), threading.Event()
    impact = service.deletion_impact(batch["id"], p, r)

    def controlled_list(*args, **kwargs):
        result = original_list(*args, **kwargs)
        entered.set()
        assert release.wait(3)
        return result

    operations = {
        "memory": lambda: service.add_memory(
            p, r, "虚构并发来源", [source[0]["id"]], confirmed=True
        ),
        "style": lambda: service.save_style(p, r, "虚构并发风格", [owner_id], confirmed=True),
        "dataset": lambda: service.build_dataset(p, r),
    }
    monkeypatch.setattr(service, "list_messages", controlled_list)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            creation = executor.submit(operations[operation_name])
            assert entered.wait(3)
            with pytest.raises(Timeout):
                FileLock(store.root / "data-management.lock", timeout=0).acquire()
            deletion = executor.submit(
                service.delete_import, batch["id"], p, r, impact["impact_hash"]
            )
            release.set()
            creation.result(timeout=3)
            with pytest.raises(DomainError, match="preview again"):
                deletion.result(timeout=3)
        assert len(store.rows(messages)) == 4
    finally:
        release.set()
