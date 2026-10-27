"""Inspect pinned JSON before model libraries can interpret executable settings.

Defense in depth for the validated 4.x backend, not a replacement for upgrading
the training stack or permission to load untrusted model repositories.
"""

import hashlib
import json
from pathlib import Path

from .spec import QWEN_REVISION, TrainingSpec


def validate_config(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            # Internal kernel selectors can bypass trust_remote_code in upstream
            # versions covered by GHSA-29pf-2h5f-8g72. Do not deserialize them.
            if key in {
                "_attn_implementation",
                "_attn_implementation_internal",
                "_experts_implementation",
                "_experts_implementation_internal",
            }:
                raise ValueError("model configuration contains an internal kernel selector")
            if key in {"attn_implementation", "experts_implementation"} and child not in (
                None,
                "eager",
                "sdpa",
            ):
                raise ValueError("custom model kernel implementations are unsupported")
            if key in {"auto_map", "custom_generate", "custom_pipelines"} and child:
                raise ValueError("custom model code configuration is unsupported")
            validate_config(child)
    elif isinstance(value, list):
        for child in value:
            validate_config(child)


def _read_pinned_file(spec: TrainingSpec, filename: str, revision: str) -> str:
    if revision.startswith("local:"):
        path = Path(spec.base_model_id) / filename
    else:
        from huggingface_hub import hf_hub_download

        path = Path(
            hf_hub_download(
                repo_id=spec.base_model_id,
                filename=filename,
                revision=revision,
                local_files_only=spec.local_files_only,
                token=False,
            )
        )
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("model configuration exceeds the supported size")
    return path.read_text()


def _read_pinned_config(spec: TrainingSpec, filename: str, revision: str) -> dict:
    value = json.loads(_read_pinned_file(spec, filename, revision))
    if not isinstance(value, dict):
        raise ValueError("model configuration must be a JSON object")
    validate_config(value)
    return value


def validate_loading_inputs(spec: TrainingSpec) -> None:
    local = spec.base_model_revision.startswith("local:")
    if local:
        root = Path(spec.base_model_id)
        if not spec.synthetic_smoke:
            raise ValueError("local bases are supported only for synthetic tiny smoke")
        if (root / "custom_generate").exists() or any(root.rglob("*.py")):
            raise ValueError("custom model code files are unsupported")
    elif (
        spec.base_model_id != "Qwen/Qwen3-4B-Instruct-2507"
        or spec.base_model_revision != QWEN_REVISION
        or spec.tokenizer_revision != QWEN_REVISION
    ):
        raise ValueError("this backend supports only the fixed reference Qwen repository/revision")
    config = _read_pinned_config(spec, "config.json", spec.base_model_revision)
    if config.get("model_type") != "qwen3":
        raise ValueError("unsupported model architecture for this validated backend")
    tokenizer = _read_pinned_config(spec, "tokenizer_config.json", spec.tokenizer_revision)
    template = tokenizer.get("chat_template")
    if template is None:
        template = _read_pinned_file(spec, "chat_template.jinja", spec.tokenizer_revision)
    # Named template dictionaries are not part of this backend. Reject before
    # save_pretrained can turn a template key into a path (GHSA-xrqw-3rrv-vx5w).
    if not isinstance(template, str) or not template:
        raise ValueError("tokenizer configuration requires one pinned string chat template")
    if hashlib.sha256(template.encode()).hexdigest() != spec.chat_template_hash:
        raise ValueError("tokenizer chat template hash mismatch")
