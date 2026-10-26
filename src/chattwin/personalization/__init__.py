"""Draft statistics and separately approved, immutable style guidance versions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from chattwin.datasets import forbidden_sources
from chattwin.domain import DomainError, now, uid
from chattwin.importers.guards import source_guard
from chattwin.storage import styles


def _eligible(service, persona_id, relationship_id, before=None):
    excluded = forbidden_sources(service, persona_id, relationship_id)
    return [
        message
        for message in service.list_messages(persona_id, relationship_id, limit=None, before=before)
        if message["id"] not in excluded
        and message["use_context"]["use_policy"]["style"]
        and message["origin"] == "human"
        and message["content"]["type"] == "text"
        and message["content"].get("text")
        and message["content"]["text"] not in {"对方已切换为ai模式", "本人已接管"}
    ]


def build_style(
    service, persona_id: str, relationship_id: str, before: datetime | None = None
) -> dict:
    """Read-only draft statistics. A chat request never creates approved guidance."""
    messages = _eligible(service, persona_id, relationship_id, before)
    return {
        "persona_id": persona_id,
        "relationship_id": relationship_id,
        "status": "draft",
        "source_message_ids": [message["id"] for message in messages],
        "count": len(messages),
        "mean_length": round(
            sum(len(message["content"]["text"]) for message in messages) / len(messages), 2
        )
        if messages
        else 0,
        "examples": [
            {"message_id": message["id"], "text": message["content"]["text"]}
            for message in messages[:20]
        ],
        "rules": "",
        "before": before.isoformat() if before else None,
    }


def get_approved_style(service, persona_id, relationship_id, before=None):
    service.require_scope(persona_id, relationship_id)
    allowed = {message["id"] for message in _eligible(service, persona_id, relationship_id, before)}
    rows = service.store.rows(
        styles, styles.c.persona_id == persona_id, styles.c.relationship_id == relationship_id
    )
    profiles = sorted(
        (row["payload"] for row in rows), key=lambda item: item.get("version", 0), reverse=True
    )
    for profile in profiles:
        if profile.get("status") != "approved":
            continue
        if before and datetime.fromisoformat(profile["created_at"]) >= before:
            continue
        if not set(profile.get("source_message_ids", [])).issubset(allowed):
            return None  # don't fall back to an older profile silently after source revocation
        return profile
    return None


def style_state(service, persona_id, relationship_id):
    service.require_scope(persona_id, relationship_id)
    rows = service.store.rows(
        styles, styles.c.persona_id == persona_id, styles.c.relationship_id == relationship_id
    )
    history = sorted(
        (row["payload"] for row in rows), key=lambda item: item.get("version", 0), reverse=True
    )
    return {
        "draft": build_style(service, persona_id, relationship_id),
        "approved": get_approved_style(service, persona_id, relationship_id),
        "history": history[:50],
        "version": max((item.get("version", 0) for item in history), default=0),
    }


@source_guard
def save_style(
    service,
    persona_id,
    relationship_id,
    rules,
    example_message_ids,
    confirmed=False,
    expected_version=0,
):
    service.require_scope(persona_id, relationship_id)
    if len(rules) > 4000 or len(example_message_ids) > 20:
        raise DomainError("STYLE_SIZE", "Style rules limit is 4000 characters and 20 examples", 422)
    eligible = {
        message["id"]: message for message in _eligible(service, persona_id, relationship_id)
    }
    ids = list(dict.fromkeys(example_message_ids))
    if not set(ids).issubset(eligible):
        raise DomainError(
            "STYLE_SOURCES",
            "Examples must be confirmed human owner messages in this relationship and outside held-out data",
            422,
        )
    with service.store.transaction() as conn:
        rows = (
            conn.execute(
                select(styles).where(
                    styles.c.persona_id == persona_id, styles.c.relationship_id == relationship_id
                )
            )
            .mappings()
            .all()
        )
        version = max((row["payload"].get("version", 0) for row in rows), default=0)
        if expected_version != version:
            raise DomainError("STALE_STYLE", "Style changed; refresh before saving")
        if confirmed:
            for row in rows:
                if row["payload"].get("status") == "approved":
                    conn.execute(
                        styles.update()
                        .where(styles.c.id == row["id"])
                        .values(payload={**row["payload"], "status": "superseded"})
                    )
        payload = {
            "id": uid(),
            "persona_id": persona_id,
            "relationship_id": relationship_id,
            "version": version + 1,
            "status": "approved" if confirmed else "draft",
            "created_at": now().isoformat(),
            "rules": rules.strip(),
            "examples": [{"message_id": id, "text": eligible[id]["content"]["text"]} for id in ids],
            "source_message_ids": ids,
            "confirmed": confirmed,
        }
        conn.execute(
            styles.insert().values(
                id=payload["id"],
                persona_id=persona_id,
                relationship_id=relationship_id,
                payload=payload,
            )
        )
    return payload
