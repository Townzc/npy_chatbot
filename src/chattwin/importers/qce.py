"""Independent QCE JSON reader, based on the public v6.3.2 data contract.

No upstream implementation is bundled. The exporter core writes metadata version
0.1.0, which is not proof of the installed QCE application release.
"""

import json
from pathlib import Path
from typing import Iterator, Literal

from chattwin.domain import Content, DomainError, Message, Source

from .parsers import VERSION, digest, parse_time

COMPATIBILITY = {
    "reference_release": "v6.3.2",
    "exporter_schema_version": "0.1.0",
    "actual_release_verified": False,
    "real_export_validated": False,
    "mode": "single_json",
}


def records(path: Path) -> Iterator[tuple[int, dict, dict, None]]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict):
        raise DomainError("QCE_HEADER", "QCE JSON must be an object", 422)
    metadata = document.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("name") != "QQChatExporter":
        raise DomainError("QCE_HEADER", "QQChatExporter metadata required", 422)
    if metadata.get("version") != "0.1.0":
        raise DomainError(
            "FORMAT_VERSION", "Only the QCE exporter-core 0.1.0 schema is supported", 422
        )
    if "chunked" in document:
        raise DomainError(
            "QCE_CHUNKED", "Export one JSON file; chunk manifests are not supported", 422
        )
    chat = document.get("chatInfo")
    rows = document.get("messages")
    if not isinstance(chat, dict) or not isinstance(rows, list):
        raise DomainError("QCE_HEADER", "QCE chatInfo object and messages array required", 422)
    if chat.get("type") not in {"private", "group", "temp"}:
        raise DomainError("QCE_HEADER", "Unknown QCE conversation type", 422)
    statistics = document.get("statistics")
    count = statistics.get("totalMessages") if isinstance(statistics, dict) else None
    if isinstance(count, bool) or not isinstance(count, int) or count != len(rows):
        raise DomainError(
            "QCE_COUNT", "QCE statistics.totalMessages differs from messages length", 422
        )
    for number, row in enumerate(rows, 1):
        yield number, row, chat, None


def stable_id(value) -> str | None:
    if value is None or value == "" or value == "0":
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("stable IDs must be nonempty strings")
    return value


def normalize(record: dict, chat: dict, number: int, sha: str, mapping: dict) -> Message:
    from .parsers import MAX_LINE_BYTES

    if (
        not isinstance(record, dict)
        or len(json.dumps(record, ensure_ascii=False).encode()) > MAX_LINE_BYTES
    ):
        raise ValueError("QCE message must be an object within the record size limit")
    sender = record["sender"]
    source_id = stable_id(record["id"])
    if not isinstance(sender, dict) or not source_id:
        raise ValueError("QCE sender and message ID required")
    sender_uid, sender_uin = stable_id(sender.get("uid")), stable_id(sender.get("uin"))
    system, recalled = record.get("system", False), record.get("recalled", False)
    if not isinstance(system, bool) or not isinstance(recalled, bool):
        raise ValueError("QCE system/recalled flags must be boolean")
    sender_id = sender_uid or sender_uin
    if not sender_id:
        if not system:
            raise ValueError("QCE message has no stable sender ID")
        sender_id = "qce:platform-system"
    stamp = record["timestamp"]
    if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp < 100_000_000_000:
        raise ValueError("QCE requires a millisecond timestamp")
    occurred = parse_time(stamp, unit="milliseconds")
    account = str(mapping.get("source_account_id", "unconfirmed"))
    kind = chat["type"] if chat["type"] != "temp" else "unknown"
    peer_uid, peer_uin = stable_id(chat.get("peerUid")), stable_id(chat.get("peerUin"))
    conversation = ("uid:" + peer_uid) if peer_uid else ("uin:" + peer_uin) if peer_uin else None
    conversation = conversation or stable_id(mapping.get("qce_conversation_id"))
    if kind == "private" and not conversation:
        raise ValueError(
            "QCE private chat requires a peer ID or an explicit qce_conversation_id mapping"
        )
    conversation = conversation or "file:" + sha
    if kind == "private" and not system:
        self_uid, self_uin = stable_id(chat.get("selfUid")), stable_id(chat.get("selfUin"))
        if sender_uid and self_uid and peer_uid and sender_uid not in {self_uid, peer_uid}:
            raise ValueError("sender UID is outside the declared private conversation")
        if (
            not sender_uid
            and sender_uin
            and self_uin
            and peer_uin
            and sender_uin not in {self_uin, peer_uin}
        ):
            raise ValueError("sender UIN is outside the declared private conversation")

    raw = record["content"]
    if not isinstance(raw, dict):
        raise ValueError("QCE content must be an object")
    fallback_text = raw.get("text", "")
    elements, resources = raw.get("elements", []), raw.get("resources", [])
    if (
        not isinstance(fallback_text, str)
        or not isinstance(elements, list)
        or not isinstance(resources, list)
    ):
        raise ValueError("invalid QCE content fields")
    text_parts, replies, unsupported = [], [], []
    for element in elements:
        if not isinstance(element, dict) or not isinstance(element.get("type"), str):
            raise ValueError("invalid QCE element")
        element_type = element["type"]
        data = element.get("data")
        if element_type == "text":
            value = data.get("text") if isinstance(data, dict) else None
            if not isinstance(value, str):
                raise ValueError("QCE text element requires data.text")
            text_parts.append(value)
        elif element_type == "reply":
            if not isinstance(data, dict):
                raise ValueError("invalid QCE reply")
            reference = stable_id(data.get("referencedMessageId")) or stable_id(
                data.get("messageId")
            )
            if reference:
                replies.append(reference)
            else:
                unsupported.append("unresolved_reply_element")
        else:
            unsupported.append(element_type)
    if len(set(replies)) > 1:
        raise ValueError("QCE message contains conflicting reply IDs")
    for resource in resources:
        if not isinstance(resource, dict) or not isinstance(resource.get("type"), str):
            raise ValueError("invalid QCE resource")
        unsupported.append(resource["type"])
    # Quoted text, HTML, JSON cards and forwarded authors never become owner text.
    text = "".join(text_parts) if text_parts else fallback_text
    if len(text) > 100_000:
        raise ValueError("message text exceeds 100000 characters")
    content_type = (
        "system"
        if system
        else "recalled"
        if recalled
        else "unsupported"
        if unsupported or not text_parts
        else "text"
    )
    origin: Literal["platform_system", "unknown", "mode_notice"] = (
        "platform_system" if system else "unknown"
    )
    if content_type == "text" and text in {"对方已切换为ai模式", "本人已接管"}:
        origin = "mode_notice"
        content_type = "mode_notice"
    return Message(
        source=Source(
            platform="qq",
            importer="qce",
            importer_version=VERSION,
            source_account_id=account,
            source_message_id=source_id,
            import_batch_id=mapping.get("batch_id", "preview"),
            file_sha256=sha,
            record_index=number,
        ),
        conversation_id="conv-" + digest(["qq", account, kind, conversation])[:24],
        sender_id=sender_id,
        origin=origin,
        occurred_at=occurred,
        sequence=number,
        content=Content(
            type=content_type,
            text=text or None,
            reply_to=replies[0] if replies else None,
            unsupported_type=record.get("type", "unknown") if content_type != "text" else None,
            attachments=[
                {"source_type": value, "status": "not_loaded"} for value in sorted(set(unsupported))
            ],
        ),
        provenance={
            "conversation_kind": kind,
            "display_name": sender.get("name") or sender_id,
            "exporter_id": chat.get("selfUid") or chat.get("selfUin"),
            "qce_sender_uid": sender.get("uid"),
            "qce_sender_uin": sender.get("uin"),
            "qce_sequence": record.get("seq"),
            "raw_time": stamp,
            "parsed_timezone": "UTC",
            "qce_compatibility": COMPATIBILITY,
            "recalled": recalled,
            "unknown_fields": sorted(
                set(record)
                - {
                    "id",
                    "seq",
                    "timestamp",
                    "time",
                    "sender",
                    "type",
                    "content",
                    "system",
                    "recalled",
                    "rawMessage",
                }
            ),
            "warnings": (["unresolved_reply"] if replies else [])
            + (["file_scoped_conversation"] if conversation.startswith("file:") else []),
        },
    )
