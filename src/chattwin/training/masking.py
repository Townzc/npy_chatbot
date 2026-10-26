"""Only the current assistant target gets loss; token-prefix proof or rejection."""

from __future__ import annotations

from typing import Any


def encode_target(tokenizer: Any, example: dict[str, Any], max_length: int) -> dict[str, list[int]]:
    messages = example.get("messages", [])
    target_index = example.get("target_index", len(messages) - 1)
    if (
        len(messages) < 2
        or target_index != len(messages) - 1
        or messages[-1].get("role") != "assistant"
        or not messages[-1].get("content", "").strip()
    ):
        raise ValueError("a nonempty final assistant target and preceding context are required")
    if any(
        m.get("role") not in {"system", "user", "assistant"}
        or not isinstance(m.get("content"), str)
        for m in messages
    ):
        raise ValueError("unsupported message role/content")
    prefix = tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True)
    tokens = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False)
    # The assistant header is part of prefix. Never find the target by text matching.
    if not prefix or tokens[: len(prefix)] != prefix:
        raise ValueError("chat template cannot prove the target token boundary")
    if len(tokens) <= len(prefix):
        raise ValueError("zero target tokens")
    if len(tokens) > max_length:
        raise ValueError("target would be truncated; sample skipped")
    return {
        "input_ids": tokens,
        "attention_mask": [1] * len(tokens),
        "labels": [-100] * len(prefix) + tokens[len(prefix) :],
    }


def pad_batch(rows: list[dict[str, list[int]]], pad_token_id: int) -> dict[str, list[list[int]]]:
    width = max(len(row["input_ids"]) for row in rows)
    return {
        key: [row[key] + [fill] * (width - len(row[key])) for row in rows]
        for key, fill in (("input_ids", pad_token_id), ("attention_mask", 0), ("labels", -100))
    }
