"""Source-backed style statistics. Held-out and future text is excluded."""

from datetime import datetime

from chattwin.datasets import forbidden_sources
from chattwin.domain import now, uid
from chattwin.storage import styles


def build_style(
    service, persona_id: str, relationship_id: str, before: datetime | None = None
) -> dict:
    excluded = forbidden_sources(service, persona_id, relationship_id)
    messages = [
        message
        for message in service.list_messages(persona_id, relationship_id, limit=None, before=before)
        if message["id"] not in excluded
        and message["use_context"]["use_policy"]["style"]
        and message["origin"] == "human"
        and message["content"]["type"] == "text"
        and message["content"].get("text")
        and message["content"]["text"] not in {"对方已切换为ai模式", "本人已接管"}
    ]
    previous = service.store.rows(
        styles, styles.c.persona_id == persona_id, styles.c.relationship_id == relationship_id
    )
    payload = {
        "id": uid(),
        "persona_id": persona_id,
        "relationship_id": relationship_id,
        "version": len(previous) + 1,
        "created_at": now().isoformat(),
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
            for message in messages[:5]
        ],
        "rules": "",
        "before": before.isoformat() if before else None,
    }
    with service.store.transaction() as conn:
        conn.execute(
            styles.insert().values(
                id=payload["id"],
                persona_id=persona_id,
                relationship_id=relationship_id,
                payload=payload,
            )
        )
    return payload
