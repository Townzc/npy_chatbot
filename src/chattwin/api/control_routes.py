"""Authenticated, scoped resolution of uncertain sends. Never resends a message."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import Field, model_validator

from chattwin.domain import Contract


class ReconcileInput(Contract):
    binding_id: str = Field(min_length=1)


class ResolveInput(ReconcileInput):
    outcome: Literal["sent", "not_sent"]
    platform_message_id: str | None = Field(default=None, min_length=1, max_length=200)
    evidence: str = Field(min_length=6, max_length=2000)
    expected_control_epoch: int = Field(ge=0)

    @model_validator(mode="after")
    def observation(self):
        if self.outcome == "not_sent" and self.platform_message_id:
            raise ValueError("not_sent cannot include a sent platform message ID")
        if len(self.evidence.strip()) < 6:
            raise ValueError("Describe the actual platform check, not a timeout guess")
        return self


def control_router(store, get_coordinator, authenticate):
    router = APIRouter(
        prefix="/api/v1", dependencies=[Depends(authenticate)], tags=["send-reconciliation"]
    )

    @router.get("/outbox/unresolved")
    def unresolved(binding_id: str) -> dict:
        return get_coordinator().unresolved(binding_id)

    @router.post("/outbox/{outbox_id}/reconcile")
    async def reconcile(outbox_id: str, body: ReconcileInput) -> dict:
        return await get_coordinator().reconcile_unknown(body.binding_id, outbox_id)

    @router.post("/outbox/{outbox_id}/resolve")
    async def resolve(outbox_id: str, body: ResolveInput) -> dict:
        return await get_coordinator().resolve_unknown(outbox_id=outbox_id, **body.model_dump())

    return router
