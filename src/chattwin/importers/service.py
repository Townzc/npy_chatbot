"""Application data service: all writes are scoped, transactional and traceable."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from chattwin.domain import DomainError, MessageUse, Persona, UsePolicy, now, uid
from chattwin.storage import Store, identity_links, imports, messages, personas, relationships, uses

from .guards import source_guard
from .parsers import digest, file_hash, inspect, parse


class DataService:
    def __init__(self, store: Store):
        self.store = store

    def create_persona(self, name: str, target_identity_id: str | None = None) -> dict:
        if not name.strip():
            raise DomainError("NAME_REQUIRED", "Persona name required", 422)
        persona = Persona(name=name.strip(), target_identity_id=target_identity_id or uid())
        payload = persona.model_dump(mode="json")
        with self.store.transaction() as conn:
            conn.execute(personas.insert().values(id=persona.id, payload=payload))
        return payload

    def create_relationship(self, persona_id: str, name: str) -> dict:
        self._persona(persona_id)
        payload = {"id": uid(), "persona_id": persona_id, "name": name, "version": 1}
        with self.store.transaction() as conn:
            conn.execute(
                relationships.insert().values(
                    id=payload["id"], persona_id=persona_id, payload=payload
                )
            )
        return payload

    def _persona(self, persona_id: str) -> dict:
        found = self.store.rows(personas, personas.c.id == persona_id)
        if not found:
            raise DomainError("PERSONA_NOT_FOUND", "Persona not found", 404)
        return found[0]["payload"]

    def require_scope(self, persona_id: str, relationship_id: str) -> None:
        if not self.store.rows(
            relationships,
            relationships.c.id == relationship_id,
            relationships.c.persona_id == persona_id,
        ):
            raise DomainError("SCOPE_MISMATCH", "Relationship is not in this Persona", 404)

    def inspect(self, path: Path | str, format: str = "auto", mapping: dict | None = None) -> dict:
        return inspect(path, format, mapping)

    @source_guard
    def import_file(
        self,
        path: Path | str,
        persona_id: str,
        relationship_id: str,
        owner_sender_id: str,
        source_account_id: str,
        format: str = "auto",
        mapping: dict | None = None,
        confirm_human: bool = False,
        skip_errors: bool = False,
    ) -> dict:
        self.require_scope(persona_id, relationship_id)
        persona = self._persona(persona_id)
        if not source_account_id.strip() or source_account_id == "unconfirmed":
            raise DomainError("IDENTITY_REQUIRED", "Explicit source account ID required", 422)
        path = Path(path)
        mapping = {**(mapping or {}), "source_account_id": source_account_id, "_inspect": False}
        report = inspect(path, format, mapping)
        manifest_validation = report.get("manifest_validation")
        if manifest_validation and (
            manifest_validation["persona_id"] != persona_id
            or manifest_validation["relationship_id"] != relationship_id
        ):
            raise DomainError(
                "MANIFEST_SCOPE",
                "Canonical manifest scope differs from selected destination; explicit rebinding is not supported",
                422,
            )
        if report["bad_rows"] and not skip_errors:
            raise DomainError(
                "IMPORT_ERRORS",
                f"{report['bad_rows']} invalid rows; inspect before explicitly skipping",
                422,
            )
        sender_ids = {sender["id"] for sender in report["senders"]}
        if owner_sender_id not in sender_ids:
            raise DomainError(
                "IDENTITY_REQUIRED", "Select an actual stable sender ID from the preview", 422
            )
        # The user selected a relationship and identity; display names never form this key.
        mapping.setdefault("conversation_id", digest([source_account_id, sorted(sender_ids)]))
        batch_id = uid()
        mapping["batch_id"] = batch_id
        report.update(
            {
                "id": batch_id,
                "persona_id": persona_id,
                "relationship_id": relationship_id,
                "owner_sender_id": owner_sender_id,
                "source_account_id": source_account_id,
                "identity_confirmed": True,
                "human_origin_confirmed": confirm_human,
                "inserted": 0,
                "duplicates": 0,
                "skipped": report["bad_rows"] if skip_errors else 0,
                "candidate_training_targets": 0,
                "scope_excluded": 0,
                "message_ids": [],
            }
        )
        # Preview is intentionally not retained in batch logs; raw content is in messages only.
        persisted_report = {key: value for key, value in report.items() if key != "preview"}
        with self.store.transaction() as conn:
            owners = (
                conn.execute(
                    select(identity_links.c.sender_id).where(
                        identity_links.c.persona_id == persona_id,
                        identity_links.c.source_account_id == source_account_id,
                    )
                )
                .scalars()
                .all()
            )
            if any(sender_id != owner_sender_id for sender_id in owners):
                raise DomainError(
                    "IDENTITY_CONFLICT",
                    "This source account already has another owner mapping; use explicit identity remapping first",
                    409,
                )
            conn.execute(
                imports.insert().values(
                    id=batch_id, file_sha256=report["file_sha256"], payload=persisted_report
                )
            )
            link = (
                conn.execute(
                    select(identity_links).where(
                        identity_links.c.persona_id == persona_id,
                        identity_links.c.source_account_id == source_account_id,
                        identity_links.c.sender_id == owner_sender_id,
                    )
                )
                .mappings()
                .first()
            )
            if not link:
                conn.execute(
                    identity_links.insert().values(
                        id=uid(),
                        persona_id=persona_id,
                        source_account_id=source_account_id,
                        sender_id=owner_sender_id,
                        payload={
                            "identity_id": persona["target_identity_id"],
                            "confirmed": True,
                            "version": persona["identity_mapping_version"],
                        },
                    )
                )
            for number, message, error in parse(path, format, mapping):
                if error:
                    if skip_errors:
                        continue
                    raise DomainError("IMPORT_ERRORS", f"Invalid row {number}", 422)
                assert message is not None
                original_origin = message.origin
                # Trusted confirmation is stored per Persona use; raw source facts are unchanged.
                human_confirmed = bool(
                    confirm_human
                    and message.sender_id == owner_sender_id
                    and original_origin in {"human", "unknown"}
                )
                private = message.provenance.get("conversation_kind") == "private"
                report["scope_excluded"] += not private
                is_owner = message.sender_id == owner_sender_id
                policy = UsePolicy(
                    context=private
                    and message.content.type == "text"
                    and original_origin not in {"platform_system", "mode_notice"},
                    style=private
                    and is_owner
                    and human_confirmed
                    and bool(message.content.text)
                    and message.content.type == "text",
                    training_target=private
                    and is_owner
                    and human_confirmed
                    and bool(message.content.text)
                    and message.content.type == "text",
                )
                context = MessageUse(
                    persona_id=persona_id,
                    relationship_id=relationship_id if private else None,
                    identity_mapping_version=persona["identity_mapping_version"],
                    sender_role="system"
                    if original_origin == "platform_system"
                    else "owner"
                    if is_owner
                    else "partner"
                    if private
                    else "other",
                    use_policy=policy,
                )
                identity_key = [
                    message.source.platform,
                    message.source.source_account_id,
                    message.conversation_id,
                ]
                dedup_key = digest(
                    identity_key
                    + (
                        ["id", message.source.source_message_id]
                        if message.source.source_message_id
                        else ["file", message.source.file_sha256, message.source.record_index]
                    )
                )
                existing = (
                    conn.execute(select(messages).where(messages.c.dedup_key == dedup_key))
                    .mappings()
                    .first()
                )
                if existing:
                    stored = existing["payload"]
                    if (
                        stored["sender_id"] != message.sender_id
                        or stored["content"] != message.content.model_dump(mode="json")
                        or stored["occurred_at"] != message.model_dump(mode="json")["occurred_at"]
                    ):
                        raise DomainError(
                            "DUPLICATE_CONFLICT",
                            "Stable message ID maps to different source content; review export",
                            422,
                        )
                    message.id = existing["id"]
                    report["duplicates"] += 1
                else:
                    conn.execute(
                        messages.insert().values(
                            id=message.id,
                            dedup_key=dedup_key,
                            batch_id=batch_id,
                            conversation_id=message.conversation_id,
                            occurred_at=message.occurred_at.isoformat(),
                            payload=message.model_dump(mode="json"),
                        )
                    )
                    report["inserted"] += 1
                existing_use = (
                    conn.execute(
                        select(uses).where(
                            uses.c.message_id == message.id, uses.c.persona_id == persona_id
                        )
                    )
                    .mappings()
                    .first()
                )
                use_payload = {
                    "use_context": context.model_dump(mode="json"),
                    "human_confirmed": human_confirmed,
                    "confirmed_at": now().isoformat() if human_confirmed else None,
                }
                if existing_use:
                    old_context = existing_use["payload"]["use_context"]
                    if (
                        existing_use["relationship_id"] != context.relationship_id
                        or old_context["sender_role"] != context.sender_role
                    ):
                        raise DomainError(
                            "IDENTITY_CONFLICT",
                            "Existing message use has a different relationship or owner; create a new Persona or explicit remapping workflow",
                            409,
                        )
                    # An idempotent reimport must never silently revoke previous confirmation.
                    if human_confirmed:
                        conn.execute(
                            uses.update()
                            .where(uses.c.message_id == message.id, uses.c.persona_id == persona_id)
                            .values(payload=use_payload)
                        )
                else:
                    conn.execute(
                        uses.insert().values(
                            message_id=message.id,
                            persona_id=persona_id,
                            relationship_id=context.relationship_id,
                            payload=use_payload,
                        )
                    )
                report["message_ids"].append(message.id)
                report["candidate_training_targets"] += policy.training_target
            if file_hash(path) != report["file_sha256"]:
                raise DomainError(
                    "SOURCE_CHANGED", "Source changed between preview and import", 409
                )
            conn.execute(
                imports.update()
                .where(imports.c.id == batch_id)
                .values(payload={key: value for key, value in report.items() if key != "preview"})
            )
        return report

    def list_messages(
        self,
        persona_id: str,
        relationship_id: str,
        limit: int | None = 200,
        before: datetime | None = None,
    ) -> list[dict]:
        self.require_scope(persona_id, relationship_id)
        query = (
            select(messages.c.payload, uses.c.payload.label("use_payload"))
            .join(uses, uses.c.message_id == messages.c.id)
            .where(uses.c.persona_id == persona_id, uses.c.relationship_id == relationship_id)
            .order_by(
                messages.c.occurred_at, messages.c.payload["sequence"].as_integer(), messages.c.id
            )
        )
        if before:
            if before.tzinfo is None:
                raise DomainError("CUTOFF_TIMEZONE", "Replay cutoff must include a timezone", 422)
            query = query.where(messages.c.occurred_at < before.astimezone(UTC).isoformat())
        if limit is not None:
            query = query.limit(limit)
        with self.store.engine.connect() as conn:
            result = []
            for row in conn.execute(query).mappings():
                message = dict(row["payload"])
                use_payload = row["use_payload"]
                message["use_context"] = use_payload["use_context"]
                message["relationship_id"] = relationship_id
                message["provenance"] = {
                    **message["provenance"],
                    "raw_origin": message["origin"],
                    "human_origin_confirmed": use_payload["human_confirmed"],
                }
                if use_payload["human_confirmed"] and message["origin"] == "unknown":
                    message["origin"] = "human"
                result.append(message)
            # Stable source sequence resolves equal timestamps, not random UUIDs.
            return sorted(
                result, key=lambda item: (item["occurred_at"], item["sequence"], item["id"])
            )

    @source_guard
    def export_canonical(
        self, persona_id: str, relationship_id: str, destination: Path | str
    ) -> dict:
        content = self.list_messages(persona_id, relationship_id, limit=None)
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            for message in content:
                handle.write(json.dumps(message, ensure_ascii=False) + "\n")
        path.chmod(0o600)
        manifest = {
            "schema_version": "1.0",
            "persona_id": persona_id,
            "relationship_id": relationship_id,
            "count": len(content),
            "file_sha256": file_hash(path),
            "created_at": now().isoformat(),
            "conversations": [
                {"id": id, "kind": "private"}
                for id in sorted({message["conversation_id"] for message in content})
            ],
            "source_account_ids": sorted(
                {message["source"]["source_account_id"] for message in content}
            ),
        }
        sidecar = path.with_suffix(path.suffix + ".manifest.json")
        with sidecar.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(manifest, ensure_ascii=False, indent=2))
        sidecar.chmod(0o600)
        return manifest

    def build_dataset(self, persona_id: str, relationship_id: str, **options) -> dict:
        from chattwin.datasets import build_dataset

        return build_dataset(self, persona_id, relationship_id, **options)

    def build_style(
        self, persona_id: str, relationship_id: str, before: datetime | None = None
    ) -> dict:
        from chattwin.personalization import build_style

        return build_style(self, persona_id, relationship_id, before)

    def add_memory(
        self,
        persona_id: str,
        relationship_id: str,
        text: str,
        source_message_ids: list[str],
        confirmed: bool = False,
    ) -> dict:
        from chattwin.memory import add_memory

        return add_memory(self, persona_id, relationship_id, text, source_message_ids, confirmed)

    def update_memory(
        self,
        id: str,
        persona_id: str,
        relationship_id: str,
        text: str | None = None,
        confirmed: bool | None = None,
        deleted: bool | None = None,
        **options,
    ) -> dict:
        from chattwin.memory import update_memory

        return update_memory(
            self, id, persona_id, relationship_id, text, confirmed, deleted, **options
        )

    def retrieve_memories(
        self, persona_id: str, relationship_id: str, query: str, before: datetime | None = None
    ) -> list[dict]:
        from chattwin.memory import retrieve_memories

        return retrieve_memories(self, persona_id, relationship_id, query, before)

    def style_state(self, persona_id: str, relationship_id: str) -> dict:
        from chattwin.personalization import style_state

        return style_state(self, persona_id, relationship_id)

    def save_style(
        self,
        persona_id: str,
        relationship_id: str,
        rules: str,
        example_message_ids: list[str],
        confirmed: bool = False,
        expected_version: int = 0,
    ) -> dict:
        from chattwin.personalization import save_style

        return save_style(
            self,
            persona_id,
            relationship_id,
            rules,
            example_message_ids,
            confirmed,
            expected_version,
        )

    def get_approved_style(
        self, persona_id: str, relationship_id: str, before: datetime | None = None
    ) -> dict | None:
        from chattwin.personalization import get_approved_style

        return get_approved_style(self, persona_id, relationship_id, before)

    def identities(self, persona_id: str) -> dict:
        from chattwin.identity import inspect_identities

        return inspect_identities(self, persona_id)

    def remap_identity(
        self,
        persona_id: str,
        source_account_id: str,
        owner_sender_id: str,
        confirm_human: bool = False,
        expected_mapping_version: int = 1,
    ) -> dict:
        from chattwin.identity import remap_identity

        return remap_identity(
            self,
            persona_id,
            source_account_id,
            owner_sender_id,
            confirm_human,
            expected_mapping_version,
        )

    def deletion_impact(self, batch_id: str, persona_id: str, relationship_id: str) -> dict:
        from chattwin.importers.management import deletion_impact

        return deletion_impact(self, batch_id, persona_id, relationship_id)

    def delete_import(
        self, batch_id: str, persona_id: str, relationship_id: str, impact_hash: str
    ) -> dict:
        from chattwin.importers.management import delete_import

        return delete_import(self, batch_id, persona_id, relationship_id, impact_hash)
