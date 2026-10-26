"""Durable monthly reservations. Provider prices are explicit owner estimates."""

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import Field, model_validator
from sqlalchemy import select

from chattwin.domain import Contract, DomainError, GenerationRequest, GenerationResult, now, uid
from chattwin.storage import audit, personas, usage


class UsagePolicy(Contract):
    persona_id: str
    version: int = 0
    monthly_requests: int = Field(default=1000, ge=0, le=1000000)
    monthly_input_tokens: int = Field(default=1000000, ge=0, le=1000000000)
    monthly_output_tokens: int = Field(default=250000, ge=0, le=1000000000)
    input_usd_per_million: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    output_usd_per_million: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    monthly_usd: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)

    @model_validator(mode="after")
    def prices(self):
        if (self.input_usd_per_million is None) != (self.output_usd_per_million is None):
            raise ValueError("Provide both input and output prices")
        if self.monthly_usd is not None and self.input_usd_per_million is None:
            raise ValueError("Cost limit needs explicit provider prices")
        return self


class UsageSummary(Contract):
    policy: UsagePolicy
    month: str
    requests: int
    input_tokens: int
    output_tokens: int
    estimated_usd: float | None
    unresolved_requests: int
    alert: bool
    exhausted: bool
    note: str = "UTC 月份；价格由本人配置。未知消耗保留预留额，金额是估算，不是供应商账单。"


class BudgetService:
    def __init__(self, store):
        self.store = store

    def _policy(self, conn, persona_id):
        if not conn.execute(select(personas.c.id).where(personas.c.id == persona_id)).first():
            raise DomainError("PERSONA_NOT_FOUND", "Persona not found", 404)
        rows = (
            conn.execute(
                select(audit.c.payload).where(
                    audit.c.kind == "usage_policy",
                    audit.c.payload["persona_id"].as_string() == persona_id,
                )
            )
            .scalars()
            .all()
        )
        return (
            UsagePolicy.model_validate(max(rows, key=lambda p: p["version"]))
            if rows
            else UsagePolicy(persona_id=persona_id)
        )

    def _totals(self, conn, persona_id, month):
        rows = (
            conn.execute(
                select(usage.c.payload).where(
                    usage.c.persona_id == persona_id,
                    usage.c.payload["created_at"].as_string().startswith(month),
                )
            )
            .scalars()
            .all()
        )
        rows = [r for r in rows if not r.get("synthetic") and r.get("model") != "mock-v1"]
        return {
            "requests": len(rows),
            "input_tokens": sum(r.get("input_tokens", 0) for r in rows),
            "output_tokens": sum(r.get("output_tokens", 0) for r in rows),
            "unresolved_requests": sum(r.get("status") in {"reserved", "unknown"} for r in rows),
        }

    @staticmethod
    def _cost(policy, input_tokens, output_tokens):
        if policy.input_usd_per_million is None:
            return None
        return float(
            (
                Decimal(str(policy.input_usd_per_million)) * input_tokens
                + Decimal(str(policy.output_usd_per_million)) * output_tokens
            )
            / 1000000
        )

    def summary(self, persona_id):
        month = now().strftime("%Y-%m")
        with self.store.engine.connect() as conn:
            policy = self._policy(conn, persona_id)
            totals = self._totals(conn, persona_id, month)
        cost = self._cost(policy, totals["input_tokens"], totals["output_tokens"])
        ratios = [
            totals[k] / limit if limit else 1.0
            for k, limit in (
                ("requests", policy.monthly_requests),
                ("input_tokens", policy.monthly_input_tokens),
                ("output_tokens", policy.monthly_output_tokens),
            )
        ]
        if cost is not None and policy.monthly_usd is not None:
            ratios.append(cost / policy.monthly_usd if policy.monthly_usd else 1.0)
        return UsageSummary(
            policy=policy,
            month=month,
            **totals,
            estimated_usd=cost,
            alert=max(ratios) >= 0.8,
            exhausted=max(ratios) >= 1,
        )

    def update(self, body: UsagePolicy):
        with self.store.transaction() as conn:
            current = self._policy(conn, body.persona_id)
            if current.version != body.version:
                raise DomainError("STALE_BUDGET", "Refresh before changing budget")
            new = body.model_copy(update={"version": current.version + 1})
            conn.execute(
                audit.insert().values(id=uid(), kind="usage_policy", payload=new.model_dump())
            )
        return self.summary(body.persona_id)

    def reserve(self, request: GenerationRequest, model: str, deployment_id: str, variant: str):
        # UTF-8 byte length plus protocol overhead is a conservative local bound
        # for byte/token based chat services. Server-added hidden context or tools
        # can have additional costs, so no universal invoice guarantee is claimed.
        input_bound = sum(len(m["content"].encode("utf-8")) + 32 for m in request.messages) + 128
        output_bound = request.max_tokens
        timestamp = now().isoformat()
        with self.store.transaction() as conn:
            policy = self._policy(conn, request.persona_id)
            totals = self._totals(conn, request.persona_id, timestamp[:7])
            projected = (
                totals["requests"] + 1,
                totals["input_tokens"] + input_bound,
                totals["output_tokens"] + output_bound,
            )
            cost = self._cost(policy, projected[1], projected[2])
            if (
                projected[0] > policy.monthly_requests
                or projected[1] > policy.monthly_input_tokens
                or projected[2] > policy.monthly_output_tokens
                or (
                    cost is not None
                    and policy.monthly_usd is not None
                    and cost > policy.monthly_usd
                )
            ):
                raise DomainError(
                    "MONTHLY_BUDGET_EXHAUSTED",
                    "本月调用预算不足，AI 已暂停；调整预算后明确重新开启。",
                    429,
                )
            reservation = uid()
            conn.execute(
                usage.insert().values(
                    id=reservation,
                    persona_id=request.persona_id,
                    payload={
                        "created_at": timestamp,
                        "status": "reserved",
                        "model": model,
                        "deployment_id": deployment_id,
                        "variant": variant,
                        "relationship_id": request.relationship_id,
                        "input_tokens": input_bound,
                        "output_tokens": output_bound,
                        "policy_version": policy.version,
                    },
                )
            )
        return reservation

    def finish(self, reservation_id: str, result: GenerationResult | None):
        with self.store.transaction() as conn:
            row = conn.execute(select(usage).where(usage.c.id == reservation_id)).mappings().one()
            if row["payload"].get("status") != "reserved":
                return
            payload = {**row["payload"], "status": "unknown", "completed_at": now().isoformat()}
            if result and result.usage_reported:
                payload.update(
                    status="completed",
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                )
            conn.execute(usage.update().where(usage.c.id == reservation_id).values(payload=payload))


def usage_router(service: BudgetService, authenticate):
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)])

    @router.get("/usage", response_model=UsageSummary)
    def summary(persona_id: str):
        return service.summary(persona_id)

    @router.put("/usage/policy", response_model=UsageSummary)
    def update(body: UsagePolicy):
        return service.update(body)

    return router
