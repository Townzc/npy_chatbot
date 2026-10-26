"""Immutable relationship datasets. Split complete segments before windows."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from difflib import SequenceMatcher

from chattwin.domain import DomainError, now, uid
from chattwin.importers.guards import source_guard
from chattwin.importers.parsers import digest, file_hash
from chattwin.storage import datasets


def forbidden_sources(service, persona_id: str, relationship_id: str) -> set[str]:
    """All frozen held-out sources stay unavailable to style/memory retrieval."""
    excluded = set()
    for row in service.store.rows(
        datasets, datasets.c.persona_id == persona_id, datasets.c.relationship_id == relationship_id
    ):
        for segment in row["payload"].get("segments", []):
            if segment["split"] != "train":
                excluded.update(segment["source_message_ids"])
    return excluded


def _redact(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", text)
    return re.sub(r"(?<!\d)(?:\+?\d[\d -]{8,}\d)(?!\d)", "[NUMBER]", text)


@source_guard
def build_dataset(
    service, persona_id: str, relationship_id: str, gap_seconds: int = 1800, redact: bool = True
) -> dict:
    service.require_scope(persona_id, relationship_id)
    if gap_seconds < 1:
        raise DomainError("DATASET_CONFIG", "gap_seconds must be positive", 422)
    persona = service._persona(persona_id)
    source = service.list_messages(persona_id, relationship_id, limit=None)
    segments: list[list[dict]] = []
    by_conversation: dict[str, list[dict]] = {}
    for message in source:
        by_conversation.setdefault(message["conversation_id"], []).append(message)
    for conversation in by_conversation.values():
        current: list[dict] = []
        for message in conversation:
            if (
                current
                and (
                    datetime.fromisoformat(message["occurred_at"])
                    - datetime.fromisoformat(current[-1]["occurred_at"])
                ).total_seconds()
                > gap_seconds
            ):
                segments.append(current)
                current = []
            current.append(message)
        if current:
            segments.append(current)
    segments.sort(key=lambda segment: segment[0]["occurred_at"])
    if not segments:
        raise DomainError("DATASET_EMPTY", "No scoped records are available", 422)
    # Connected components keep cross-gap replies and near-duplicate segments together.
    parents = list(range(len(segments)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left, right):
        parents[root(right)] = root(left)

    normalized = [
        re.sub(
            r"[\W_]+",
            "",
            " ".join(
                f"{item['use_context']['sender_role']}:{item['content'].get('text') or ''}"
                for item in segment
            ),
        ).casefold()
        for segment in segments
    ]
    lookup = {}
    for index, segment in enumerate(segments):
        for message in segment:
            if message["source"]["source_message_id"]:
                lookup[(message["conversation_id"], message["source"]["source_message_id"])] = index
    for index, segment in enumerate(segments):
        for message in segment:
            reply = lookup.get((message["conversation_id"], message["content"].get("reply_to")))
            if reply is not None:
                union(index, reply)
        for other in range(index):
            a, b = normalized[index], normalized[other]
            if (
                a
                and b
                and min(len(a), len(b)) / max(len(a), len(b)) >= 0.9
                and SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.9
            ):
                union(index, other)
    clusters: dict[int, list[int]] = {}
    for index in range(len(segments)):
        clusters.setdefault(root(index), []).append(index)
    groups = sorted(
        clusters.values(),
        key=lambda group: max(segments[index][-1]["occurred_at"] for index in group),
    )
    assignments: dict[int, str] = {}
    confidence = (
        "low: fewer than five independent segments; train only, no valid held-out evaluation"
    )
    if len(groups) < 5:
        for group in groups:
            for index in group:
                assignments[index] = "train"
    else:
        # Hold one cluster out at each split boundary as an embargo.
        train_count = max(1, int((len(groups) - 2) * 0.8))
        validation_count = max(1, len(groups) - train_count - 3)
        labels = (
            ["train"] * train_count + ["embargo"] + ["validation"] * validation_count + ["embargo"]
        )
        labels += ["test"] * (len(groups) - len(labels))
        for group, split in zip(groups, labels, strict=True):
            for index in group:
                assignments[index] = split
        confidence = (
            "synthetic/engineering split only; quality requires independent human evaluation"
        )
    # Never promote a frozen held-out source into training when new history arrives.
    old_excluded = forbidden_sources(service, persona_id, relationship_id)
    for group in groups:
        if any(message["id"] in old_excluded for index in group for message in segments[index]):
            for index in group:
                if assignments[index] == "train":
                    assignments[index] = "embargo"
    # Reply/duplicate clusters may span time boundaries. Embargo every cluster that
    # contains a message at or after the earliest held-out event; no future training.
    held_times = [
        message["occurred_at"]
        for index, segment in enumerate(segments)
        if assignments[index] in {"validation", "test"}
        for message in segment
    ]
    if held_times:
        cutoff = min(held_times)
        for group in groups:
            if any(
                message["occurred_at"] >= cutoff for index in group for message in segments[index]
            ):
                for index in group:
                    if assignments[index] == "train":
                        assignments[index] = "embargo"
    examples: dict[str, list[dict]] = {"train": [], "validation": [], "test": []}
    segment_records = []
    target_count = skipped = 0
    seen_normalized = set()
    for index, segment in enumerate(segments):
        split = assignments[index]
        segment_id = digest([message["id"] for message in segment])
        segment_records.append(
            {
                "id": segment_id,
                "split": split,
                "source_message_ids": [message["id"] for message in segment],
                "start": segment[0]["occurred_at"],
                "end": segment[-1]["occurred_at"],
            }
        )
        if split == "embargo" or normalized[index] in seen_normalized:
            skipped += 1
            continue
        seen_normalized.add(normalized[index])
        context: list[dict] = []
        context_ids: list[list[str]] = []
        cursor = 0
        while cursor < len(segment):
            message = segment[cursor]
            policy = message["use_context"]["use_policy"]
            text = message["content"].get("text")
            usable = (
                policy["context"]
                and message["content"]["type"] == "text"
                and text
                and message["origin"] not in {"ai", "mode_notice", "platform_system"}
                and text not in {"对方已切换为ai模式", "本人已接管"}
            )
            if not usable:
                cursor += 1
                continue
            owner = message["use_context"]["sender_role"] == "owner"
            role = "assistant" if owner else "user"
            target = (
                owner
                and policy["training_target"]
                and message["origin"] == "human"
                and message["provenance"].get("human_origin_confirmed")
            )
            target_ids = [message["id"]]
            text = _redact(text) if redact else text
            cursor += 1
            # Preserve bursts as a single current owner target.
            while target and cursor < len(segment):
                nxt = segment[cursor]
                if not (
                    nxt["use_context"]["sender_role"] == "owner"
                    and nxt["use_context"]["use_policy"]["training_target"]
                    and nxt["origin"] == "human"
                    and nxt["provenance"].get("human_origin_confirmed")
                    and nxt["content"]["type"] == "text"
                    and nxt["content"].get("text")
                    and nxt["content"]["text"] not in {"对方已切换为ai模式", "本人已接管"}
                ):
                    break
                text += "\n" + (
                    _redact(nxt["content"]["text"]) if redact else nxt["content"]["text"]
                )
                target_ids.append(nxt["id"])
                cursor += 1
            turn = {"role": role, "content": text}
            if target and context and any(item["role"] == "user" for item in context):
                turns = context[-12:] + [turn]
                # Sources include all retained context and target; no row-random split.
                examples[split].append(
                    {
                        "id": uid(),
                        "segment_id": segment_id,
                        "messages": turns,
                        "source_message_ids": [value for ids in context_ids[-12:] for value in ids]
                        + target_ids,
                        "target_message_ids": target_ids,
                        "target_index": len(turns) - 1,
                    }
                )
                target_count += 1
            context.append(turn)
            context_ids.append(target_ids)
    if not examples["train"]:
        raise DomainError(
            "NO_TRAINING_TARGETS",
            "Confirm human origin of selected owner messages and provide preceding partner context",
            422,
        )
    dataset_id = uid()
    parent = service.store.root / "datasets"
    parent.mkdir(exist_ok=True, mode=0o700)
    staging, destination = parent / ("." + dataset_id + ".tmp"), parent / dataset_id
    staging.mkdir(mode=0o700)
    try:
        for split, rows in examples.items():
            path = staging / f"{split}.jsonl"
            path.write_text(
                "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
                encoding="utf-8",
            )
            path.chmod(0o600)
        try:
            commit = (
                subprocess.run(
                    ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
                ).stdout.strip()
                or "uncommitted"
            )
        except (OSError, subprocess.TimeoutExpired):
            commit = "unavailable"
        manifest = {
            "id": dataset_id,
            "schema_version": "1.0",
            "persona_id": persona_id,
            "relationship_id": relationship_id,
            "identity_mapping_version": persona["identity_mapping_version"],
            "created_at": now().isoformat(),
            "files": {
                f"{split}.jsonl": file_hash(staging / f"{split}.jsonl") for split in examples
            },
            "counts": {split: len(rows) for split, rows in examples.items()},
            "segments": segment_records,
            "split_assignments": {segment["id"]: segment["split"] for segment in segment_records},
            "source_message_ids": [message["id"] for message in source],
            "source_batch_ids": sorted(
                {message["source"]["import_batch_id"] for message in source}
            ),
            "redaction": {
                "enabled": redact,
                "rules": "email and long numeric identifiers; manual review still required",
            },
            "split_policy": {
                "method": "chronological complete segment clusters",
                "gap_seconds": gap_seconds,
                "boundary_embargo_clusters": 1,
                "near_duplicate_ratio": 0.9,
            },
            "template_version": "role-content-v1; tokenize only with pinned worker template",
            "code_commit": commit,
            "confidence": confidence,
            "skipped_duplicate_or_embargo_segments": skipped,
        }
        manifest["dataset_hash"] = digest(manifest)
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (staging / "manifest.json").chmod(0o600)
        staging.rename(destination)
        with service.store.transaction() as conn:
            conn.execute(
                datasets.insert().values(
                    id=dataset_id,
                    persona_id=persona_id,
                    relationship_id=relationship_id,
                    payload=manifest,
                )
            )
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return {**manifest, "path": str(destination)}
