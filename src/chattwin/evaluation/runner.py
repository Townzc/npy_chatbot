"""Serial, private, genuine HTTP comparisons. Never invokes any message channel."""

import asyncio
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
from filelock import FileLock

from chattwin.domain import DomainError, GenerationRequest, now, uid
from chattwin.models import HTTPProvider
from chattwin.training.spec import canonical_hash, private_output, sha256_file
from chattwin.training.worker import verify_artifact

from .contracts import EvaluationCase, EvaluationSpec
from .prompts import prepare_prompts


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        os.chmod(temporary, 0o600)
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


async def acquire_lock(lock) -> None:
    # A cancelled to_thread await does not cancel flock acquisition. Drain it
    # before propagating cancellation so a background thread cannot leak a lock.
    pending = asyncio.create_task(asyncio.to_thread(lock.acquire))
    try:
        await asyncio.shield(pending)
    except asyncio.CancelledError:
        await pending
        lock.release()
        raise


class EvaluationRunner:
    def __init__(self, store, data, registry):
        self.store, self.data, self.registry = store, data, registry

    def _model_records(self, spec):
        result = {}
        for kind, deployment_id in (
            ("base", spec.base_deployment_id),
            ("adapter", spec.adapter_deployment_id),
        ):
            if not deployment_id or (kind == "adapter" and "B3" not in spec.variants):
                continue
            deployment = self.registry.deployment(deployment_id)
            if (deployment.persona_id, deployment.relationship_id) != (
                spec.persona_id,
                spec.relationship_id,
            ):
                raise DomainError("MODEL_SCOPE_MISMATCH", "Evaluation endpoint scope differs", 403)
            if kind == "base" and deployment.artifact_id:
                raise ValueError("B0–B2 must use a base deployment without an adapter")
            record = {
                "deployment": deployment.model_dump(mode="json"),
                "pin": spec.base_pin.model_dump(),
                "identity_evidence": "health_verified",
            }
            if kind == "adapter":
                if not deployment.artifact_id:
                    raise DomainError("ADAPTER_REQUIRED", "B3 requires a registered adapter", 422)
                artifact = self.registry.artifact(
                    deployment.artifact_id, spec.persona_id, spec.relationship_id
                )
                path = Path(artifact["artifact_path"])
                training_spec, manifest = verify_artifact(path)
                if sha256_file(path / "manifest.json") != artifact["manifest_hash"]:
                    raise ValueError("registered adapter manifest changed")
                if any(manifest[key] != value for key, value in spec.base_pin.model_dump().items()):
                    raise ValueError("B3 must use the same frozen base/tokenizer/template as B0–B2")
                if spec.mode == "formal" and (
                    training_spec.synthetic_smoke or manifest.get("evidence") != "real_training"
                ):
                    raise ValueError("tiny synthetic training is not formal evaluation evidence")
                record["artifact_id"] = artifact["id"]
                record["artifact_manifest_hash"] = artifact["manifest_hash"]
                record["dataset_hash"] = manifest["dataset_hash"]
                record["dataset_version"] = manifest["dataset_version"]
                record["training_evidence"] = manifest["evidence"]
            if spec.mode == "synthetic-protocol":
                record["identity_evidence"] = "synthetic_protocol_only"
            record["model_version_hash"] = canonical_hash(record)
            result[kind] = record
        return result

    async def _verify_health(self, record, spec):
        deployment = record["deployment"]
        if spec.mode == "synthetic-protocol" and "artifact_id" not in record:
            return
        try:
            key = os.environ.get(deployment["key_env"], "")
            async with (
                asyncio.timeout(10),
                httpx.AsyncClient(
                    timeout=10, follow_redirects=False, transport=self.registry.transport
                ) as client,
            ):
                response = await client.get(
                    deployment["endpoint"].removesuffix("/v1") + "/health",
                    headers={"Authorization": "Bearer " + key} if key else {},
                )
                response.raise_for_status()
                health = response.json()
            expected = (
                {
                    "artifact_manifest_hash": record["artifact_manifest_hash"],
                    "persona_id": spec.persona_id,
                    "relationship_id": spec.relationship_id,
                    "model": deployment["model"],
                }
                if "artifact_id" in record
                else spec.base_pin.model_dump()
            )
            if any(health.get(key) != value for key, value in expected.items()):
                raise ValueError("identity mismatch")
            if "artifact_id" not in record and health.get("artifact_manifest_hash"):
                # The built-in shared PEFT server exposes a genuine disable_adapter
                # base route. Reject accidentally naming its adapter as the baseline.
                if deployment["model"] != "chattwin-base" or "chattwin-base" not in health.get(
                    "models", []
                ):
                    raise ValueError("baseline endpoint is serving an adapter")
        except (httpx.HTTPError, KeyError, ValueError, TypeError, TimeoutError) as exc:
            raise DomainError(
                "EVALUATION_MODEL_IDENTITY", "Endpoint model identity could not be verified", 422
            ) from exc

    async def run(self, spec: EvaluationSpec, cases: list[EvaluationCase]) -> dict:
        if (
            not cases
            or len(cases) > spec.max_cases
            or len({case.id for case in cases}) != len(cases)
        ):
            raise ValueError("cases must have unique IDs within the explicit case budget")
        if spec.mode == "formal" and any(case.synthetic for case in cases):
            raise ValueError("synthetic scenarios cannot become formal quality evidence")
        if spec.mode == "synthetic-protocol" and not all(case.synthetic for case in cases):
            raise ValueError("synthetic-protocol mode accepts explicitly synthetic scenarios only")
        root = private_output(self.store.root / "evaluations")
        run_id = uid()
        output = root / run_id
        evidence = (
            "synthetic_protocol_only" if spec.mode == "synthetic-protocol" else "real_http_unscored"
        )
        manifest: dict[str, Any] = {
            "id": run_id,
            "schema_version": "1.0",
            "status": "preparing",
            "persona_id": spec.persona_id,
            "relationship_id": spec.relationship_id,
            "source_message_ids": sorted(
                {source for case in cases for source in case.source_message_ids}
            ),
            "evidence": evidence,
            "quality_accepted": False,
            "auto_promoted": False,
            "created_at": now().isoformat(),
            "spec": spec.model_dump(mode="json"),
            "cases_hash": canonical_hash(
                {"cases": [case.model_dump(mode="json") for case in cases]}
            ),
            "case_count": len(cases),
            "category_counts": dict(Counter(case.category for case in cases)),
            "recommended_scenario_count": 100,
            "expected_requests": len(cases) * len(spec.variants),
            "completed_requests": 0,
            "failed_requests": 0,
            "limitation": "HTTP identity is endpoint attestation; scoring requires independent human review.",
        }
        results = []
        lock = FileLock(self.store.root / "data-management.lock", timeout=35, thread_local=False)
        try:
            await acquire_lock(lock)
            try:
                records = self._model_records(spec)
                if "adapter" in records and any(
                    case.provenance == "frozen_test"
                    and (
                        case.dataset_id != records["adapter"]["dataset_version"]
                        or case.dataset_hash != records["adapter"]["dataset_hash"]
                    )
                    for case in cases
                ):
                    raise ValueError(
                        "frozen test cases must come from the adapter's training dataset split"
                    )
                prepared = prepare_prompts(self.data, spec, cases)
                # A caller may have read frozen cases before source deletion.
                # Validate under the deletion lock before copying any private text.
                root.mkdir(mode=0o700, exist_ok=True)
                output.mkdir(mode=0o700)
                manifest["models"] = records
                manifest["source_message_ids"] = sorted(
                    set(
                        [source for case in cases for source in case.source_message_ids]
                        + [source for prompt in prepared for source in prompt["source_message_ids"]]
                    )
                )
                manifest["status"] = "running"
                manifest["prompts_hash"] = canonical_hash({"prepared": prepared})
                # Write lineage before any text: even a crash during a later write
                # leaves enough provenance for source deletion to remove the run.
                write_json(output / "manifest.json", manifest)
                write_json(output / "cases.json", [case.model_dump(mode="json") for case in cases])
                write_json(output / "prompts.json", prepared)
                write_json(output / "manifest.json", manifest)
            finally:
                lock.release()
            for record in records.values():
                await self._verify_health(record, spec)
            providers = {
                kind: HTTPProvider(
                    record["deployment"]["endpoint"],
                    record["deployment"]["model"],
                    os.environ.get(record["deployment"]["key_env"], ""),
                    max_calls=manifest["expected_requests"],
                    transport=self.registry.transport,
                )
                for kind, record in records.items()
            }
            for case, prompt in zip(cases, prepared, strict=True):
                for variant in spec.variants:
                    kind = "adapter" if variant == "B3" else "base"
                    record = records[kind]
                    result = {
                        "id": uid(),
                        "case_id": case.id,
                        "category": case.category,
                        "variant": variant,
                        "evidence": evidence,
                        "synthetic": case.synthetic,
                        "persona_id": spec.persona_id,
                        "relationship_id": spec.relationship_id,
                        "model_version_hash": record["model_version_hash"],
                        "prompt_hash": prompt["prompt_hashes"][variant],
                        "status": "failed",
                        "input_tokens": None,
                        "output_tokens": None,
                        "token_usage_reported": False,
                    }
                    started = time.monotonic()
                    await acquire_lock(lock)
                    try:
                        if not output.is_dir():
                            raise DomainError(
                                "EVALUATION_REVOKED", "Evaluation source was removed", 409
                            )
                        # Source mutation cannot race transmission. The shared data lock
                        # is held only for this bounded HTTP request, never across the run.
                        if self._model_records(spec) != records:
                            raise DomainError(
                                "EVALUATION_MODEL_CHANGED", "Model lineage changed", 409
                            )
                        current = prepare_prompts(self.data, spec, [case])[0]
                        if current != prompt:
                            raise DomainError(
                                "EVALUATION_SOURCES_CHANGED", "Replay sources changed", 409
                            )
                        await self._verify_health(record, spec)
                        async with asyncio.timeout(35):
                            generated = await providers[kind].generate(
                                GenerationRequest(
                                    persona_id=spec.persona_id,
                                    relationship_id=spec.relationship_id,
                                    messages=prompt["prompts"][variant],
                                    max_tokens=spec.max_tokens,
                                    temperature=spec.temperature,
                                )
                            )
                        if generated.synthetic and spec.mode == "formal":
                            raise DomainError(
                                "MOCK_EVALUATION_REJECTED", "Mock is not HTTP evaluation", 422
                            )
                        result.update(
                            status="succeeded",
                            response=generated.text,
                            input_tokens=generated.input_tokens,
                            output_tokens=generated.output_tokens,
                            token_usage_reported=generated.usage_reported,
                        )
                    except DomainError as exc:
                        result["error_code"] = exc.code
                    except (ValueError, OSError, KeyError):
                        result["error_code"] = "EVALUATION_INPUT_INVALIDATED"
                    except TimeoutError:
                        result["error_code"] = "EVALUATION_MODEL_TIMEOUT"
                    finally:
                        try:
                            if not output.is_dir():
                                raise DomainError(
                                    "EVALUATION_REVOKED", "Evaluation source was removed", 409
                                )
                            result["duration_ms"] = round((time.monotonic() - started) * 1000)
                            results.append(result)
                            manifest["completed_requests"] += 1
                            manifest["failed_requests"] += result["status"] == "failed"
                            write_json(output / "results.json", results)
                            write_json(output / "manifest.json", manifest)
                        finally:
                            lock.release()
            manifest["status"] = (
                "completed_with_failures" if manifest["failed_requests"] else "completed"
            )
        except BaseException as exc:
            manifest["status"] = (
                "interrupted"
                if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError))
                else "failed"
            )
            manifest["error_code"] = (
                exc.code if isinstance(exc, DomainError) else "EVALUATION_SETUP_FAILED"
            )
            raise
        finally:
            manifest["results_hash"] = canonical_hash({"results": results})
            manifest["updated_at"] = now().isoformat()
            await acquire_lock(lock)
            try:
                if output.is_dir():
                    write_json(output / "manifest.json", manifest)
            finally:
                lock.release()
        return {"id": run_id, "output_path": str(output), "report": manifest}
