import json
from pathlib import Path

import pytest

from chattwin.runtime_paths import training_code_hash
from chattwin.training.masking import encode_target, pad_batch
from chattwin.training.spec import TrainingSpec, canonical_hash, validate_dataset, validate_scope
from chattwin.training.worker import worker_environment


class TokenProofTokenizer:
    """Token IDs make role boundaries explicit; repeated text cannot locate a target."""

    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        role_ids = {"system": 10, "user": 11, "assistant": 12}
        result = []
        for message in messages:
            result.extend([role_ids[message["role"]], *message["content"].encode(), 2])
        if add_generation_prompt:
            result.append(12)
        return result


def test_only_final_owner_target_has_loss_even_when_text_repeats():
    tokenizer = TokenProofTokenizer()
    messages = [
        {"role": "system", "content": "same"},
        {"role": "user", "content": "same"},
        {"role": "assistant", "content": "same"},
        {"role": "user", "content": "same"},
        {"role": "assistant", "content": "same"},
    ]
    row = encode_target(tokenizer, {"messages": messages, "target_index": 4}, 128)
    prefix = tokenizer.apply_chat_template(messages[:-1], True, True)
    assert row["labels"][: len(prefix)] == [-100] * len(prefix)
    assert row["labels"][len(prefix) :] == [*b"same", 2]
    shorter = encode_target(tokenizer, {"messages": messages[-2:]}, 128)
    padded = pad_batch([row, shorter], 0)
    assert padded["labels"][1][len(shorter["labels"]) :] == [-100] * (
        len(row["labels"]) - len(shorter["labels"])
    )


def test_template_without_stable_token_prefix_and_truncated_targets_are_rejected():
    class BrokenTokenizer(TokenProofTokenizer):
        def apply_chat_template(self, messages, tokenize, add_generation_prompt):
            return super().apply_chat_template(messages, tokenize, add_generation_prompt) + [999]

    example = {
        "messages": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    }
    with pytest.raises(ValueError, match="boundary"):
        encode_target(BrokenTokenizer(), example, 128)
    with pytest.raises(ValueError, match="truncated"):
        encode_target(TokenProofTokenizer(), example, 4)


def make_spec(tmp_path: Path, **updates):
    values = dict(
        dataset_path=tmp_path / "dataset",
        dataset_version="dataset-v1",
        dataset_hash="a" * 64,
        persona_id="p",
        relationship_id="r",
        output_path=tmp_path / "job",
        dependency_lock_hash="b" * 64,
        code_version="source:" + training_code_hash(),
    )
    return TrainingSpec(**(values | updates))


def test_fixed_revisions_scope_and_output_boundary(tmp_path):
    with pytest.raises(ValueError, match="fixed commit"):
        make_spec(tmp_path, base_model_revision="main")
    with pytest.raises(ValueError, match="CPU"):
        make_spec(tmp_path, device="cpu")
    with pytest.raises(ValueError, match="scope"):
        validate_scope({"persona_id": "p", "relationship_id": "r"}, "p", "other")
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="Git"):
        make_spec(tmp_path, output_path=checkout / "private")


def test_dataset_tampering_and_wrong_relationship_rejected(tmp_path):
    import hashlib

    dataset = tmp_path / "dataset"
    dataset.mkdir()
    files = {}
    for split in ("train", "validation", "test"):
        path = dataset / (split + ".jsonl")
        path.write_text("")
        files[path.name] = hashlib.sha256(b"").hexdigest()
    manifest = {
        "id": "dataset-v1",
        "schema_version": "1.0",
        "persona_id": "p",
        "relationship_id": "r",
        "files": files,
    }
    digest = canonical_hash(manifest)
    manifest["dataset_hash"] = digest
    (dataset / "manifest.json").write_text(json.dumps(manifest))
    spec = make_spec(tmp_path, dataset_hash=digest)
    assert validate_dataset(spec)["id"] == "dataset-v1"
    with pytest.raises(ValueError, match="relationship_id"):
        validate_dataset(make_spec(tmp_path, dataset_hash=digest, relationship_id="other"))
    (dataset / "train.jsonl").write_text("tampered")
    with pytest.raises(ValueError, match="file hash"):
        validate_dataset(spec)


def test_worker_child_does_not_inherit_channel_or_admin_secrets(monkeypatch):
    monkeypatch.setenv("QQ_ACCESS_TOKEN", "private")
    monkeypatch.setenv("CHATTWIN_ADMIN_TOKEN", "private")
    monkeypatch.setenv("OPENAI_API_KEY", "private")
    monkeypatch.setenv("HF_TOKEN", "private")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    environment = worker_environment()
    assert (
        not {"QQ_ACCESS_TOKEN", "CHATTWIN_ADMIN_TOKEN", "OPENAI_API_KEY", "HF_TOKEN"}
        & environment.keys()
    )
    assert environment["HF_HUB_DISABLE_IMPLICIT_TOKEN"] == "1"
    assert environment["CUDA_VISIBLE_DEVICES"] == "1"


@pytest.mark.parametrize(
    "injected",
    [
        {"_attn_implementation_internal": "fictional/remote-kernel"},
        {"_attn_implementation": "fictional/remote-kernel"},
        {"subconfig": {"_experts_implementation_internal": "fictional/remote-kernel"}},
        {"attn_implementation": "fictional/remote-kernel"},
        {"auto_map": {"AutoModel": "untrusted.Model"}},
        {"custom_generate": "fictional/generation"},
        {"custom_pipelines": {"task": "untrusted.Pipeline"}},
    ],
)
def test_model_config_rejects_custom_code_before_library_loading(injected):
    from chattwin.training.loading import validate_config

    with pytest.raises(ValueError, match="kernel|custom"):
        validate_config(injected)
    validate_config({"model_type": "qwen3", "attn_implementation": "sdpa"})


@pytest.mark.parametrize(
    "changed", [{"base_model_id": "fictional/other-base"}, {"base_model_revision": "b" * 40}]
)
def test_unreviewed_remote_repository_rejected_before_any_download(tmp_path, changed):
    from chattwin.training.loading import validate_loading_inputs

    with pytest.raises(ValueError, match="fixed reference"):
        validate_loading_inputs(make_spec(tmp_path, **changed))


def test_worker_refuses_source_drift_before_loading_data_or_model(tmp_path, monkeypatch):
    from chattwin.training.worker import train

    spec = make_spec(tmp_path)
    monkeypatch.setattr("chattwin.training.worker.training_code_hash", lambda: "f" * 64)
    with pytest.raises(ValueError, match="source code fingerprint mismatch"):
        train(spec)
    state = json.loads((spec.output_path / "status.json").read_text())
    assert state["status"] == "failed" and "fingerprint mismatch" in state["error"]
    assert not (spec.output_path / "adapter").exists()
    with pytest.raises(ValueError, match="prepared again"):
        make_spec(tmp_path, code_version="working-tree")
