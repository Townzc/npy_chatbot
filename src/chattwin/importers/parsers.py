"""Independent readers; never fetch attachments, extract archives or run code."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from chattwin.domain import Content, DomainError, Message, Source, uid

from .probe import reject_unsupported_container

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
VERSION = "0.1.0"
CSV_DEFAULT = {
    "sender": "sender_id",
    "time": "occurred_at",
    "text": "text",
    "conversation": "conversation",
    "message_id": "message_id",
    "name": "sender_name",
}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def validate_path(path: Path) -> None:
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise DomainError("IMPORT_SIZE", "Expected a regular file no larger than 64 MiB", 422)


def detect(path: Path) -> str:
    validate_path(path)
    reject_unsupported_container(path)
    if path.suffix.lower() == ".csv":
        return "csv"
    try:
        with path.open(encoding="utf-8-sig") as handle:
            head = handle.read(MAX_LINE_BYTES)
    except UnicodeError:
        raise DomainError("INVALID_FILE", "聊天导出需要 UTF-8 编码", 422) from None
    first = next(
        (line for line in head.splitlines() if line.strip() and not line.lstrip().startswith("#")),
        "",
    )
    try:
        item = json.loads(first)
        if item.get("schema_version"):
            return "canonical"
        if item.get("_type") == "header":
            return "chatlab"
    except (ValueError, AttributeError):
        pass
    try:
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(obj, dict) and "chatlab" in obj:
            return "chatlab"
        if (
            isinstance(obj, dict)
            and isinstance(obj.get("metadata"), dict)
            and obj["metadata"].get("name") == "QQChatExporter"
        ):
            return "qce"
    except (ValueError, UnicodeError):
        pass
    raise DomainError(
        "UNSUPPORTED_FORMAT",
        "Supported: QCE exporter-core 0.1.0 single JSON, ChatLab v0.0.2 JSON/JSONL, canonical JSONL v1, CSV with mapping.",
        422,
    )


def parse_time(value: Any, timezone: str = "UTC", unit: str = "iso") -> datetime:
    if unit in {"seconds", "milliseconds"}:
        if isinstance(value, bool):
            raise ValueError("timestamp must be numeric")
        stamp = float(value)
        if unit == "seconds" and abs(stamp) >= 100_000_000_000:
            raise ValueError("expected seconds, received apparent milliseconds")
        return datetime.fromtimestamp(stamp / (1000 if unit == "milliseconds" else 1), UTC)
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        zone = ZoneInfo(timezone)
        early, late = result.replace(tzinfo=zone, fold=0), result.replace(tzinfo=zone, fold=1)
        if early.utcoffset() != late.utcoffset():
            raise ValueError("ambiguous or nonexistent local time; supply UTC offset")
        result = early
    return result.astimezone(UTC)


def _json_lines(path: Path) -> Iterator[tuple[int, Any, str | None]]:
    with path.open(encoding="utf-8-sig") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if len(line.encode()) > MAX_LINE_BYTES:
                yield number, None, "line exceeds 1 MiB"
                continue
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    raise ValueError("record must be an object")
                yield number, obj, None
            except (ValueError, RecursionError):
                yield number, None, "invalid JSON object"


def records(path: Path, fmt: str, mapping: dict) -> Iterator[tuple[int, dict, dict, str | None]]:
    """Yield record index, data, header metadata, sanitized error."""
    if fmt == "csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = CSV_DEFAULT | mapping.get("fields", {})
            missing = [
                fields[key]
                for key in ("sender", "time", "text", "conversation")
                if fields[key] not in (reader.fieldnames or [])
            ]
            if missing:
                raise DomainError("CSV_MAPPING", "Missing columns: " + ", ".join(missing), 422)
            for number, row in enumerate(reader, 2):
                yield (
                    number,
                    row,
                    {
                        "fields": fields,
                        "platform": mapping.get("platform", "unknown"),
                        "type": mapping.get("conversation_kind", "unknown"),
                    },
                    None,
                )
        return
    if fmt == "canonical":
        for number, obj, error in _json_lines(path):
            yield number, obj or {}, {}, error
        return
    if fmt == "qce":
        from .qce import records as qce_records

        yield from qce_records(path)
        return
    if fmt != "chatlab":
        raise DomainError("UNSUPPORTED_FORMAT", "Unknown importer format", 422)
    with path.open(encoding="utf-8-sig") as handle:
        first = next(
            (line for line in handle if line.strip() and not line.lstrip().startswith("#")), ""
        )
    try:
        header = json.loads(first)
        is_lines = isinstance(header, dict) and header.get("_type") == "header"
    except ValueError:
        is_lines = False
    if not is_lines:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        _check_header(document)
        header = {
            **document["meta"],
            "members": document.get("members", []),
            "exportedAt": document["chatlab"]["exportedAt"],
        }
        for number, item in enumerate(document["messages"], 1):
            yield number, item, header, None
        return
    metadata: dict = {}
    seen_message = False
    for number, item, error in _json_lines(path):
        if error:
            yield number, {}, metadata, error
            continue
        if not metadata:
            if item.get("_type") != "header":
                raise DomainError(
                    "CHATLAB_HEADER", "First ChatLab JSONL record must be header", 422
                )
            _check_header(item)
            metadata = {**item["meta"], "members": [], "exportedAt": item["chatlab"]["exportedAt"]}
        elif item.get("_type") == "member" and not seen_message:
            metadata["members"].append(item)
        elif item.get("_type") == "message":
            seen_message = True
            yield number, item, metadata, None
        else:
            yield number, {}, metadata, "unexpected row type or member after message"


def _check_header(document: dict) -> None:
    if document.get("chatlab", {}).get("version") != "0.0.2":
        raise DomainError("FORMAT_VERSION", "Only ChatLab v0.0.2 is supported", 422)
    meta = document.get("meta", {})
    if not meta.get("platform") or meta.get("type") not in {"private", "group"}:
        raise DomainError("CHATLAB_HEADER", "meta.platform and meta.type are required", 422)
    parse_time(document["chatlab"]["exportedAt"], unit="seconds")


def normalize(
    record: dict, metadata: dict, fmt: str, number: int, sha: str, mapping: dict
) -> Message:
    account = str(mapping.get("source_account_id", "unconfirmed"))
    if fmt == "qce":
        from .qce import normalize as normalize_qce

        return normalize_qce(record, metadata, number, sha, mapping)
    if fmt == "canonical":
        message = Message.model_validate(record)
        if (
            not mapping.get("_inspect")
            and account != "unconfirmed"
            and message.source.source_account_id != account
        ):
            raise ValueError("canonical source account differs from confirmed account")
        original_source = message.source.model_dump(mode="json")
        message.id = uid()
        message.source.file_sha256 = sha
        message.source.record_index = number
        message.source.import_batch_id = mapping.get("batch_id", "preview")
        message.provenance = {
            **message.provenance,
            "original_source": original_source,
            "conversation_kind": message.provenance.get(
                "conversation_kind",
                mapping.get("_manifest_conversations", {}).get(
                    message.conversation_id, mapping.get("conversation_kind", "unknown")
                ),
            ),
            "ignored_imported_use_context": message.use_context is not None,
        }
        message.use_context = None
        message.relationship_id = None
        return message
    if fmt == "csv":
        fields = metadata["fields"]
        sender = record[fields["sender"]]
        occurred = parse_time(
            record[fields["time"]], mapping.get("timezone", "UTC"), mapping.get("time_unit", "iso")
        )
        text = record[fields["text"]]
        source_id = record.get(fields["message_id"]) or None
        raw_conversation = record[fields["conversation"]]
        if not raw_conversation:
            raise ValueError("stable conversation ID required")
        conversation = "conv-" + digest([metadata["platform"], account, raw_conversation])[:24]
        content = Content(type="text", text=text or None)
        name = record.get(fields["name"], sender)
        extra = set(record) - set(fields.values())
    else:
        sender = record["sender"]
        if not isinstance(sender, str) or not sender:
            raise ValueError("sender must be stable nonempty string")
        occurred = parse_time(record["timestamp"], unit="seconds")
        kind, text = record["type"], record["content"]
        if (
            not isinstance(kind, int)
            or isinstance(kind, bool)
            or (text is not None and not isinstance(text, str))
        ):
            raise ValueError("invalid message type or content")
        source_id = record.get("platformMessageId")
        raw_conversation = metadata.get("groupId") or mapping.get("conversation_id") or sha
        conversation = "conv-" + digest([metadata["platform"], account, raw_conversation])[:24]
        content = Content(
            type="text" if kind in {0, 25} else "unsupported",
            text=text,
            reply_to=record.get("replyToMessageId"),
            unsupported_type=kind if kind not in {0, 25} else None,
        )
        if content.type != "text":
            content.attachments = [{"status": "missing", "source_type": kind}]
        name = record.get("accountName", sender)
        extra = set(record) - {
            "_type",
            "sender",
            "timestamp",
            "type",
            "content",
            "platformMessageId",
            "replyToMessageId",
            "accountName",
            "groupNickname",
        }
    if (
        not sender
        or not isinstance(sender, str)
        or (source_id is not None and not isinstance(source_id, str))
    ):
        raise ValueError("sender/message IDs must be strings")
    if text is not None and len(text) > 100_000:
        raise ValueError("message text exceeds 100000 characters")
    return Message(
        source=Source(
            platform=metadata["platform"],
            importer=fmt,
            importer_version=VERSION,
            source_account_id=account,
            source_message_id=source_id,
            import_batch_id=mapping.get("batch_id", "preview"),
            file_sha256=sha,
            record_index=number,
        ),
        conversation_id=conversation,
        sender_id=sender,
        occurred_at=occurred,
        sequence=number,
        content=content,
        provenance={
            "conversation_kind": metadata.get("type", "private"),
            "display_name": name,
            "exporter_id": metadata.get("ownerId"),
            "unknown_fields": sorted(extra),
            "parsed_timezone": mapping.get("timezone", "UTC"),
            "raw_time": record.get("timestamp")
            if fmt == "chatlab"
            else record[metadata["fields"]["time"]],
            "warnings": ["unresolved_reply"] if content.reply_to else [],
        },
    )


def parse(
    path: Path | str, format: str = "auto", mapping: dict | None = None
) -> Iterator[tuple[int, Message | None, str | None]]:
    path = Path(path)
    validate_path(path)
    if format != "auto":
        reject_unsupported_container(path)
    mapping = mapping or {}
    fmt = (
        detect(path)
        if format == "auto"
        else {"canonical_jsonl": "canonical", "csv_mapping": "csv"}.get(format, format)
    )
    from .manifests import prepare_manifest

    mapping, _ = prepare_manifest(path, fmt, mapping)
    sha = file_hash(path)
    try:
        for number, record, meta, error in records(path, fmt, mapping):
            if error:
                yield number, None, error
                continue
            try:
                yield number, normalize(record, meta, fmt, number, sha, mapping), None
            except (ValueError, KeyError, TypeError, OverflowError, AttributeError) as exc:
                yield number, None, "invalid record: " + type(exc).__name__
    except (
        UnicodeError,
        ValueError,
        RecursionError,
        csv.Error,
        KeyError,
        TypeError,
        AttributeError,
    ):
        raise DomainError(
            "INVALID_FILE",
            "File decoding/structure failed; UTF-8 and supported schema required",
            422,
        ) from None


def inspect(path: Path | str, format: str = "auto", mapping: dict | None = None) -> dict:
    path = Path(path)
    fmt = detect(path) if format == "auto" else format
    from .manifests import prepare_manifest

    mapping, manifest_validation = prepare_manifest(path, fmt, mapping or {})
    counts: Counter = Counter()
    senders: dict[str, dict] = {}
    dates: list[str] = []
    preview: list[dict] = []
    errors: list[dict] = []
    source_ids: set[tuple[str, str]] = set()
    references: list[tuple[str, str]] = []
    total = text_count = stable = 0
    for number, message, error in parse(path, fmt, {**(mapping or {}), "_inspect": True}):
        if error:
            errors.append({"record_index": number, "error": error})
            continue
        assert message is not None
        total += 1
        counts[message.content.type] += 1
        text_count += bool(message.content.type == "text" and message.content.text)
        stable += message.source.source_message_id is not None
        if message.source.source_message_id:
            source_ids.add((message.conversation_id, message.source.source_message_id))
        if message.content.reply_to:
            references.append((message.conversation_id, message.content.reply_to))
        dates.append(message.occurred_at.isoformat())
        sender_key = f"{message.source.source_account_id}:{message.sender_id}"
        if message.origin != "platform_system":
            senders[sender_key] = {
                "id": message.sender_id,
                "name": message.provenance.get("display_name", message.sender_id),
                "source_account_id": message.source.source_account_id,
            }
        if len(preview) < 20:
            preview.append(message.model_dump(mode="json"))
    result = {
        "filename": path.name,
        "file_sha256": file_hash(path),
        "format": fmt,
        "importer_version": VERSION,
        "total": total,
        "types": dict(counts),
        "valid_text": text_count,
        "candidate_training_targets": 0,
        "errors": errors,
        "bad_rows": len(errors),
        "senders": list(senders.values()),
        "preview": preview,
        "start": min(dates, default=None),
        "end": max(dates, default=None),
        "stable_id_coverage": stable / total if total else 0,
        "unresolved_references": sum(ref not in source_ids for ref in references),
        "history_completeness": "unknown; parsed records do not prove complete chat history",
        "identity_confirmed": False,
        "manifest_validation": manifest_validation,
    }
    if fmt == "qce":
        from .qce import COMPATIBILITY

        result["format_compatibility"] = dict(COMPATIBILITY)
    return result
