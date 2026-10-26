"""Offline tiny Qwen3 + real LoRA updates. This is not Qwen 4B or quality acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from .spec import TrainingSpec, canonical_hash, local_model_hash, private_output, sha256_file
from .worker import train, write_json


def create_smoke_spec(root: Path) -> TrainingSpec:
    import torch
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import PreTrainedTokenizerFast, Qwen3Config, Qwen3ForCausalLM

    root = private_output(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    model_dir, dataset = root / "base", root / "dataset"
    model_dir.mkdir()
    dataset.mkdir()
    vocabulary = [
        "<unk>",
        "<pad>",
        "<eos>",
        "<user>",
        "<assistant>",
        "<system>",
        "hello",
        "hi",
        "tea",
        "yes",
        "please",
        "thanks",
        "welcome",
        "friend",
        "good",
        "morning",
        "evening",
        "synthetic",
        "only",
        ".",
    ]
    raw = Tokenizer(WordLevel({word: i for i, word in enumerate(vocabulary)}, unk_token="<unk>"))
    raw.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=raw,
        unk_token="<unk>",
        pad_token="<pad>",
        eos_token="<eos>",
        additional_special_tokens=["<user>", "<assistant>", "<system>"],
    )
    tokenizer.chat_template = "{% for message in messages %}{{ '<' + message['role'] + '>' + ' ' + message['content'] + ' <eos> ' }}{% endfor %}{% if add_generation_prompt %}{{ '<assistant> ' }}{% endif %}"
    tokenizer.save_pretrained(model_dir)
    torch.manual_seed(7)
    model = Qwen3ForCausalLM(
        Qwen3Config(
            vocab_size=len(tokenizer),
            hidden_size=32,
            intermediate_size=64,
            num_hidden_layers=1,
            num_attention_heads=4,
            num_key_value_heads=2,
            head_dim=8,
            max_position_embeddings=128,
            pad_token_id=tokenizer.pad_token_id,
            bos_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
            tie_word_embeddings=True,
        )
    )
    model.save_pretrained(model_dir, safe_serialization=True)
    files, assignments, source_ids, counts = {}, {}, [], {}
    for split, pairs in (
        ("train", [("hello friend", "hi friend"), ("tea please", "yes tea")]),
        ("validation", [("good morning", "good morning")]),
        ("test", [("thanks", "welcome")]),
    ):
        rows = []
        for index, (user, target) in enumerate(pairs):
            segment = f"synthetic-{split}-{index}"
            ids = [segment + "-user", segment + "-owner"]
            rows.append(
                {
                    "id": segment,
                    "segment_id": segment,
                    "messages": [
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": target},
                    ],
                    "source_message_ids": ids,
                    "target_message_ids": [ids[-1]],
                    "target_index": 1,
                }
            )
            assignments[segment] = split
            source_ids.extend(ids)
        file = dataset / (split + ".jsonl")
        file.write_text("".join(json.dumps(row) + "\n" for row in rows))
        files[file.name] = sha256_file(file)
        counts[split] = len(rows)
    manifest: dict[str, Any] = {
        "id": "synthetic-tiny-v1",
        "schema_version": "1.0",
        "persona_id": "synthetic-persona",
        "relationship_id": "synthetic-relationship",
        "identity_mapping_version": 1,
        "files": files,
        "counts": counts,
        "split_assignments": assignments,
        "source_message_ids": source_ids,
        "synthetic": True,
    }
    manifest["dataset_hash"] = canonical_hash(manifest)
    write_json(dataset / "manifest.json", manifest)
    revision = "local:" + local_model_hash(model_dir)
    spec = TrainingSpec(
        dataset_path=dataset,
        dataset_version=manifest["id"],
        dataset_hash=manifest["dataset_hash"],
        persona_id=manifest["persona_id"],
        relationship_id=manifest["relationship_id"],
        base_model_id=str(model_dir),
        base_model_revision=revision,
        tokenizer_revision=revision,
        chat_template_hash=hashlib.sha256(tokenizer.chat_template.encode()).hexdigest(),
        precision="float32",
        device="cpu",
        rank=2,
        alpha=4,
        dropout=0,
        max_sequence_length=64,
        batch_size=2,
        gradient_accumulation=1,
        learning_rate=0.02,
        epochs=8,
        max_steps=8,
        output_path=root / "job",
        dependency_lock_hash=sha256_file(Path(__file__).resolve().parents[3] / "training/uv.lock"),
        synthetic_smoke=True,
        local_files_only=True,
    )
    write_json(root / "spec.json", spec.model_dump(mode="json"))
    return spec


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.output or Path(tempfile.mkdtemp(prefix="chattwin-tiny-smoke-"))
    result = train(create_smoke_spec(root))
    print(
        json.dumps(
            {"output": str(root), "status": result["status"], "report": result["report"]},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
