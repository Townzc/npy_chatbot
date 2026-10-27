"""Run explicitly in training/.venv; core installations skip optional model dependencies."""

import json
from pathlib import Path

import pytest

pytest.importorskip("torch")
pytest.importorskip("peft")

from fastapi.testclient import TestClient
from transformers import AutoTokenizer

from chattwin.training.masking import encode_target
from chattwin.training.serve import create_inference_app
from chattwin.training.smoke import create_smoke_spec
from chattwin.training.worker import train, verify_artifact


@pytest.fixture(scope="module")
def artifact(tmp_path_factory):
    root = tmp_path_factory.mktemp("real-tiny-lora")
    spec = create_smoke_spec(root)
    result = train(spec)
    return spec, result


def test_real_lora_updates_saves_and_reloads_in_new_process(artifact):
    spec, result = artifact
    report = result["report"]
    assert report["max_parameter_update"] > 0
    assert report["reload_comparison"]["pid"] != report["training_pid"]
    assert report["reload_comparison"]["max_logit_delta"] > 0
    assert (spec.output_path / "adapter/adapter_model.safetensors").exists()
    assert report["evidence"] == "tiny_cpu_smoke"
    assert result["manifest"]["relationship_id"] == spec.relationship_id


def test_checkpointed_lora_recomputes_without_losing_frozen_input_gradients(artifact, tmp_path):
    from safetensors.torch import load_file

    spec, original = artifact
    checkpointed = spec.model_copy(
        update={"output_path": tmp_path / "checkpointed", "gradient_checkpointing": True}
    )
    result = train(checkpointed)
    assert result["report"]["gradient_checkpointing"] is True
    assert result["report"]["max_parameter_update"] > 0
    assert result["report"]["reload_comparison"]["max_logit_delta"] > 0
    assert result["report"]["reload_comparison"]["pid"] != result["report"]["training_pid"]
    assert result["report"]["losses"] == pytest.approx(original["report"]["losses"], abs=1e-6)
    expected = load_file(spec.output_path / "adapter/adapter_model.safetensors")
    actual = load_file(checkpointed.output_path / "adapter/adapter_model.safetensors")
    for name, tensor in expected.items():
        assert actual[name].allclose(tensor, atol=1e-6)


def test_real_tokenizer_masks_history_and_keeps_current_target(artifact):
    spec, _ = artifact
    tokenizer = AutoTokenizer.from_pretrained(spec.base_model_id, local_files_only=True)
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hi"},
    ]
    row = encode_target(tokenizer, {"messages": messages, "target_index": 3}, 64)
    boundary = len(
        tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True)
    )
    assert row["labels"][:boundary] == [-100] * boundary
    assert tokenizer.decode(row["labels"][boundary:]) == "hi <eos>"


def test_endpoint_auth_scope_and_actual_inference(artifact):
    spec, _ = artifact
    token = "test-model-token-" + "x" * 32
    app = create_inference_app(spec.output_path, token)
    client = TestClient(app)
    body = {
        "model": "chattwin-adapter",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 4,
        "metadata": {"persona_id": spec.persona_id, "relationship_id": spec.relationship_id},
    }
    assert client.post("/v1/chat/completions", json=body).status_code == 401
    headers = {"Authorization": "Bearer " + token}
    from chattwin.training.spec import sha256_file

    health = client.get("/health", headers=headers)
    assert health.status_code == 200
    assert health.json()["artifact_manifest_hash"] == sha256_file(
        spec.output_path / "manifest.json"
    )
    assert health.json()["persona_id"] == spec.persona_id
    mismatch = {**body, "metadata": {**body["metadata"], "relationship_id": "another-friend"}}
    assert client.post("/v1/chat/completions", json=mismatch, headers=headers).status_code == 403
    response = client.post("/v1/chat/completions", json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["usage"]["completion_tokens"] > 0
    base_response = client.post(
        "/v1/chat/completions", json={**body, "model": "chattwin-base"}, headers=headers
    )
    assert base_response.status_code == 200
    assert base_response.json()["model"] == "chattwin-base"
    assert base_response.json()["chattwin_evidence"] == "tiny_cpu_smoke"
    after_base = client.post("/v1/chat/completions", json=body, headers=headers)
    assert after_base.json()["choices"] == response.json()["choices"]


def test_cancellation_preserves_truthful_state_before_loading(artifact, tmp_path):
    spec, _ = artifact
    flag = tmp_path / "cancel"
    flag.touch()
    stopped = spec.model_copy(update={"output_path": tmp_path / "cancelled", "cancel_path": flag})
    result = train(stopped)
    assert result["status"] == "cancelled"
    assert not (stopped.output_path / "manifest.json").exists()


def test_inference_caps_output_without_truncating_prompt(artifact):
    spec, _ = artifact
    client = TestClient(create_inference_app(spec.output_path, "synthetic-budget-" + "x" * 32))
    headers = {"Authorization": "Bearer synthetic-budget-" + "x" * 32}
    messages = [{"role": "user", "content": "hello friend"}]
    body = {
        "model": "chattwin-adapter",
        "messages": messages,
        "max_tokens": 1024,
        "metadata": {"persona_id": spec.persona_id, "relationship_id": spec.relationship_id},
    }
    tokenizer = AutoTokenizer.from_pretrained(spec.base_model_id, local_files_only=True)
    prompt_size = len(
        tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
    )
    response = client.post("/v1/chat/completions", json=body, headers=headers)
    assert response.status_code == 200
    result = response.json()
    assert result["usage"]["prompt_tokens"] == prompt_size
    assert 0 < result["usage"]["completion_tokens"] <= spec.max_sequence_length - prompt_size
    assert result["usage"]["total_tokens"] <= spec.max_sequence_length
    assert result["choices"][0]["finish_reason"] in {"stop", "length"}
    overflow = {
        **body,
        "messages": [{"role": "user", "content": "hello " * spec.max_sequence_length}],
    }
    assert client.post("/v1/chat/completions", json=overflow, headers=headers).status_code == 413


def test_tampered_artifact_refused(artifact, tmp_path):
    import shutil

    spec, _ = artifact
    copied = tmp_path / "artifact"
    shutil.copytree(spec.output_path, copied)
    manifest_path = copied / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["relationship_id"] = "unrelated"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="mismatch"):
        verify_artifact(copied)


def test_interrupted_job_is_not_resumed_or_overwritten(artifact, tmp_path):
    spec, _ = artifact
    work = tmp_path / "interrupted"
    work.mkdir()
    (work / "status.json").write_text(json.dumps({"status": "running", "step": 3}))
    with pytest.raises(ValueError, match="no implicit resume"):
        train(spec.model_copy(update={"output_path": work}))
    assert json.loads((work / "status.json").read_text())["status"] == "interrupted"


def test_imported_synthetic_dataset_enters_real_worker(artifact, tmp_path):
    from chattwin.importers import DataService
    from chattwin.storage import Store
    from chattwin.training.spec import prepare_spec

    tiny, _ = artifact
    store = Store(tmp_path / "private")
    store.migrate()
    service = DataService(store)
    persona = service.create_persona("Synthetic training integration")
    relationship = service.create_relationship(persona["id"], "Synthetic friend")
    fixture = Path(__file__).resolve().parents[1] / "examples/chatlab_wechat.synthetic.jsonl"
    service.import_file(
        fixture, persona["id"], relationship["id"], "demo_owner", "demo_source", confirm_human=True
    )
    dataset = service.build_dataset(persona["id"], relationship["id"])
    qwen_spec = prepare_spec(Path(dataset["path"]), tmp_path / "integrated-job")
    spec = tiny.model_copy(
        update={
            "dataset_path": qwen_spec.dataset_path,
            "dataset_version": qwen_spec.dataset_version,
            "dataset_hash": qwen_spec.dataset_hash,
            "persona_id": persona["id"],
            "relationship_id": relationship["id"],
            "output_path": qwen_spec.output_path,
            "max_steps": 2,
            "epochs": 2,
        }
    )
    result = train(spec)
    assert result["report"]["max_parameter_update"] > 0
    assert result["manifest"]["dataset_hash"] == dataset["dataset_hash"]
    assert result["manifest"]["persona_id"] == persona["id"]
    from chattwin.models import MockProvider
    from chattwin.models.registry import ArtifactRegistration, ModelRegistry

    registry = ModelRegistry(store, MockProvider(), lambda: None)
    registered = registry.register(
        ArtifactRegistration(
            persona_id=persona["id"],
            relationship_id=relationship["id"],
            artifact_path=str(spec.output_path),
        )
    )
    assert registered.status == "validated"
    assert registered.manifest["dataset_hash"] == dataset["dataset_hash"]
    assert registered.manifest["evidence"] == "tiny_cpu_smoke"
    store.close()
