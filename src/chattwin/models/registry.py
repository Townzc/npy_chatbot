"""Artifact lineage and immutable scoped model deployment versions."""

import json
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends
from pydantic import Field, field_validator
from sqlalchemy import select

from chattwin.domain import Contract, DomainError, GenerationRequest, Scope, now, uid
from chattwin.models import HTTPProvider
from chattwin.storage import (
    artifacts,
    audit,
    datasets,
    model_deployments,
    outbox,
    relationships,
    sessions,
)
from chattwin.training.spec import sha256_file, validate_scope
from chattwin.training.worker import verify_artifact


class ArtifactRegistration(Scope):
    artifact_path: str = Field(min_length=1, max_length=4096)


class ArtifactRecord(Scope):
    id: str
    artifact_path: str
    status: str
    manifest: dict
    manifest_hash: str
    created_at: str
    revoked_at: str | None = None
    revoked_reason: str | None = None
    restore_requires_verification: bool = False
    weights_forgotten: bool = False
    deployment_status: str | None = None
    restore_reason: str | None = None


class DeploymentInput(Scope):
    artifact_id: str | None = None
    endpoint: str
    model: str = Field(min_length=1, max_length=200)
    key_env: str = Field(
        default="CHATTWIN_MODEL_KEY", pattern=r"^CHATTWIN_MODEL_KEY(?:_[A-Z0-9_]+)?$"
    )
    label: str = Field(min_length=1, max_length=100)

    @field_validator("endpoint")
    @classmethod
    def endpoint_url(cls, value):
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Use an HTTP(S) endpoint without credentials, query or fragment")
        if parsed.scheme == "http" and parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
            "testserver",
        }:
            raise ValueError("Remote model endpoints require HTTPS")
        return value.rstrip("/")


class DeploymentRecord(DeploymentInput):
    id: str
    status: str
    created_at: str
    verified_at: str | None = None
    probe: dict | None = None
    revoked_at: str | None = None
    revoked_reason: str | None = None
    restore_requires_verification: bool = False


class ActivateDeployment(Contract):
    binding_id: str
    expected_control_epoch: int


class DeploymentTest(Contract):
    status: Literal["ready"]
    probe: dict


class ModelRegistry:
    def __init__(self, store, default_provider, get_coordinator, *, transport=None, budget=None):
        self.store, self.default_provider, self.get_coordinator = (
            store,
            default_provider,
            get_coordinator,
        )
        self.transport = transport
        self.budget = budget
        self.providers: dict[str, HTTPProvider] = {}

    def require_scope(self, persona_id, relationship_id):
        if not self.store.rows(
            relationships,
            relationships.c.persona_id == persona_id,
            relationships.c.id == relationship_id,
        ):
            raise DomainError("SCOPE_MISMATCH", "Relationship does not belong to this Persona", 403)

    def artifact(self, artifact_id, persona_id, relationship_id):
        rows = self.store.rows(
            artifacts,
            artifacts.c.id == artifact_id,
            artifacts.c.persona_id == persona_id,
            artifacts.c.relationship_id == relationship_id,
        )
        if not rows:
            raise DomainError("ARTIFACT_NOT_FOUND", "Artifact not found in this relationship", 404)
        item = rows[0]["payload"]
        if item.get("status") != "validated" or item.get("restore_requires_verification"):
            raise DomainError("ARTIFACT_REVOKED", "Artifact is revoked or must be revalidated")
        version = self.store.rows(datasets, datasets.c.id == item["manifest"]["dataset_version"])
        if not version or version[0]["payload"].get("status") == "revoked":
            raise DomainError(
                "DATASET_REVOKED", "Artifact source dataset is unavailable or revoked"
            )
        return item

    def register(self, body: ArtifactRegistration) -> ArtifactRecord:
        self.require_scope(body.persona_id, body.relationship_id)
        path = Path(body.artifact_path).expanduser().resolve()
        if any((p / ".git").exists() for p in (path, *path.parents)):
            raise DomainError(
                "PRIVATE_ARTIFACT_PATH", "Private model artifacts must remain outside Git", 422
            )
        try:
            spec, manifest = verify_artifact(path)
            validate_scope(manifest, body.persona_id, body.relationship_id)
            status = json.loads((path / "status.json").read_text())
            if status.get("status") != "succeeded":
                raise ValueError("training has not successfully completed and reloaded")
            source = self.store.rows(
                datasets,
                datasets.c.id == spec.dataset_version,
                datasets.c.persona_id == body.persona_id,
                datasets.c.relationship_id == body.relationship_id,
            )
            if (
                not source
                or source[0]["payload"].get("dataset_hash") != spec.dataset_hash
                or source[0]["payload"].get("status") == "revoked"
            ):
                raise ValueError("source dataset is absent, changed, or revoked")
        except (OSError, ValueError, KeyError) as exc:
            raise DomainError(
                "INVALID_ARTIFACT", "Artifact status, hashes or source scope failed validation", 422
            ) from exc
        result = ArtifactRecord(
            **body.model_dump(),
            id=uid(),
            status="validated",
            manifest=manifest,
            manifest_hash=sha256_file(path / "manifest.json"),
            created_at=now().isoformat(),
        )
        result.artifact_path = str(path)
        with self.store.transaction() as conn:
            # Serialize registration with source revocation. Files were checked
            # outside the writer transaction so long hashes never delay takeover.
            current = conn.execute(
                select(datasets.c.payload).where(datasets.c.id == spec.dataset_version)
            ).scalar_one_or_none()
            if (
                not current
                or current.get("status") == "revoked"
                or current.get("dataset_hash") != spec.dataset_hash
            ):
                raise DomainError("DATASET_REVOKED", "Dataset changed during artifact validation")
            conn.execute(
                artifacts.insert().values(
                    id=result.id,
                    persona_id=result.persona_id,
                    relationship_id=result.relationship_id,
                    payload=result.model_dump(),
                )
            )
        return result

    def create(self, body: DeploymentInput) -> DeploymentRecord:
        self.require_scope(body.persona_id, body.relationship_id)
        if body.artifact_id:
            self.artifact(body.artifact_id, body.persona_id, body.relationship_id)
        result = DeploymentRecord(
            **body.model_dump(), id=uid(), status="unverified", created_at=now().isoformat()
        )
        with self.store.transaction() as conn:
            if result.artifact_id:
                current = conn.execute(
                    select(artifacts.c.payload).where(artifacts.c.id == result.artifact_id)
                ).scalar_one_or_none()
                if not current or current.get("status") != "validated":
                    raise DomainError(
                        "ARTIFACT_REVOKED", "Artifact was revoked during deployment registration"
                    )
            conn.execute(
                model_deployments.insert().values(
                    id=result.id,
                    persona_id=result.persona_id,
                    relationship_id=result.relationship_id,
                    artifact_id=result.artifact_id,
                    status=result.status,
                    payload=result.model_dump(),
                )
            )
        return result

    def deployment(self, deployment_id, *, verified=True):
        rows = self.store.rows(model_deployments, model_deployments.c.id == deployment_id)
        if not rows:
            raise DomainError("DEPLOYMENT_NOT_FOUND", "Model deployment not found", 404)
        row = rows[0]
        if (
            row["status"] == "revoked"
            or row["payload"].get("restore_requires_verification")
            or (verified and row["status"] not in {"ready", "active"})
        ):
            raise DomainError(
                "DEPLOYMENT_UNAVAILABLE", "Model deployment is not validated or was revoked"
            )
        result = DeploymentRecord.model_validate(row["payload"])
        if result.artifact_id:
            self.artifact(result.artifact_id, result.persona_id, result.relationship_id)
        return result

    def provider(self, deployment_id, persona_id, relationship_id):
        if deployment_id == "mock-v1":
            return self.default_provider
        dep = self.deployment(deployment_id)
        if (dep.persona_id, dep.relationship_id) != (persona_id, relationship_id):
            raise DomainError(
                "MODEL_SCOPE_MISMATCH", "Adapter or endpoint belongs to another relationship", 403
            )
        if deployment_id not in self.providers:
            self.providers[deployment_id] = HTTPProvider(
                dep.endpoint, dep.model, os.environ.get(dep.key_env, ""), transport=self.transport
            )
        return self.providers[deployment_id]

    async def test(self, deployment_id) -> DeploymentTest:
        dep = self.deployment(deployment_id, verified=False)
        provider = HTTPProvider(
            dep.endpoint, dep.model, os.environ.get(dep.key_env, ""), transport=self.transport
        )
        if dep.artifact_id:
            artifact = self.artifact(dep.artifact_id, dep.persona_id, dep.relationship_id)
            try:
                async with httpx.AsyncClient(
                    timeout=10, transport=self.transport, follow_redirects=False
                ) as client:
                    response = await client.get(
                        dep.endpoint.removesuffix("/v1") + "/health",
                        headers={"Authorization": "Bearer " + os.environ[dep.key_env]}
                        if os.environ.get(dep.key_env)
                        else {},
                    )
                    response.raise_for_status()
                    health = response.json()
                if (
                    health.get("artifact_manifest_hash") != artifact["manifest_hash"]
                    or health.get("persona_id") != dep.persona_id
                    or health.get("relationship_id") != dep.relationship_id
                    or health.get("model") != dep.model
                ):
                    raise ValueError("endpoint serves a different adapter")
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                raise DomainError(
                    "MODEL_IDENTITY_MISMATCH",
                    "Endpoint adapter identity or scope could not be verified",
                    422,
                ) from exc
        request = GenerationRequest(
            persona_id=dep.persona_id,
            relationship_id=dep.relationship_id,
            messages=[
                {
                    "role": "user",
                    "content": "Reply with OK. This is a synthetic connectivity check.",
                }
            ],
            max_tokens=8,
        )
        reservation = (
            self.budget.reserve(request, provider.name, deployment_id, "probe")
            if self.budget
            else None
        )
        generated = None
        try:
            generated = await provider.generate(request)
        finally:
            if self.budget and reservation:
                self.budget.finish(reservation, generated)
        probe = {
            "model": generated.model,
            "synthetic": generated.synthetic,
            "input_tokens": generated.input_tokens,
            "output_tokens": generated.output_tokens,
        }
        with self.store.transaction() as conn:
            current = (
                conn.execute(
                    select(model_deployments).where(model_deployments.c.id == deployment_id)
                )
                .mappings()
                .one()
            )
            if current["status"] == "revoked":
                raise DomainError("DEPLOYMENT_REVOKED", "Deployment was revoked during test")
            payload = {
                **current["payload"],
                "status": "ready",
                "verified_at": now().isoformat(),
                "probe": probe,
            }
            conn.execute(
                model_deployments.update()
                .where(model_deployments.c.id == deployment_id)
                .values(status="ready", payload=payload)
            )
        self.providers[deployment_id] = provider
        return DeploymentTest(status="ready", probe=probe)

    async def activate(self, deployment_id, body: ActivateDeployment):
        coordinator = self.get_coordinator()
        async with coordinator.gate:
            with self.store.transaction() as conn:
                binding = coordinator._binding(conn, body.binding_id)
                if deployment_id != "mock-v1":
                    self.provider(deployment_id, binding.persona_id, binding.relationship_id)
                current = (
                    conn.execute(select(sessions).where(sessions.c.binding_id == body.binding_id))
                    .mappings()
                    .one()
                )
                if current["control_epoch"] != body.expected_control_epoch:
                    raise DomainError("STALE_EPOCH", "Refresh before changing model deployment")
                unresolved = conn.execute(
                    select(outbox.c.id).where(
                        outbox.c.binding_id == body.binding_id,
                        outbox.c.status.in_(["planned", "submitting", "unknown"]),
                        outbox.c.kind != "ai_reply",
                    )
                ).first()
                if unresolved:
                    raise DomainError(
                        "UNRESOLVED_NOTICE",
                        "Resolve required mode notification before switching models",
                    )
                old_id = current["payload"]["model_deployment_id"]
                if old_id != deployment_id:
                    payload = {
                        **current["payload"],
                        "previous_model_deployment_id": old_id,
                        "model_deployment_id": deployment_id,
                    }
                    conn.execute(
                        sessions.update()
                        .where(sessions.c.binding_id == body.binding_id)
                        .values(
                            mode="HUMAN" if current["mode"] == "HUMAN" else "PAUSED",
                            control_epoch=current["control_epoch"] + 1,
                            payload=payload,
                        )
                    )
                    conn.execute(
                        outbox.update()
                        .where(
                            outbox.c.binding_id == body.binding_id,
                            outbox.c.kind == "ai_reply",
                            outbox.c.status == "planned",
                        )
                        .values(status="cancelled")
                    )
                    conn.execute(
                        audit.insert().values(
                            id=uid(),
                            kind="model_deployment_changed",
                            payload={
                                "binding_id": body.binding_id,
                                "from": old_id,
                                "to": deployment_id,
                                "at": now().isoformat(),
                            },
                        )
                    )
        return {
            "status": coordinator.status(body.binding_id),
            "deployment_id": deployment_id,
            "reenable_required": True,
        }

    async def rollback(self, body: ActivateDeployment):
        current = self.get_coordinator().status(body.binding_id)
        previous = current["payload"].get("previous_model_deployment_id")
        if not previous:
            raise DomainError("NO_PREVIOUS_DEPLOYMENT", "No previous model deployment is recorded")
        return await self.activate(previous, body)


def model_router(registry: ModelRegistry, authenticate):
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)])

    @router.get("/model-artifacts", response_model=list[ArtifactRecord])
    def list_artifacts(persona_id: str, relationship_id: str):
        registry.require_scope(persona_id, relationship_id)
        return [
            r["payload"]
            for r in registry.store.rows(
                artifacts,
                artifacts.c.persona_id == persona_id,
                artifacts.c.relationship_id == relationship_id,
            )
        ]

    @router.post("/model-artifacts", response_model=ArtifactRecord)
    def register(body: ArtifactRegistration):
        return registry.register(body)

    @router.get("/model-deployments", response_model=list[DeploymentRecord])
    def list_deployments(persona_id: str, relationship_id: str):
        registry.require_scope(persona_id, relationship_id)
        return [
            r["payload"]
            for r in registry.store.rows(
                model_deployments,
                model_deployments.c.persona_id == persona_id,
                model_deployments.c.relationship_id == relationship_id,
            )
        ]

    @router.post("/model-deployments", response_model=DeploymentRecord)
    def create(body: DeploymentInput):
        return registry.create(body)

    @router.post("/model-deployments/{deployment_id}/test", response_model=DeploymentTest)
    async def test(deployment_id: str):
        return await registry.test(deployment_id)

    @router.post("/model-deployments/{deployment_id}/activate")
    async def activate(deployment_id: str, body: ActivateDeployment):
        return await registry.activate(deployment_id, body)

    @router.post("/model-deployments/rollback")
    async def rollback(body: ActivateDeployment):
        return await registry.rollback(body)

    return router
