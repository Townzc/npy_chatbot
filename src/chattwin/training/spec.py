"""Validated, frozen training inputs and scope checks; no model dependencies."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from chattwin.runtime_paths import training_code_hash, training_lock_path

QWEN_REVISION = "cdbee75f17c01a7cc42f958dc650907174af0554"
QWEN_TEMPLATE_HASH = "64f85b198065d0fba2a81f37e10ed68161ce2c19a754c7100e67e0ca2ee9c326"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def local_model_hash(path: Path) -> str:
    """Pin all files of a local model, including tokenizer, config and weights."""
    files = {
        str(p.relative_to(path)): sha256_file(p) for p in sorted(path.rglob("*")) if p.is_file()
    }
    if not files:
        raise ValueError("local model directory is empty")
    return canonical_hash(files)


def private_output(path: Path) -> Path:
    path = path.expanduser().resolve()
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise ValueError("training output must be outside a Git checkout")
    return path


class TrainingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    dataset_path: Path
    dataset_version: str = Field(min_length=1)
    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    persona_id: str = Field(min_length=1)
    relationship_id: str = Field(min_length=1)
    base_model_id: str = "Qwen/Qwen3-4B-Instruct-2507"
    base_model_revision: str = QWEN_REVISION
    tokenizer_revision: str = QWEN_REVISION
    chat_template_hash: str = QWEN_TEMPLATE_HASH
    backend: Literal["transformers-peft"] = "transformers-peft"
    backend_version: Literal["1"] = "1"
    precision: Literal["float32", "bfloat16", "float16"] = "bfloat16"
    device: Literal["cpu", "cuda"] = "cuda"
    target_modules: list[str] = Field(default_factory=lambda: ["q_proj", "v_proj"])
    rank: int = Field(default=8, ge=1, le=128)
    alpha: int = Field(default=16, ge=1, le=1024)
    dropout: float = Field(default=0.05, ge=0, lt=1)
    max_sequence_length: int = Field(default=1024, ge=16, le=32768)
    batch_size: int = Field(default=1, ge=1, le=128)
    gradient_accumulation: int = Field(default=4, ge=1, le=1024)
    learning_rate: float = Field(default=2e-4, gt=0, le=0.1)
    epochs: int = Field(default=1, ge=1, le=100)
    max_steps: int = Field(default=100, ge=1, le=1000000)
    seed: int = Field(default=42, ge=0)
    output_path: Path
    cancel_path: Path | None = None
    dependency_lock_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_version: str
    synthetic_smoke: bool = False
    local_files_only: bool = False

    @field_validator("code_version")
    @classmethod
    def pinned_training_source(cls, value: str) -> str:
        if not re.fullmatch(r"source:[0-9a-f]{64}", value):
            raise ValueError(
                "code_version requires source:<sha256>; legacy working-tree specs must be prepared again"
            )
        return value

    @field_validator("dataset_path", "output_path", "cancel_path", mode="before")
    @classmethod
    def absolute_paths(cls, value: Any) -> str | None:
        return str(Path(value).expanduser().resolve()) if value is not None else None

    @model_validator(mode="after")
    def immutable_inputs(self) -> TrainingSpec:
        for revision in (self.base_model_revision, self.tokenizer_revision):
            if not re.fullmatch(r"[0-9a-f]{40}|local:[0-9a-f]{64}", revision):
                raise ValueError("model/tokenizer revisions must be fixed commit hashes")
        if not re.fullmatch(r"[0-9a-f]{64}", self.chat_template_hash):
            raise ValueError("chat_template_hash must be SHA-256")
        if not self.target_modules or any(
            not re.fullmatch(r"[A-Za-z0-9_.]+", m) for m in self.target_modules
        ):
            raise ValueError("explicit LoRA module names required")
        if self.device == "cpu" and (not self.synthetic_smoke or self.precision != "float32"):
            raise ValueError("CPU is only validated for synthetic float32 tiny smoke")
        if self.synthetic_smoke and not self.base_model_revision.startswith("local:"):
            raise ValueError("synthetic smoke requires a pinned local tiny model")
        if self.base_model_revision.startswith("local:"):
            if self.tokenizer_revision != self.base_model_revision or not self.local_files_only:
                raise ValueError("local model/tokenizer must share a content pin and stay offline")
            if not Path(self.base_model_id).is_absolute():
                raise ValueError("local model path must be absolute")
        private_output(self.output_path)
        return self


def validate_dataset(spec: TrainingSpec) -> dict[str, Any]:
    root = spec.dataset_path.expanduser().resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    digest = canonical_hash(
        {k: v for k, v in manifest.items() if k not in {"dataset_hash", "path"}}
    )
    if digest != spec.dataset_hash or manifest.get("dataset_hash") != digest:
        raise ValueError("dataset manifest hash mismatch")
    for key, expected in (
        ("id", spec.dataset_version),
        ("persona_id", spec.persona_id),
        ("relationship_id", spec.relationship_id),
    ):
        if manifest.get(key) != expected:
            raise ValueError(f"dataset {key} does not match TrainingSpec")
    if manifest.get("schema_version") != "1.0":
        raise ValueError("unsupported dataset schema")
    for filename in ("train.jsonl", "validation.jsonl", "test.jsonl"):
        if manifest.get("files", {}).get(filename) != sha256_file(root / filename):
            raise ValueError(f"dataset file hash mismatch: {filename}")
    return manifest


def validate_scope(manifest: dict[str, Any], persona_id: str, relationship_id: str) -> None:
    if (manifest.get("persona_id"), manifest.get("relationship_id")) != (
        persona_id,
        relationship_id,
    ):
        raise ValueError("adapter scope mismatch")


def prepare_spec(dataset_path: Path, output_path: Path) -> TrainingSpec:
    """Prepare the pinned Qwen candidate. This does not assert GPU compatibility."""
    manifest = json.loads((dataset_path.expanduser() / "manifest.json").read_text())
    lock = training_lock_path()
    spec = TrainingSpec(
        dataset_path=dataset_path,
        dataset_version=manifest["id"],
        dataset_hash=manifest["dataset_hash"],
        persona_id=manifest["persona_id"],
        relationship_id=manifest["relationship_id"],
        output_path=output_path,
        cancel_path=output_path / "cancel.requested",
        dependency_lock_hash=sha256_file(lock),
        code_version="source:" + training_code_hash(),
    )
    validate_dataset(spec)
    return spec
