"""Real LoRA optimizer/save/reload pipeline, launched in the isolated training environment."""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import signal
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from filelock import FileLock

from chattwin.runtime_paths import training_code_hash, training_lock_path

from .hardware import inspect_cuda
from .masking import encode_target, pad_batch
from .spec import (
    QWEN_REVISION,
    QWEN_TEMPLATE_HASH,
    TrainingSpec,
    local_model_hash,
    prepare_spec,
    sha256_file,
    validate_dataset,
)


def worker_environment() -> dict[str, str]:
    """Allowlist for a child worker; channel/admin/provider secrets are never inherited."""
    allowed = {
        "PATH",
        "HOME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "VIRTUAL_ENV",
        "PYTHONPATH",
        "XDG_CACHE_HOME",
        "HF_HOME",
        "HF_HUB_CACHE",
        "CUDA_VISIBLE_DEVICES",
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment.update(
        HF_HUB_DISABLE_TELEMETRY="1",
        HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
        WANDB_DISABLED="true",
        TOKENIZERS_PARALLELISM="false",
    )
    return environment


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def _imports() -> tuple[Any, Any, Any, Any, Any, Any]:
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    try:
        import torch
        from peft import LoraConfig, PeftModel, get_peft_model
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(
            "Run with: uv run --project training python -m chattwin.training.worker"
        ) from exc
    return torch, LoraConfig, PeftModel, get_peft_model, AutoModelForCausalLM, AutoTokenizer


def load_base(spec: TrainingSpec) -> tuple[Any, Any, Any]:
    torch, _, _, _, auto_model, auto_tokenizer = _imports()
    expected_versions = {
        "torch": "2.9.1",
        "transformers": "4.57.6",
        "peft": "0.18.1",
        "accelerate": "1.12.0",
        "safetensors": "0.7.0",
    }
    if any(
        version.split("+")[0] != expected_versions[name] for name, version in _versions().items()
    ):
        raise ValueError("installed training dependencies differ from the validated pins")
    local = spec.base_model_revision.startswith("local:")
    if local and local_model_hash(Path(spec.base_model_id)) != spec.base_model_revision[6:]:
        raise ValueError("local base model content changed")
    if spec.device == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA unavailable; this is not a supported production training host")
    if (
        spec.precision == "bfloat16"
        and spec.device == "cuda"
        and not torch.cuda.is_bf16_supported(including_emulation=False)
    ):
        raise ValueError("CUDA device does not support bf16")
    tokenizer = auto_tokenizer.from_pretrained(
        spec.base_model_id,
        revision=None if local else spec.tokenizer_revision,
        trust_remote_code=False,
        local_files_only=spec.local_files_only,
    )
    if (
        not tokenizer.chat_template
        or hashlib.sha256(tokenizer.chat_template.encode()).hexdigest() != spec.chat_template_hash
    ):
        raise ValueError("tokenizer chat template hash mismatch")
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = auto_model.from_pretrained(
        spec.base_model_id,
        revision=None if local else spec.base_model_revision,
        trust_remote_code=False,
        use_safetensors=True,
        local_files_only=spec.local_files_only,
        dtype=getattr(torch, spec.precision),
    ).to(spec.device)
    return torch, model, tokenizer


def _versions() -> dict[str, str]:
    return {
        name: importlib.metadata.version(name)
        for name in ("torch", "transformers", "peft", "accelerate", "safetensors")
    }


def _require_code_version(spec: TrainingSpec) -> str:
    actual = training_code_hash()
    if spec.code_version != "source:" + actual:
        raise ValueError(
            "training source code fingerprint mismatch; prepare a new spec with the intended code version"
        )
    return actual


def train(spec: TrainingSpec) -> dict[str, Any]:
    """Fresh job only. Interrupted jobs are preserved; resumption is not implemented."""
    work = spec.output_path.expanduser().resolve()
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    work.chmod(0o700)
    with FileLock(str(work / "worker.lock"), timeout=0):
        if (work / "status.json").exists():
            previous = json.loads((work / "status.json").read_text())
            if previous.get("status") in {"running", "validating"}:
                write_json(work / "status.json", {**previous, "status": "interrupted"})
            raise ValueError("job output already exists; use a new directory (no implicit resume)")
        return _train_locked(spec, work)


def _train_locked(spec: TrainingSpec, work: Path) -> dict[str, Any]:
    started = time.time()
    cancelled = False
    old_handlers: dict[int, Any] = {}
    torch = None
    status: dict[str, Any] = {
        "status": "validating",
        "pid": os.getpid(),
        "step": 0,
        "evidence": "tiny_cpu_smoke" if spec.synthetic_smoke else "real_training",
    }

    def update(**values: Any) -> None:
        status.update(values, heartbeat=time.time())
        write_json(work / "status.json", status)

    def stop(_signal: int, _frame: Any) -> None:
        nonlocal cancelled
        cancelled = True

    def is_cancelled() -> bool:
        return cancelled or bool(spec.cancel_path and spec.cancel_path.exists())

    update()
    write_json(work / "training_spec.json", spec.model_dump(mode="json"))
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            old_handlers[signum] = signal.signal(signum, stop)
        except ValueError:
            pass  # API runners should spawn a separate worker process.
    try:
        actual_code_hash = _require_code_version(spec)
        dataset_manifest = validate_dataset(spec)
        lock = training_lock_path()
        if not lock.exists() or sha256_file(lock) != spec.dependency_lock_hash:
            raise ValueError("training dependency lock hash mismatch")
        if is_cancelled():
            update(status="cancelled")
            return status
        torch, *_ = _imports()
        hardware = inspect_cuda(torch)
        write_json(work / "hardware.json", hardware)
        if spec.device == "cuda" and hardware["cuda_available"]:
            torch.cuda.reset_peak_memory_stats()
        torch, model, tokenizer = load_base(spec)
        torch.manual_seed(spec.seed)
        if spec.device == "cuda":
            torch.cuda.manual_seed_all(spec.seed)
        examples = [
            json.loads(line)
            for line in (spec.dataset_path / "train.jsonl").read_text().splitlines()
            if line.strip()
        ]
        encoded, accepted = [], []
        skipped: dict[str, int] = {}
        for example in examples:
            try:
                encoded.append(encode_target(tokenizer, example, spec.max_sequence_length))
                accepted.append(example)
            except ValueError as exc:
                reason = str(exc)
                skipped[reason] = skipped.get(reason, 0) + 1
        if not encoded:
            raise ValueError("no valid training targets after token boundary/truncation checks")
        _, lora_config, _, get_peft_model, _, _ = _imports()
        model = get_peft_model(
            model,
            lora_config(
                r=spec.rank,
                lora_alpha=spec.alpha,
                lora_dropout=spec.dropout,
                target_modules=spec.target_modules,
                bias="none",
                task_type="CAUSAL_LM",
            ),
        )
        model.config.use_cache = False
        if spec.gradient_checkpointing:
            # Non-reentrant checkpointing supports frozen base/embedding inputs.
            model.gradient_checkpointing_enable(
                gradient_checkpointing_kwargs={"use_reentrant": False}
            )
            if not model.is_gradient_checkpointing:
                raise ValueError("model did not enable gradient checkpointing")
        trainable = {name: param for name, param in model.named_parameters() if param.requires_grad}
        initial = {name: value.detach().cpu().clone() for name, value in trainable.items()}
        if not trainable:
            raise ValueError("no trainable LoRA parameters")
        optimizer = torch.optim.AdamW(trainable.values(), lr=spec.learning_rate)
        scaler = torch.amp.GradScaler(
            "cuda", enabled=spec.device == "cuda" and spec.precision == "float16"
        )
        model.train()
        update(status="running", accepted_examples=len(encoded), skipped=skipped)
        losses: list[float] = []
        steps = 0
        batches = [
            encoded[i : i + spec.batch_size] for i in range(0, len(encoded), spec.batch_size)
        ]
        for _epoch in range(spec.epochs):
            for group_start in range(0, len(batches), spec.gradient_accumulation):
                if is_cancelled() or steps >= spec.max_steps:
                    break
                group = batches[group_start : group_start + spec.gradient_accumulation]
                optimizer.zero_grad(set_to_none=True)
                for rows in group:
                    if is_cancelled():
                        break
                    tensors = {
                        k: torch.tensor(v, device=spec.device)
                        for k, v in pad_batch(rows, tokenizer.pad_token_id).items()
                    }
                    amp = (
                        torch.autocast("cuda", dtype=getattr(torch, spec.precision))
                        if spec.device == "cuda" and spec.precision != "float32"
                        else nullcontext()
                    )
                    with amp:
                        loss = model(**tensors).loss
                    value = float(loss.detach().cpu())
                    if not math.isfinite(value):
                        raise ValueError("training loss became non-finite")
                    losses.append(value)
                    scaler.scale(loss / len(group)).backward()
                    del loss, tensors
                if is_cancelled():
                    break
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(list(trainable.values()), 1.0)
                scaler.step(optimizer)
                scaler.update()
                steps += 1
                update(step=steps, loss=losses[-1])
            if is_cancelled() or steps >= spec.max_steps:
                break
        if is_cancelled():
            model.save_pretrained(work / "cancelled_checkpoint", safe_serialization=True)
            update(status="cancelled", checkpoint="cancelled_checkpoint", resume_supported=False)
            return status
        max_update = max(
            float((param.detach().cpu() - initial[name]).abs().max())
            for name, param in trainable.items()
        )
        if not math.isfinite(max_update) or max_update <= 0:
            raise ValueError("no finite LoRA parameter update observed")
        adapter_dir = work / "adapter"
        model.save_pretrained(adapter_dir, safe_serialization=True)
        tokenizer.save_pretrained(work / "tokenizer")
        report = {
            "evidence": status["evidence"],
            "steps": steps,
            "losses": losses,
            "trainable_parameters": sum(p.numel() for p in trainable.values()),
            "max_parameter_update": max_update,
            "accepted_examples": len(encoded),
            "skipped": skipped,
            "elapsed_seconds": time.time() - started,
            "training_pid": os.getpid(),
            "platform": platform.platform(),
            "dependencies": _versions(),
            "hardware": hardware,
            "gradient_checkpointing": spec.gradient_checkpointing,
            "distributed_training": False,
            "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated()
            if spec.device == "cuda"
            else None,
            "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved()
            if spec.device == "cuda"
            else None,
            "quality_evaluation": "UNVERIFIED; loss and reload smoke do not establish chat quality",
        }
        if _require_code_version(spec) != actual_code_hash:
            raise ValueError("training code changed during execution")
        manifest = {
            "schema_version": "1.0",
            "persona_id": spec.persona_id,
            "relationship_id": spec.relationship_id,
            "dataset_version": spec.dataset_version,
            "dataset_hash": spec.dataset_hash,
            "dataset_source_ids": dataset_manifest.get("source_message_ids", []),
            "base_model_id": spec.base_model_id,
            "base_model_revision": spec.base_model_revision,
            "tokenizer_revision": spec.tokenizer_revision,
            "chat_template_hash": spec.chat_template_hash,
            "dependency_lock_hash": spec.dependency_lock_hash,
            "code_version": spec.code_version,
            "training_code_hash": actual_code_hash,
            "evidence": status["evidence"],
            "license": "local synthetic weights"
            if spec.synthetic_smoke
            else "base and dataset licenses apply",
            "files": {
                str(p.relative_to(work)): sha256_file(p)
                for p in sorted(adapter_dir.glob("*"))
                if p.is_file()
            },
            "deployment_status": "unreviewed",
        }
        write_json(work / "manifest.json", manifest)
        write_json(work / "reload_prompt.json", accepted[0]["messages"][:-1])
        # Free GPU model before independent reload to avoid doubling peak VRAM.
        del model, optimizer, trainable, initial, scaler
        gc.collect()
        if spec.device == "cuda":
            torch.cuda.empty_cache()
        process = subprocess.Popen(
            [sys.executable, "-m", "chattwin.training.worker", "compare", "--artifact", str(work)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=worker_environment(),
        )
        reload_deadline = time.monotonic() + 600
        while True:
            try:
                _stdout, stderr = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if is_cancelled() or time.monotonic() > reload_deadline:
                    process.terminate()
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    if is_cancelled():
                        update(status="cancelled", phase="reload", resume_supported=False)
                        return status
                    raise TimeoutError("fresh-process reload exceeded 600 seconds")
                update(phase="reload")
        if process.returncode:
            raise RuntimeError("fresh-process reload failed; " + stderr[-1000:])
        comparison = json.loads((work / "reload_comparison.json").read_text())
        if comparison["pid"] == os.getpid() or comparison["max_logit_delta"] <= 0:
            raise ValueError("fresh-process adapter effect verification failed")
        report["reload_comparison"] = comparison
        write_json(work / "training_report.json", report)
        update(
            status="succeeded",
            elapsed_seconds=time.time() - started,
            max_parameter_update=max_update,
            reload_pid=comparison["pid"],
        )
        return {"status": status, "manifest": manifest, "report": report}
    except BaseException as exc:
        memory = {}
        if torch is not None and spec.device == "cuda" and torch.cuda.is_available():
            memory = {
                "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
                "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved(),
            }
        update(
            status="cancelled" if is_cancelled() else "failed",
            error=f"{type(exc).__name__}: {exc}",
            **memory,
        )
        raise
    finally:
        for saved_signum, previous in old_handlers.items():
            signal.signal(saved_signum, previous)


def verify_artifact(work: Path) -> tuple[TrainingSpec, dict[str, Any]]:
    spec = TrainingSpec.model_validate_json((work / "training_spec.json").read_text())
    manifest = json.loads((work / "manifest.json").read_text())
    if not {"adapter/adapter_config.json", "adapter/adapter_model.safetensors"}.issubset(
        manifest.get("files", {})
    ):
        raise ValueError("adapter manifest missing required artifact hashes")
    for filename, digest in manifest["files"].items():
        relative = Path(filename)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or (work / relative).is_symlink()
            or sha256_file(work / relative) != digest
        ):
            raise ValueError("adapter file hash mismatch or invalid path")
    for field in (
        "persona_id",
        "relationship_id",
        "dataset_hash",
        "base_model_id",
        "base_model_revision",
        "tokenizer_revision",
        "chat_template_hash",
        "code_version",
    ):
        if manifest[field] != getattr(spec, field):
            raise ValueError(f"adapter manifest/spec mismatch: {field}")
    if manifest.get("training_code_hash") != spec.code_version.removeprefix("source:"):
        raise ValueError("adapter manifest/spec training code fingerprint mismatch")
    return spec, manifest


def compare(work: Path) -> dict[str, Any]:
    spec, _manifest = verify_artifact(work)
    _require_code_version(spec)
    torch, base, tokenizer = load_base(spec)
    _, _, peft_model, _, _, _ = _imports()
    model = peft_model.from_pretrained(base, work / "adapter", is_trainable=False)
    model.eval()
    messages = json.loads((work / "reload_prompt.json").read_text())
    tokens = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
    inputs = torch.tensor([tokens], device=spec.device)
    with torch.inference_mode():
        with model.disable_adapter():
            base_logits = model(input_ids=inputs).logits[:, -1, :].float().cpu()
            base_output = model.generate(
                input_ids=inputs,
                max_new_tokens=16,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
            )
        adapter_logits = model(input_ids=inputs).logits[:, -1, :].float().cpu()
        adapter_output = model.generate(
            input_ids=inputs,
            max_new_tokens=16,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
        )
    result = {
        "pid": os.getpid(),
        "max_logit_delta": float((base_logits - adapter_logits).abs().max()),
        "base_output": tokenizer.decode(base_output[0, len(tokens) :], skip_special_tokens=True),
        "adapter_output": tokenizer.decode(
            adapter_output[0, len(tokens) :], skip_special_tokens=True
        ),
        "prompt_source": "training example; reload smoke only, not held-out quality evaluation",
    }
    write_json(work / "reload_comparison.json", result)
    return result


def check_qwen_tokenizer() -> dict[str, Any]:
    """Download only the fixed public tokenizer; test target masking without model weights."""
    _, _, _, _, _, auto_tokenizer = _imports()
    tokenizer = auto_tokenizer.from_pretrained(
        "Qwen/Qwen3-4B-Instruct-2507", revision=QWEN_REVISION, trust_remote_code=False
    )
    if hashlib.sha256(tokenizer.chat_template.encode()).hexdigest() != QWEN_TEMPLATE_HASH:
        raise ValueError("reference Qwen chat template hash mismatch")
    messages = [
        {"role": "system", "content": "以下是虚构测试。"},
        {"role": "user", "content": "周末喝茶吗？"},
        {"role": "assistant", "content": "好呀，下午见。"},
        {"role": "user", "content": "好呀，下午见。"},
        {"role": "assistant", "content": "好呀，下午见。"},
    ]
    row = encode_target(tokenizer, {"messages": messages, "target_index": 4}, 512)
    masked = sum(label == -100 for label in row["labels"])
    return {
        "model": "Qwen/Qwen3-4B-Instruct-2507",
        "revision": QWEN_REVISION,
        "template_hash_verified": True,
        "total_tokens": len(row["input_ids"]),
        "masked_context_tokens": masked,
        "target_tokens": len(row["input_ids"]) - masked,
        "weights_downloaded": False,
    }


def main() -> None:
    environment = worker_environment()
    os.environ.clear()
    os.environ.update(environment)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    training = sub.add_parser("train")
    training.add_argument("--spec", type=Path, required=True)
    comparison = sub.add_parser("compare")
    comparison.add_argument("--artifact", type=Path, required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--dataset", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--spec", type=Path, required=True)
    prepare.add_argument("--profile", choices=("reference", "rtx4090-dry-run"), default="reference")
    sub.add_parser("tokenizer-check")
    args = parser.parse_args()
    if args.command == "train":
        result = train(TrainingSpec.model_validate_json(args.spec.read_text()))
    elif args.command == "prepare":
        spec = prepare_spec(args.dataset, args.output, profile=args.profile)
        write_json(args.spec, spec.model_dump(mode="json"))
        result = {"spec": str(args.spec), "status": "prepared", "hardware": "UNVERIFIED"}
    elif args.command == "tokenizer-check":
        result = check_qwen_tokenizer()
    else:
        result = compare(args.artifact.resolve())
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
