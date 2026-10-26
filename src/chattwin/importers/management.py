"""Source deletion and revocation with an atomic SQLite decision and recoverable file moves.

Only derived files owned under Store.root are removed. Original exports, backups,
remote requests and trained weights are never described as forgotten.
"""

from __future__ import annotations

import json
import shutil
from contextlib import ExitStack, contextmanager
from pathlib import Path

from filelock import FileLock
from sqlalchemy import select

from chattwin.domain import DomainError, now, uid
from chattwin.importers.guards import source_lease
from chattwin.importers.parsers import digest
from chattwin.storage import (
    artifacts,
    audit,
    bindings,
    datasets,
    identity_links,
    imports,
    jobs,
    memories,
    messages,
    outbox,
    sessions,
    styles,
    uses,
)

WARNINGS = [
    "原始导出文件和已有备份由用户保管，本操作不删除这些外部副本。",
    "已训练权重不会自动遗忘：依赖产物和部署将撤销，权重保留在私有目录供删除或重新训练。",
    "已发送的平台消息和既有运行会话记录不能通过删除训练来源撤回。",
    "本地依赖来源的评测案例、提示词和结果一并清除；已导出的评分 CSV 等外部副本无法召回。",
]


def _scope(row):
    return row["persona_id"], row["relationship_id"]


def _source_ids(payload):
    return set(payload.get("source_message_ids", []))


def derived_impact(
    conn, scope_messages: dict[tuple[str, str], set[str]], whole_scopes=False, store=None
):
    result: dict[str, list[dict]] = {
        "styles": [],
        "memories": [],
        "datasets": [],
        "artifacts": [],
        "deployments": [],
        "jobs": [],
        "evaluations": [],
    }
    for name, table in (("styles", styles), ("memories", memories), ("datasets", datasets)):
        for row in conn.execute(select(table)).mappings():
            if _scope(row) in scope_messages and (
                whole_scopes or _source_ids(row["payload"]) & scope_messages[_scope(row)]
            ):
                result[name].append(dict(row))
    dataset_ids = {row["id"] for row in result["datasets"]}
    for row in conn.execute(select(artifacts)).mappings():
        payload = row["payload"]
        manifest = payload.get("manifest", {})
        source_dataset = (
            payload.get("dataset_id")
            or payload.get("dataset_version")
            or manifest.get("dataset_version")
            or manifest.get("dataset_id")
        )
        if _scope(row) in scope_messages and (
            whole_scopes
            or source_dataset in dataset_ids
            or _source_ids(payload) & scope_messages[_scope(row)]
        ):
            result["artifacts"].append(dict(row))
    artifact_ids = {row["id"] for row in result["artifacts"]}
    from chattwin.storage import model_deployments

    for row in conn.execute(select(model_deployments)).mappings():
        if row["artifact_id"] in artifact_ids:
            result["deployments"].append(dict(row))
    for row in conn.execute(select(jobs)).mappings():
        payload = row["payload"]
        spec = payload.get("spec", {})
        if (
            payload.get("dataset_id")
            or payload.get("dataset_version")
            or spec.get("dataset_version")
        ) in dataset_ids:
            result["jobs"].append(dict(row))
    if store is not None:
        for path in sorted((store.root / "evaluations").glob("*/manifest.json")):
            if path.is_symlink() or not path.resolve().is_relative_to(
                (store.root / "evaluations").resolve()
            ):
                raise DomainError(
                    "EVAL_PROVENANCE_INVALID", "Evaluation lineage path is unsafe", 409
                )
            try:
                manifest = json.loads(path.read_text())
                row = {
                    "id": manifest["id"],
                    "persona_id": manifest["persona_id"],
                    "relationship_id": manifest["relationship_id"],
                    "payload": manifest,
                }
                if (
                    path.parent.name != row["id"]
                    or not isinstance(manifest["source_message_ids"], list)
                    or any(not isinstance(source, str) for source in manifest["source_message_ids"])
                    or not all(
                        isinstance(row[key], str) for key in ("persona_id", "relationship_id")
                    )
                ):
                    raise ValueError("invalid evaluation lineage")
            except (OSError, ValueError, KeyError, TypeError):
                raise DomainError(
                    "EVAL_PROVENANCE_INVALID",
                    "Evaluation lineage is incomplete; repair it before source deletion",
                    409,
                ) from None
            if _scope(row) in scope_messages and (
                whole_scopes or _source_ids(manifest) & scope_messages[_scope(row)]
            ):
                result["evaluations"].append(row)
    return result


def revoke_derived(conn, impacted, scopes, reason):
    timestamp = now().isoformat()
    for name, table in (
        ("styles", styles),
        ("memories", memories),
        ("datasets", datasets),
        ("artifacts", artifacts),
    ):
        for row in impacted[name]:
            payload = {
                **row["payload"],
                "status": "revoked",
                "revoked_at": timestamp,
                "revoked_reason": reason,
            }
            if name == "styles":
                payload.update(rules="", examples=[], confirmed=False)
            elif name == "memories":
                payload.update(text="", history=[], confirmed=False, deleted=True)
            elif name == "datasets":
                payload["files_removed_from_active_storage"] = True
            elif name == "artifacts":
                payload["weights_forgotten"] = False
            conn.execute(table.update().where(table.c.id == row["id"]).values(payload=payload))
    from chattwin.storage import model_deployments

    for row in impacted["deployments"]:
        conn.execute(
            model_deployments.update()
            .where(model_deployments.c.id == row["id"])
            .values(
                status="revoked",
                payload={
                    **row["payload"],
                    "status": "revoked",
                    "revoked_reason": reason,
                    "revoked_at": timestamp,
                },
            )
        )
    for row in impacted["jobs"]:
        conn.execute(
            jobs.update()
            .where(jobs.c.id == row["id"])
            .values(
                payload={
                    **row["payload"],
                    "cancel_requested": True,
                    "invalidated": True,
                    "revoked_reason": reason,
                }
            )
        )
    for binding in conn.execute(select(bindings)).mappings():
        if _scope(binding) not in scopes:
            continue
        row = (
            conn.execute(select(sessions).where(sessions.c.binding_id == binding["id"]))
            .mappings()
            .first()
        )
        if not row:
            continue
        payload = dict(row["payload"])
        payload.update(
            memory_version=payload.get("memory_version", 1) + 1,
            persona_version=payload.get("persona_version", 1) + 1,
            model_deployment_id="mock-v1",
            data_revoked_at=timestamp,
        )
        conn.execute(
            sessions.update()
            .where(sessions.c.binding_id == binding["id"])
            .values(
                mode="HUMAN" if row["mode"] == "HUMAN" else "PAUSED",
                control_epoch=row["control_epoch"] + (row["mode"] != "HUMAN"),
                payload=payload,
            )
        )
        conn.execute(
            outbox.update()
            .where(
                outbox.c.binding_id == binding["id"],
                outbox.c.status == "planned",
                outbox.c.kind.in_(["ai_reply", "enable_notice"]),
            )
            .values(status="cancelled")
        )


def _public(impacted, scope_messages):
    return {
        "affected_scopes": [
            {"persona_id": p, "relationship_id": r} for p, r in sorted(scope_messages)
        ],
        "revoked_style_ids": [row["id"] for row in impacted["styles"]],
        "revoked_memory_ids": [row["id"] for row in impacted["memories"]],
        "revoked_dataset_ids": [row["id"] for row in impacted["datasets"]],
        "revoked_artifact_ids": [row["id"] for row in impacted["artifacts"]],
        "revoked_deployment_ids": [row["id"] for row in impacted["deployments"]],
        "revoked_evaluation_ids": [row["id"] for row in impacted["evaluations"]],
        "cancel_job_ids": [
            row["id"]
            for row in impacted["jobs"]
            if row["status"] in {"queued", "validating", "running"}
        ],
        "versions": {
            name: [
                {
                    "id": row["id"],
                    "version": row["payload"].get("version"),
                    "status": row["payload"].get("status"),
                    "digest": digest(row["payload"]),
                }
                for row in rows
            ]
            for name, rows in impacted.items()
        },
    }


def _deletion_plan(conn, batch_id, persona_id, relationship_id, store=None):
    batches = {row["id"]: dict(row) for row in conn.execute(select(imports)).mappings()}
    batch = batches.get(batch_id)
    if (
        not batch
        or batch["payload"].get("persona_id") != persona_id
        or batch["payload"].get("relationship_id") != relationship_id
    ):
        raise DomainError("IMPORT_NOT_FOUND", "Import is not in this scope", 404)
    raw = {row["id"]: dict(row) for row in conn.execute(select(messages)).mappings()}
    membership = {}
    for id, row in batches.items():
        payload = row["payload"]
        if "message_ids" not in payload and payload.get("duplicates", 0):
            raise DomainError(
                "IMPORT_PROVENANCE_INCOMPLETE",
                "Legacy duplicate batch lacks source membership; reimport it to establish traceability before deleting",
                409,
            )
        membership[id] = set(
            payload.get("message_ids", [mid for mid, msg in raw.items() if msg["batch_id"] == id])
        )
    target = membership[batch_id]
    removed_raw, retained_raw, remove_uses, rehome = [], [], [], {}
    scope_messages: dict[tuple[str, str], set[str]] = {}
    all_uses = [dict(row) for row in conn.execute(select(uses)).mappings()]
    uses_by_message: dict[str, list[dict]] = {}
    references: dict[str, set[str]] = {}
    for use in all_uses:
        uses_by_message.setdefault(use["message_id"], []).append(use)
    for id, ids in membership.items():
        for mid in ids:
            references.setdefault(mid, set()).add(id)
    for mid in target:
        if mid not in raw:
            continue
        retained = sorted(references.get(mid, set()) - {batch_id})
        if retained:
            retained_raw.append(mid)
            if raw[mid]["batch_id"] == batch_id:
                rehome[mid] = retained[0]
        else:
            removed_raw.append(mid)
        for use in uses_by_message.get(mid, []):
            keep = any(
                batches[id]["payload"].get("persona_id") == use["persona_id"]
                and batches[id]["payload"].get("relationship_id") == use["relationship_id"]
                for id in retained
            )
            if not keep:
                remove_uses.append(use)
                if use["relationship_id"]:
                    scope_messages.setdefault(_scope(use), set()).add(mid)
    impacted = derived_impact(conn, scope_messages, store=store)
    public = {
        "batch_id": batch_id,
        "source_file_sha256": batch["file_sha256"],
        **_public(impacted, scope_messages),
        "message_ids_removed": sorted(removed_raw),
        "message_ids_retained": sorted(retained_raw),
        "use_keys_removed": sorted([[row["persona_id"], row["message_id"]] for row in remove_uses]),
        "counts": {
            "raw_messages_removed": len(removed_raw),
            "raw_messages_retained_by_other_imports": len(retained_raw),
            "message_uses_removed": len(remove_uses),
            **{name: len(rows) for name, rows in impacted.items()},
        },
        "warnings": WARNINGS,
    }
    public["impact_hash"] = digest(public)
    return public, {
        "raw": raw,
        "removed_raw": removed_raw,
        "remove_uses": remove_uses,
        "rehome": rehome,
        "scopes": scope_messages,
        "impacted": impacted,
    }


def deletion_impact(service, batch_id, persona_id, relationship_id):
    service.require_scope(persona_id, relationship_id)
    with service.store.engine.connect() as conn:
        return _deletion_plan(conn, batch_id, persona_id, relationship_id, service.store)[0]


def _safe_child(root: Path, relative: str) -> Path:
    candidate = root / relative
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()) or candidate.is_symlink():
        raise DomainError(
            "UNSAFE_DATA_PATH", "Managed data path must stay inside private root", 422
        )
    return candidate


def _purge_quarantine(path):
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
        return True
    except OSError:
        # Keep the journal and isolated file for retry; never claim secure erasure.
        return False


def recover_data_operations(store):
    """Resolve interrupted file moves from the durable SQLite audit decision."""
    with FileLock(store.root / "data-management.lock", timeout=10):
        journal_dir = store.root / "maintenance" / "data-operations"
        if not journal_dir.exists():
            return []
        recovered = []
        for path in journal_dir.glob("*.json"):
            journal = json.loads(path.read_text())
            committed = bool(store.rows(audit, audit.c.id == journal["id"]))
            cleanup_complete = True
            for item in journal["moves"]:
                original, quarantined = (
                    _safe_child(store.root, item["original"]),
                    _safe_child(store.root, item["quarantined"]),
                )
                if committed:
                    cleanup_complete = _purge_quarantine(quarantined) and cleanup_complete
                elif quarantined.exists() and not original.exists():
                    original.parent.mkdir(parents=True, exist_ok=True)
                    quarantined.rename(original)
            if cleanup_complete:
                path.unlink()
            recovered.append(
                {
                    "id": journal["id"],
                    "committed": committed,
                    **({"cleanup_pending": True} if not cleanup_complete else {}),
                }
            )
        return recovered


@contextmanager
def quarantine_datasets(store, dataset_ids, operation_id, evaluation_ids=()):
    journal_dir = store.root / "maintenance" / "data-operations"
    journal_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    moves = []
    managed_paths = [("datasets", id) for id in dataset_ids] + [
        ("evaluations", id) for id in evaluation_ids
    ]
    for category, id in managed_paths:
        source = _safe_child(store.root, category + "/" + id)
        if source.exists():
            if source.parent.resolve() != (store.root / category).resolve():
                raise DomainError("UNSAFE_DATA_PATH", "Invalid managed artifact identifier", 422)
            target = _safe_child(store.root, f"quarantine/{operation_id}/{category}/{id}")
            moves.append(
                {
                    "original": str(source.relative_to(store.root)),
                    "quarantined": str(target.relative_to(store.root)),
                }
            )
    journal_path = journal_dir / (operation_id + ".json")
    journal_path.write_text(json.dumps({"id": operation_id, "moves": moves}))
    journal_path.chmod(0o600)
    try:
        for item in moves:
            source, target = (
                _safe_child(store.root, item["original"]),
                _safe_child(store.root, item["quarantined"]),
            )
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            source.rename(target)
        yield
    finally:
        # A commit can fail after file moves. The audit row is the sole commit decision.
        committed = bool(store.rows(audit, audit.c.id == operation_id))
        cleanup_complete = True
        for item in moves:
            source, target = (
                _safe_child(store.root, item["original"]),
                _safe_child(store.root, item["quarantined"]),
            )
            if committed:
                cleanup_complete = _purge_quarantine(target) and cleanup_complete
            elif target.exists() and not source.exists():
                target.rename(source)
        if cleanup_complete:
            journal_path.unlink(missing_ok=True)


def delete_import(service, batch_id, persona_id, relationship_id, impact_hash):
    service.require_scope(persona_id, relationship_id)
    operation_id = uid()
    with source_lease(service.store):
        # Freeze provenance and the derived set while moving files. ExitStack runs
        # after commit/rollback, when the audit decision is visible on another connection.
        with ExitStack() as stack:
            with service.store.transaction() as conn:
                current, work = _deletion_plan(
                    conn, batch_id, persona_id, relationship_id, service.store
                )
                if current["impact_hash"] != impact_hash:
                    raise DomainError(
                        "STALE_DELETION_PREVIEW", "Deletion impact changed; preview again"
                    )
                stack.enter_context(
                    quarantine_datasets(
                        service.store,
                        current["revoked_dataset_ids"],
                        operation_id,
                        current["revoked_evaluation_ids"],
                    )
                )
                revoke_derived(conn, work["impacted"], work["scopes"], "source_batch_deleted")
                for row in work["remove_uses"]:
                    conn.execute(
                        uses.delete().where(
                            uses.c.message_id == row["message_id"],
                            uses.c.persona_id == row["persona_id"],
                        )
                    )
                for mid, new_batch in work["rehome"].items():
                    payload = dict(work["raw"][mid]["payload"])
                    payload["source"] = {**payload["source"], "import_batch_id": new_batch}
                    conn.execute(
                        messages.update()
                        .where(messages.c.id == mid)
                        .values(batch_id=new_batch, payload=payload)
                    )
                if work["removed_raw"]:
                    conn.execute(messages.delete().where(messages.c.id.in_(work["removed_raw"])))
                conn.execute(imports.delete().where(imports.c.id == batch_id))
                # One pass over remaining usage avoids a scan per historical participant.
                remaining = conn.execute(
                    select(messages.c.payload, uses.c.persona_id).join(
                        uses, messages.c.id == uses.c.message_id
                    )
                ).mappings()
                participant_refs = {
                    (
                        row["persona_id"],
                        row["payload"]["source"]["source_account_id"],
                        row["payload"]["sender_id"],
                    )
                    for row in remaining
                }
                for link in conn.execute(select(identity_links)).mappings().all():
                    if (
                        link["persona_id"],
                        link["source_account_id"],
                        link["sender_id"],
                    ) not in participant_refs:
                        conn.execute(
                            identity_links.delete().where(identity_links.c.id == link["id"])
                        )
                conn.execute(
                    audit.insert().values(
                        id=operation_id,
                        kind="data_revocation",
                        payload={
                            "reason": "source_batch_deleted",
                            "batch_id": batch_id,
                            "counts": current["counts"],
                            "created_at": now().isoformat(),
                        },
                    )
                )
    return {
        **current,
        "deleted": True,
        "operation_id": operation_id,
        "invalidate_scopes": current["affected_scopes"],
        "weights_forgotten": False,
        "quarantine_cleanup_pending": (
            service.store.root / "maintenance" / "data-operations" / (operation_id + ".json")
        ).exists(),
    }
