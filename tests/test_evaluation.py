"""Synthetic local HTTP protocol evidence, never model quality acceptance."""

import csv
import json
import shutil
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from chattwin.domain import DomainError
from chattwin.evaluation import (
    EvaluationCase,
    EvaluationRunner,
    EvaluationSpec,
    ModelPin,
    export_blind_sheet,
    frozen_test_cases,
    read_cases,
    summarize_scores,
)
from chattwin.evaluation.prompts import prepare_prompts
from chattwin.importers import DataService
from chattwin.jobs.environment import training_python
from chattwin.models import MockProvider
from chattwin.models.registry import ArtifactRegistration, DeploymentInput, ModelRegistry
from chattwin.storage import Store, datasets, memories, personas, relationships
from chattwin.training.spec import QWEN_REVISION, QWEN_TEMPLATE_HASH, TrainingSpec
from chattwin.training.worker import worker_environment

PIN = ModelPin(
    base_model_id="Qwen/Qwen3-4B-Instruct-2507",
    base_model_revision=QWEN_REVISION,
    tokenizer_revision=QWEN_REVISION,
    chat_template_hash=QWEN_TEMPLATE_HASH,
)


@pytest.fixture
def http_endpoint(monkeypatch):
    # Real socket transport catches invalid empty Bearer headers missed by mocks.
    monkeypatch.delenv("CHATTWIN_MODEL_KEY", raising=False)
    state = {"calls": [], "health": PIN.model_dump(), "adapter_health": {}, "fail": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.respond(
                200,
                state["adapter_health"] if self.path.startswith("/adapter") else state["health"],
            )

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["calls"].append(body)
            if state["fail"]:
                self.respond(503, {"error": "PRIVATE_PROVIDER_BODY_NEVER_LOG"})
                return
            self.respond(
                200,
                {
                    "choices": [{"message": {"content": "=SYNTHETIC_PROTOCOL_REPLY()"}}],
                    "usage": {"prompt_tokens": 17, "completion_tokens": 5},
                },
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", state
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


@pytest.fixture
def system(tmp_path):
    store = Store(tmp_path / "private")
    store.migrate()
    data = DataService(store)
    p = data.create_persona("虚构评测本人")["id"]
    r = data.create_relationship(p, "虚构评测关系")["id"]
    fixture = Path(__file__).parents[1] / "examples/chatlab_wechat.synthetic.jsonl"
    data.import_file(fixture, p, r, "demo_owner", "synthetic-evaluation", confirm_human=True)
    owner = next(m for m in data.list_messages(p, r) if m["use_context"]["sender_role"] == "owner")
    data.save_style(p, r, "STYLE_CANARY 简短温和", [owner["id"]], confirmed=True)
    source = data.list_messages(p, r)[0]["id"]
    data.add_memory(p, r, "MEMORY_CANARY 只在此虚构关系喜欢安静展览", [source], confirmed=True)
    future = data.add_memory(p, r, "FUTURE_CANARY 展览", [source], confirmed=True)
    with store.transaction() as conn:
        conn.execute(
            memories.update()
            .where(memories.c.id == future["id"])
            .values(payload={**future, "updated_at": "2028-01-01T00:00:00+00:00"})
        )
    other = data.create_relationship(p, "隔离关系")["id"]
    # The public API correctly disallows reusing sources in another relationship.
    with store.transaction() as conn:
        conn.execute(
            memories.insert().values(
                id="foreign",
                persona_id=p,
                relationship_id=other,
                payload={
                    **future,
                    "id": "foreign",
                    "relationship_id": other,
                    "text": "FOREIGN_CANARY 展览",
                },
            )
        )
    registry = ModelRegistry(store, MockProvider(), lambda: None)
    yield store, data, registry, p, r
    store.close()


def scenario(**changes):
    return EvaluationCase(
        id="synthetic-case",
        category="facts",
        messages=[{"role": "user", "content": "【虚构场景】我们喜欢什么展览？"}],
        reference="GOLD_NEVER_PROMPT",
        rubric="只使用本关系已确认的来源。",
        source_cutoff="2027-01-01T00:00:00Z",
        synthetic=True,
        **changes,
    )


async def deployment(registry, p, r, endpoint, artifact_id=None):
    dep = registry.create(
        DeploymentInput(
            persona_id=p,
            relationship_id=r,
            endpoint=endpoint,
            model="synthetic-adapter" if artifact_id else "synthetic-base",
            label="Synthetic protocol",
            artifact_id=artifact_id,
        )
    )
    await registry.test(dep.id)
    return dep.id


async def protocol_run(system, http_endpoint, variants=None):
    store, data, registry, p, r = system
    endpoint, _state = http_endpoint
    base = await deployment(registry, p, r, endpoint)
    spec = EvaluationSpec(
        persona_id=p,
        relationship_id=r,
        base_deployment_id=base,
        base_pin=PIN,
        variants=variants or ["B0", "B1", "B2"],
        mode="synthetic-protocol",
    )
    result = await EvaluationRunner(store, data, registry).run(spec, [scenario()])
    return Path(result["output_path"]), spec, result


async def test_actual_loopback_http_context_variants_and_private_evidence(system, http_endpoint):
    path, _spec, outcome = await protocol_run(system, http_endpoint)
    calls = http_endpoint[1]["calls"][-3:]
    assert "STYLE_CANARY" not in json.dumps(calls[0])
    assert "STYLE_CANARY" in json.dumps(calls[1])
    assert "MEMORY_CANARY" not in json.dumps(calls[1])
    assert "MEMORY_CANARY" in json.dumps(calls[2])
    for call in calls:
        assert call["temperature"] == 0
        assert all(
            sentinel not in json.dumps(call)
            for sentinel in ("GOLD_NEVER_PROMPT", "FUTURE_CANARY", "FOREIGN_CANARY")
        )
        assert call["messages"][-1] == calls[0]["messages"][-1]
    results = json.loads((path / "results.json").read_text())
    assert all(
        row["input_tokens"] == 17 and row["output_tokens"] == 5 and row["token_usage_reported"]
        for row in results
    )
    assert all(row["evidence"] == "synthetic_protocol_only" for row in results)
    assert not outcome["report"]["quality_accepted"] and not outcome["report"]["auto_promoted"]
    assert (path / "results.json").stat().st_mode & 0o777 == 0o600
    assert outcome["report"]["source_message_ids"]


async def test_http_failure_is_durable_and_raw_provider_body_is_not_logged(system, http_endpoint):
    store, data, registry, p, r = system
    base = await deployment(registry, p, r, http_endpoint[0])
    http_endpoint[1]["fail"] = True
    spec = EvaluationSpec(
        persona_id=p,
        relationship_id=r,
        base_deployment_id=base,
        base_pin=PIN,
        variants=["B0"],
        mode="synthetic-protocol",
    )
    result = await EvaluationRunner(store, data, registry).run(spec, [scenario()])
    assert result["report"]["failed_requests"] == 1
    path = Path(result["output_path"])
    row = json.loads((path / "results.json").read_text())[0]
    assert row["error_code"] == "MODEL_UNAVAILABLE" and row["input_tokens"] is None
    assert "PRIVATE_PROVIDER_BODY" not in "".join(p.read_text() for p in path.glob("*.json"))
    with pytest.raises(ValueError, match="no successful"):
        export_blind_sheet(path)


async def test_blind_review_requires_actual_ratings_and_rejects_tamper(system, http_endpoint):
    path, _spec, _result = await protocol_run(system, http_endpoint)
    report = export_blind_sheet(path)
    rating_path = Path(report["path"])
    with rating_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        fields, rows = reader.fieldnames, list(reader)
    assert "variant" not in fields and "model_version_hash" not in fields
    assert all(row["response"].startswith("'=") and row["style_score"] == "" for row in rows)
    with pytest.raises(ValueError, match="no human ratings"):
        summarize_scores(path, rating_path, "synthetic-rating-fixture")
    for row in rows:
        row.update(
            style_score="4",
            grounded_score="3",
            sendable="1",
            privacy_violation="0",
            unauthorized_commitment="0",
        )
    with rating_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize_scores(path, rating_path, "synthetic-rating-fixture")
    assert summary["rated_responses"] == 3 and not summary["partial_review"]
    assert summary["variants"]["B0"]["style_mean"] == 4
    assert (
        summary["acceptance_status"] == "human_decision_required"
        and not summary["quality_accepted"]
    )
    with rating_path.open("a") as handle:
        csv.DictWriter(handle, fieldnames=fields).writerow(rows[0])
    with pytest.raises(ValueError, match="duplicate"):
        summarize_scores(path, rating_path, "fixture")
    results = json.loads((path / "results.json").read_text())
    results[0]["response"] = "tampered"
    (path / "results.json").write_text(json.dumps(results))
    with pytest.raises(ValueError, match="results changed"):
        summarize_scores(path, rating_path, "fixture")


def test_contracts_require_aware_cutoff_and_b3_adapter_and_reject_mock():
    values = scenario().model_dump()
    with pytest.raises(ValueError, match="timezone"):
        EvaluationCase.model_validate(values | {"source_cutoff": "2027-01-01"})
    with pytest.raises(ValueError, match="adapter"):
        EvaluationSpec(persona_id="p", relationship_id="r", base_deployment_id="base", base_pin=PIN)
    with pytest.raises(ValueError, match="HTTP"):
        EvaluationSpec(
            persona_id="p",
            relationship_id="r",
            base_deployment_id="mock-v1",
            base_pin=PIN,
            variants=["B0"],
            mode="synthetic-protocol",
        )
    cases = read_cases(Path(__file__).parents[1] / "examples/evaluation.synthetic.jsonl")
    assert len(cases) == 12 and all(case.synthetic for case in cases)
    assert len({case.category for case in cases}) == 6


async def test_formal_rejects_synthetic_cases_and_unverified_identity(system, http_endpoint):
    store, data, registry, p, r = system
    base = await deployment(registry, p, r, http_endpoint[0])
    spec = EvaluationSpec(
        persona_id=p,
        relationship_id=r,
        base_deployment_id=base,
        base_pin=PIN,
        adapter_deployment_id="unregistered",
    )
    runner = EvaluationRunner(store, data, registry)
    with pytest.raises(ValueError, match="synthetic scenarios"):
        await runner.run(spec, [scenario()])
    http_endpoint[1]["health"] = {"base_model_revision": "mutable-latest"}
    with pytest.raises(DomainError, match="identity"):
        await runner._verify_health({"deployment": registry.deployment(base).model_dump()}, spec)
    http_endpoint[1]["health"] = PIN.model_dump()
    await runner._verify_health({"deployment": registry.deployment(base).model_dump()}, spec)


def test_frozen_test_answers_and_heldout_sources_never_enter_prompt(system, tmp_path):
    store, data, registry, p, r = system
    p = data.create_persona("虚构独立时间数据")["id"]
    r = data.create_relationship(p, "虚构测试关系")["id"]
    path = tmp_path / "segments.csv"
    lines = ["conversation,sender_id,occurred_at,text,message_id"]
    questions = ["吃饭", "天气", "爬山", "咖啡", "旅行", "电影", "音乐", "跑步", "小说", "比赛"]
    answers = ["吃面条", "晴朗", "去高山", "拿铁", "海边", "喜剧", "爵士", "五公里", "科幻", "篮球"]
    for i, (question, answer) in enumerate(zip(questions, answers, strict=True)):
        date = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i)
        lines += [
            f"conv,friend,{date.isoformat()},{question},q{i}",
            f"conv,owner,{(date + timedelta(seconds=30)).isoformat()},{answer},a{i}",
        ]
    path.write_text("\n".join(lines))
    data.import_file(
        path,
        p,
        r,
        "owner",
        "synthetic-split",
        confirm_human=True,
        mapping={"conversation_kind": "private"},
    )
    dataset = data.build_dataset(p, r)
    cases = frozen_test_cases(data, dataset["id"], p, r)
    heldout = cases[0].target_message_ids[0]
    data.add_memory(p, r, "HELDOUT_CANARY 比赛", [heldout], confirmed=True)
    spec = EvaluationSpec(
        persona_id=p,
        relationship_id=r,
        base_deployment_id="unused",
        adapter_deployment_id="unused-adapter",
        base_pin=PIN,
    )
    prepared = prepare_prompts(data, spec, cases)
    for case, prompt in zip(cases, prepared, strict=True):
        assert prompt["prompts"]["B2"] == prompt["prompts"]["B3"]
        assert case.reference not in json.dumps(prompt["prompts"], ensure_ascii=False)
        assert "HELDOUT_CANARY" not in json.dumps(prompt["prompts"])
    altered = cases[0].model_copy(update={"reference": "changed answer"})
    with pytest.raises(ValueError, match="differs"):
        prepare_prompts(data, spec, [altered])
    (Path(dataset["path"]) / "test.jsonl").write_text("tamper")
    with pytest.raises(ValueError, match="hash"):
        frozen_test_cases(data, dataset["id"], p, r)


@pytest.mark.skipif(
    not training_python().is_file(), reason="optional isolated real tiny runtime absent"
)
async def test_b3_requires_actual_registered_adapter_same_pin_and_scope(tmp_path, http_endpoint):
    tiny = tmp_path / "tiny-proof"
    subprocess.run(
        [str(training_python()), "-m", "chattwin.training.smoke", "--output", str(tiny)],
        check=True,
        env=worker_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=45,
    )
    train_spec = TrainingSpec.model_validate_json((tiny / "spec.json").read_text())
    store = Store(tmp_path / "private")
    store.migrate()
    p, r = train_spec.persona_id, train_spec.relationship_id
    destination = store.root / "datasets" / train_spec.dataset_version
    shutil.copytree(train_spec.dataset_path, destination)
    manifest = json.loads((destination / "manifest.json").read_text())
    with store.transaction() as conn:
        conn.execute(personas.insert().values(id=p, payload={"name": "synthetic"}))
        conn.execute(
            relationships.insert().values(id=r, persona_id=p, payload={"name": "synthetic"})
        )
        conn.execute(
            datasets.insert().values(
                id=train_spec.dataset_version, persona_id=p, relationship_id=r, payload=manifest
            )
        )
    registry = ModelRegistry(store, MockProvider(), lambda: None)
    artifact = registry.register(
        ArtifactRegistration(persona_id=p, relationship_id=r, artifact_path=str(tiny / "job"))
    )
    http_endpoint[1]["adapter_health"] = {
        "artifact_manifest_hash": artifact.manifest_hash,
        "persona_id": p,
        "relationship_id": r,
        "model": "synthetic-adapter",
    }
    base = await deployment(registry, p, r, http_endpoint[0])
    adapter = await deployment(
        registry, p, r, http_endpoint[0].replace("/v1", "/adapter/v1"), artifact.id
    )
    pin = ModelPin(**{key: getattr(train_spec, key) for key in ModelPin.model_fields})
    spec = EvaluationSpec(
        persona_id=p,
        relationship_id=r,
        base_deployment_id=base,
        adapter_deployment_id=adapter,
        base_pin=pin,
        mode="synthetic-protocol",
    )
    runner = EvaluationRunner(store, DataService(store), registry)
    outcome = await runner.run(spec, [scenario()])
    results = json.loads((Path(outcome["output_path"]) / "results.json").read_text())
    assert len(results) == 4 and all(item["status"] == "succeeded" for item in results)
    assert results[2]["prompt_hash"] == results[3]["prompt_hash"]
    assert results[2]["model_version_hash"] != results[3]["model_version_hash"]
    formal = spec.model_copy(update={"mode": "formal"})
    with pytest.raises(ValueError, match="tiny synthetic"):
        runner._model_records(formal)
    wrong = spec.model_copy(update={"base_pin": PIN})
    with pytest.raises(ValueError, match="same frozen"):
        runner._model_records(wrong)
    store.close()
