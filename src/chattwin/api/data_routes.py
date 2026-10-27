"""Owner-authenticated data management routes; no real-world messages are sent here."""

from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import Field

from chattwin.domain import Contract, DomainError, ModeCommand, Scope, uid
from chattwin.identity import remap_scopes
from chattwin.importers import DataService
from chattwin.importers.management import recover_data_operations
from chattwin.importers.parsers import file_hash
from chattwin.storage import bindings, datasets, imports


class StyleInput(Scope):
    rules: str = Field(default="", max_length=4000)
    example_message_ids: list[str] = Field(default_factory=list, max_length=20)
    confirmed: bool = False
    expected_version: int = Field(ge=0)


class MemoryPatch(Scope):
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    confirmed: bool | None = None
    expires_at: datetime | None = None
    expected_version: int | None = Field(default=None, ge=1)


class IdentityRemap(Contract):
    persona_id: str
    source_account_id: str
    owner_sender_id: str
    confirm_human: bool = False
    expected_mapping_version: int = Field(ge=1)


class DeleteInput(Contract):
    impact_hash: str = Field(min_length=64, max_length=64)


async def _finish_operation(coroutine):
    """A disconnected HTTP client must not lower barriers while a thread still writes."""
    task = asyncio.create_task(coroutine)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.shield(task)
        raise


def data_router(store, get_coordinator, authenticate):
    router = APIRouter(
        prefix="/api/v1", dependencies=[Depends(authenticate)], tags=["data-management"]
    )
    data = DataService(store)
    # Called when application routes are constructed, before accepting requests.
    recover_data_operations(store)

    async def mutate(scopes, operation, *, stop=False):
        coordinator = get_coordinator()
        async with AsyncExitStack() as stack:
            for scope in scopes:
                await stack.enter_async_context(
                    coordinator.scope_update(scope["persona_id"], scope["relationship_id"])
                )
            if stop:
                for scope in scopes:
                    for binding in store.rows(
                        bindings,
                        bindings.c.persona_id == scope["persona_id"],
                        bindings.c.relationship_id == scope["relationship_id"],
                        bindings.c.channel_account_id == coordinator.channel.account_id,
                        bindings.c.active.is_(True),
                    ):
                        await coordinator.command(
                            binding["id"], ModeCommand(command_id=uid(), action="pause")
                        )
            result = await asyncio.to_thread(operation)
            callback = getattr(coordinator, "on_sources_revoked", None)
            if callback and result.get("revoked_dataset_ids"):
                await callback(result)
            return result

    @router.get("/styles")
    def style_state(persona_id: str, relationship_id: str) -> dict:
        return data.style_state(persona_id, relationship_id)

    @router.put("/styles")
    async def save_style(body: StyleInput) -> dict:
        return await _finish_operation(
            mutate(
                [{"persona_id": body.persona_id, "relationship_id": body.relationship_id}],
                lambda: data.save_style(**body.model_dump()),
            )
        )

    @router.patch("/memories/{memory_id}")
    async def patch_memory(memory_id: str, body: MemoryPatch) -> dict:
        options = body.model_dump(exclude_unset=True)
        return await _finish_operation(
            mutate(
                [{"persona_id": body.persona_id, "relationship_id": body.relationship_id}],
                lambda: data.update_memory(memory_id, **options),
            )
        )

    @router.get("/identities")
    def identities(persona_id: str) -> dict:
        return data.identities(persona_id)

    @router.put("/identities/remap")
    async def remap(body: IdentityRemap) -> dict:
        scopes = [
            {"persona_id": p, "relationship_id": r}
            for p, r in remap_scopes(data, body.persona_id, body.source_account_id)
        ]
        return await _finish_operation(
            mutate(scopes, lambda: data.remap_identity(**body.model_dump()), stop=True)
        )

    @router.get("/imports")
    def list_imports(persona_id: str, relationship_id: str) -> list[dict]:
        data.require_scope(persona_id, relationship_id)
        return [
            row["payload"]
            for row in store.rows(imports)
            if row["payload"].get("persona_id") == persona_id
            and row["payload"].get("relationship_id") == relationship_id
        ]

    @router.get("/imports/{batch_id}/deletion-impact")
    def deletion_impact(batch_id: str, persona_id: str, relationship_id: str) -> dict:
        return data.deletion_impact(batch_id, persona_id, relationship_id)

    @router.delete("/imports/{batch_id}")
    async def delete_import(
        batch_id: str, persona_id: str, relationship_id: str, body: DeleteInput
    ) -> dict:
        preview = data.deletion_impact(batch_id, persona_id, relationship_id)
        if preview["impact_hash"] != body.impact_hash:
            raise DomainError("STALE_DELETION_PREVIEW", "Deletion impact changed; preview again")
        return await _finish_operation(
            mutate(
                preview["affected_scopes"],
                lambda: data.delete_import(batch_id, persona_id, relationship_id, body.impact_hash),
                stop=True,
            )
        )

    @router.get("/datasets")
    def list_datasets(persona_id: str, relationship_id: str) -> list[dict]:
        data.require_scope(persona_id, relationship_id)
        result = [
            {
                **row["payload"],
                "status": row["payload"].get("status", "ready"),
                "path": str(store.root / "datasets" / row["id"]),
            }
            for row in store.rows(
                datasets,
                datasets.c.persona_id == persona_id,
                datasets.c.relationship_id == relationship_id,
            )
        ]
        # Initial page selection should use the newest valid snapshot, while
        # retaining old versions for provenance and explicit comparison.
        return sorted(
            result, key=lambda item: (item.get("created_at", ""), item["id"]), reverse=True
        )

    @router.get("/datasets/{dataset_id}/preview")
    def preview_dataset(dataset_id: str, persona_id: str, relationship_id: str) -> dict:
        data.require_scope(persona_id, relationship_id)
        found = store.rows(
            datasets,
            datasets.c.id == dataset_id,
            datasets.c.persona_id == persona_id,
            datasets.c.relationship_id == relationship_id,
        )
        if not found:
            raise DomainError("DATASET_NOT_FOUND", "Dataset not found in this scope", 404)
        manifest = found[0]["payload"]
        if manifest.get("status") == "revoked":
            raise DomainError(
                "DATASET_REVOKED", "Dataset source was revoked; samples are unavailable", 409
            )
        root = (store.root / "datasets" / dataset_id).resolve()
        if root.parent != (store.root / "datasets").resolve():
            raise DomainError("DATASET_PATH", "Invalid managed dataset path", 422)
        samples: dict[str, list[Any]] = {}
        for split in ("train", "validation", "test"):
            path: Path = root / f"{split}.jsonl"
            if (
                not path.is_file()
                or path.is_symlink()
                or file_hash(path) != manifest["files"].get(path.name)
            ):
                raise DomainError("DATASET_HASH", "Dataset file is missing or changed", 409)
            with path.open(encoding="utf-8") as handle:
                samples[split] = []
                for _, line in zip(range(5), handle):
                    samples[split].append(json.loads(line))
        return {"manifest": manifest, "examples": samples}

    return router
