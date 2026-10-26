"""Explicit identity inspection/remapping; source sender IDs never change."""

from __future__ import annotations

from contextlib import ExitStack

from sqlalchemy import select

from chattwin.domain import DomainError, MessageUse, UsePolicy, now, uid
from chattwin.importers.guards import source_lease
from chattwin.storage import audit, identity_links, messages, personas, uses


def inspect_identities(service, persona_id):
    persona = service._persona(persona_id)
    participants: dict[tuple[str, str], dict] = {}
    with service.store.engine.connect() as conn:
        query = (
            select(messages.c.payload, uses.c.payload.label("use_payload"))
            .join(uses, messages.c.id == uses.c.message_id)
            .where(uses.c.persona_id == persona_id)
        )
        for row in conn.execute(query).mappings():
            message, usage = row["payload"], row["use_payload"]["use_context"]
            key = (message["source"]["source_account_id"], message["sender_id"])
            item = participants.setdefault(
                key,
                {
                    "source_account_id": key[0],
                    "sender_id": key[1],
                    "name": message["provenance"].get("display_name", key[1]),
                    "message_count": 0,
                    "roles": [],
                },
            )
            item["message_count"] += 1
            if usage["sender_role"] not in item["roles"]:
                item["roles"].append(usage["sender_role"])
    return {
        "persona_id": persona_id,
        "target_identity_id": persona["target_identity_id"],
        "identity_mapping_version": persona["identity_mapping_version"],
        "links": service.store.rows(identity_links, identity_links.c.persona_id == persona_id),
        "participants": list(participants.values()),
    }


def remap_scopes(service, persona_id, source_account_id):
    service._persona(persona_id)
    result: dict[tuple[str, str], set[str]] = {}
    with service.store.engine.connect() as conn:
        for row in conn.execute(
            select(messages.c.id, messages.c.payload, uses.c.relationship_id)
            .join(uses, messages.c.id == uses.c.message_id)
            .where(uses.c.persona_id == persona_id)
        ).mappings():
            if (
                row["payload"]["source"]["source_account_id"] == source_account_id
                and row["relationship_id"]
            ):
                result.setdefault((persona_id, row["relationship_id"]), set()).add(row["id"])
    return result


def remap_identity(
    service,
    persona_id,
    source_account_id,
    owner_sender_id,
    confirm_human=False,
    expected_mapping_version=1,
):
    from chattwin.importers.management import (
        _public,
        derived_impact,
        quarantine_datasets,
        revoke_derived,
    )

    operation_id = uid()
    with source_lease(service.store):
        with ExitStack() as stack:
            with service.store.transaction() as conn:
                persona = conn.execute(
                    select(personas.c.payload).where(personas.c.id == persona_id)
                ).scalar_one_or_none()
                if not persona:
                    raise DomainError("PERSONA_NOT_FOUND", "Persona not found", 404)
                if persona["identity_mapping_version"] != expected_mapping_version:
                    raise DomainError(
                        "STALE_IDENTITY", "Identity mapping changed; refresh before remapping"
                    )
                rows = (
                    conn.execute(
                        select(
                            messages.c.payload.label("message"),
                            uses.c.message_id,
                            uses.c.relationship_id,
                            uses.c.payload.label("usage"),
                        )
                        .join(uses, messages.c.id == uses.c.message_id)
                        .where(uses.c.persona_id == persona_id)
                    )
                    .mappings()
                    .all()
                )
                target_rows = [
                    row
                    for row in rows
                    if row["message"]["source"]["source_account_id"] == source_account_id
                ]
                if owner_sender_id not in {row["message"]["sender_id"] for row in target_rows}:
                    raise DomainError(
                        "IDENTITY_REQUIRED", "Select an observed stable source sender ID", 422
                    )
                target_ids = {row["message_id"] for row in target_rows}
                scopes: dict[tuple[str, str], set[str]] = {}
                for row in target_rows:
                    if row["relationship_id"]:
                        scopes.setdefault((persona_id, row["relationship_id"]), set()).add(
                            row["message_id"]
                        )
                impacted = derived_impact(conn, scopes, whole_scopes=True, store=service.store)
                report = _public(impacted, scopes)
                stack.enter_context(
                    quarantine_datasets(
                        service.store,
                        report["revoked_dataset_ids"],
                        operation_id,
                        report["revoked_evaluation_ids"],
                    )
                )
                new_version = expected_mapping_version + 1
                for row in rows:
                    usage = dict(row["usage"])
                    context = dict(usage["use_context"])
                    context["identity_mapping_version"] = new_version
                    if row["message_id"] in target_ids:
                        message = row["message"]
                        owner = message["sender_id"] == owner_sender_id
                        private = (
                            row["relationship_id"] is not None
                            and message["provenance"].get("conversation_kind") == "private"
                        )
                        human = bool(
                            confirm_human and owner and message["origin"] in {"human", "unknown"}
                        )
                        text = message["content"]["type"] == "text" and bool(
                            message["content"].get("text")
                        )
                        context = MessageUse(
                            persona_id=persona_id,
                            relationship_id=row["relationship_id"],
                            identity_mapping_version=new_version,
                            sender_role="owner" if owner else "partner" if private else "other",
                            use_policy=UsePolicy(
                                context=private and text,
                                style=private and owner and human and text,
                                training_target=private and owner and human and text,
                            ),
                        ).model_dump(mode="json")
                        usage.update(
                            human_confirmed=human, confirmed_at=now().isoformat() if human else None
                        )
                    usage["use_context"] = context
                    conn.execute(
                        uses.update()
                        .where(
                            uses.c.message_id == row["message_id"], uses.c.persona_id == persona_id
                        )
                        .values(payload=usage)
                    )
                for link in (
                    conn.execute(
                        select(identity_links).where(identity_links.c.persona_id == persona_id)
                    )
                    .mappings()
                    .all()
                ):
                    if link["source_account_id"] == source_account_id:
                        conn.execute(
                            identity_links.delete().where(identity_links.c.id == link["id"])
                        )
                    else:
                        conn.execute(
                            identity_links.update()
                            .where(identity_links.c.id == link["id"])
                            .values(payload={**link["payload"], "version": new_version})
                        )
                conn.execute(
                    identity_links.insert().values(
                        id=uid(),
                        persona_id=persona_id,
                        source_account_id=source_account_id,
                        sender_id=owner_sender_id,
                        payload={
                            "identity_id": persona["target_identity_id"],
                            "confirmed": True,
                            "version": new_version,
                        },
                    )
                )
                persona = {
                    **persona,
                    "identity_mapping_version": new_version,
                    "version": persona.get("version", 1) + 1,
                }
                conn.execute(
                    personas.update().where(personas.c.id == persona_id).values(payload=persona)
                )
                revoke_derived(conn, impacted, scopes, "identity_remapped")
                conn.execute(
                    audit.insert().values(
                        id=operation_id,
                        kind="data_revocation",
                        payload={
                            "reason": "identity_remapped",
                            "persona_id": persona_id,
                            "mapping_version": new_version,
                            "created_at": now().isoformat(),
                        },
                    )
                )
    return {
        "persona_id": persona_id,
        "mapping_version": new_version,
        "identity_mapping_version": new_version,
        "source_account_id": source_account_id,
        "owner_sender_id": owner_sender_id,
        "operation_id": operation_id,
        **report,
        "impact": report,
        "invalidate_scopes": report["affected_scopes"],
        "weights_forgotten": False,
        "quarantine_cleanup_pending": (
            service.store.root / "maintenance" / "data-operations" / (operation_id + ".json")
        ).exists(),
    }
