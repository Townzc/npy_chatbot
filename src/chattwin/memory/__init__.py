"""Confirmed relation memory; scope filtering always precedes relevance ranking."""

from datetime import datetime

from chattwin.datasets import forbidden_sources
from chattwin.domain import DomainError, now, uid
from chattwin.storage import memories


def add_memory(service, persona_id, relationship_id, text, source_message_ids, confirmed=False):
    service.require_scope(persona_id, relationship_id)
    scoped = {
        message["id"]: message
        for message in service.list_messages(persona_id, relationship_id, limit=None)
    }
    if not text.strip() or not source_message_ids or not set(source_message_ids).issubset(scoped):
        raise DomainError(
            "MEMORY_SOURCES", "Nonempty text and source IDs in this relationship are required", 422
        )
    if any(
        scoped[id]["origin"] in {"ai", "mode_notice", "platform_system"}
        or scoped[id]["content"]["type"] != "text"
        for id in source_message_ids
    ):
        raise DomainError(
            "MEMORY_SOURCES",
            "AI, notifications and unsupported media cannot become factual memory",
            422,
        )
    payload = {
        "id": uid(),
        "persona_id": persona_id,
        "relationship_id": relationship_id,
        "text": text,
        "source_message_ids": list(dict.fromkeys(source_message_ids)),
        "confirmed": confirmed,
        "deleted": False,
        "version": 1,
        "created_at": now().isoformat(),
        "source_time": max(scoped[id]["occurred_at"] for id in source_message_ids),
        "expires_at": None,
    }
    with service.store.transaction() as conn:
        conn.execute(
            memories.insert().values(
                id=payload["id"],
                persona_id=persona_id,
                relationship_id=relationship_id,
                payload=payload,
            )
        )
    return payload


def update_memory(
    service, id, persona_id, relationship_id, text=None, confirmed=None, deleted=False
):
    service.require_scope(persona_id, relationship_id)
    rows = service.store.rows(
        memories,
        memories.c.id == id,
        memories.c.persona_id == persona_id,
        memories.c.relationship_id == relationship_id,
    )
    if not rows:
        raise DomainError("MEMORY_NOT_FOUND", "Memory not found in this relationship", 404)
    payload = rows[0]["payload"]
    if text is not None:
        if not text.strip():
            raise DomainError("MEMORY_TEXT", "Memory text cannot be empty", 422)
        payload["text"] = text
        payload["confirmed"] = False
    if confirmed is not None:
        payload["confirmed"] = confirmed
    payload["deleted"] = deleted
    payload["version"] += 1
    payload["updated_at"] = now().isoformat()
    with service.store.transaction() as conn:
        conn.execute(memories.update().where(memories.c.id == id).values(payload=payload))
    return payload


def retrieve_memories(service, persona_id, relationship_id, query, before: datetime | None = None):
    service.require_scope(persona_id, relationship_id)
    excluded = forbidden_sources(service, persona_id, relationship_id)
    cutoff = before or now()
    result = []
    for row in service.store.rows(
        memories, memories.c.persona_id == persona_id, memories.c.relationship_id == relationship_id
    ):
        item = row["payload"]
        if not item["confirmed"] or item["deleted"] or set(item["source_message_ids"]) & excluded:
            continue
        if datetime.fromisoformat(item["source_time"]) >= cutoff:
            continue
        if item.get("expires_at") and datetime.fromisoformat(item["expires_at"]) <= cutoff:
            continue
        score = len(set(query.casefold()) & set(item["text"].casefold()))
        if score or not query:
            result.append((score, item))
    return [item for _, item in sorted(result, key=lambda pair: pair[0], reverse=True)[:8]]
