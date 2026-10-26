"""Strict canonical sidecars. A manifest is evidence, never identity permission."""

from __future__ import annotations

import json
from pathlib import Path

from chattwin.domain import DomainError


def prepare_manifest(path: Path, fmt: str, mapping: dict) -> tuple[dict, dict | None]:
    from .parsers import _json_lines, file_hash

    result = {key: value for key, value in mapping.items() if not key.startswith("_manifest_")}
    if fmt not in {"canonical", "canonical_jsonl"}:
        if "manifest" in mapping:
            raise DomainError(
                "MANIFEST_FORMAT", "A canonical sidecar cannot authorize another file format", 422
            )
        return result, None
    manifest = mapping.get("manifest")
    companion = path.with_suffix(path.suffix + ".manifest.json")
    if manifest is None and companion.is_file():
        if companion.stat().st_size > 256 * 1024:
            raise DomainError("MANIFEST_SIZE", "Canonical manifest must not exceed 256 KiB", 422)
        try:
            manifest = json.loads(companion.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            raise DomainError("MANIFEST_INVALID", "Manifest must be UTF-8 JSON", 422) from None
    if manifest is None:
        return result, None
    if not isinstance(manifest, dict) or len(json.dumps(manifest)) > 256 * 1024:
        raise DomainError("MANIFEST_INVALID", "Manifest must be a bounded JSON object", 422)
    required = {
        "schema_version",
        "file_sha256",
        "count",
        "persona_id",
        "relationship_id",
        "conversations",
    }
    if not required.issubset(manifest) or manifest["schema_version"] != "1.0":
        raise DomainError(
            "MANIFEST_FIELDS",
            "Manifest requires schema 1.0, hash, count, Persona, relationship and explicit conversation kinds",
            422,
        )
    if manifest["file_sha256"] != file_hash(path):
        raise DomainError(
            "MANIFEST_HASH", "Manifest hash does not match the supplied message file", 422
        )
    if type(manifest["count"]) is not int or manifest["count"] < 0:
        raise DomainError("MANIFEST_COUNT", "Manifest count must be a nonnegative integer", 422)
    if not all(
        isinstance(manifest[key], str) and manifest[key]
        for key in ("persona_id", "relationship_id")
    ):
        raise DomainError(
            "MANIFEST_SCOPE", "Manifest must identify source Persona and relationship", 422
        )
    declared = manifest["conversations"]
    if not isinstance(declared, list):
        raise DomainError("MANIFEST_KIND", "Manifest conversations must be a list", 422)
    kinds = {}
    for item in declared:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or item.get("kind") not in {"private", "group"}
            or item["id"] in kinds
        ):
            raise DomainError(
                "MANIFEST_KIND",
                "Each conversation needs a unique ID and explicit private/group kind",
                422,
            )
        kinds[item["id"]] = item["kind"]
    count, actual_conversations = 0, set()
    for _, record, error in _json_lines(path):
        if error:
            raise DomainError(
                "MANIFEST_RECORD", "Cannot validate a manifest against malformed records", 422
            )
        count += 1
        conversation = record.get("conversation_id")
        if not isinstance(conversation, str) or not isinstance(record.get("provenance", {}), dict):
            raise DomainError(
                "MANIFEST_RECORD",
                "Canonical conversation/provenance fields have invalid types",
                422,
            )
        actual_conversations.add(conversation)
        if conversation not in kinds:
            raise DomainError(
                "MANIFEST_KIND", "A record conversation is absent from the manifest", 422
            )
        recorded_kind = record.get("provenance", {}).get("conversation_kind")
        if recorded_kind in {"private", "group"} and recorded_kind != kinds[conversation]:
            raise DomainError("MANIFEST_KIND", "Manifest kind conflicts with source record", 422)
        context = record.get("use_context")
        if context is not None and not isinstance(context, dict):
            raise DomainError("MANIFEST_SCOPE", "Canonical use context must be an object", 422)
        if (
            record.get("relationship_id") is not None
            and record["relationship_id"] != manifest["relationship_id"]
        ):
            raise DomainError(
                "MANIFEST_SCOPE", "Record relationship conflicts with manifest scope", 422
            )
        if context and (
            context.get("persona_id") != manifest["persona_id"]
            or context.get("relationship_id") != manifest["relationship_id"]
        ):
            raise DomainError("MANIFEST_SCOPE", "Record scope conflicts with manifest scope", 422)
    if count != manifest["count"]:
        raise DomainError("MANIFEST_COUNT", "Manifest count does not match message records", 422)
    if actual_conversations != set(kinds):
        raise DomainError(
            "MANIFEST_KIND", "Manifest contains conversations absent from this file", 422
        )
    # Only this validated internal map can supply missing conversation kind.
    result["_manifest_conversations"] = kinds
    return result, {
        "present": True,
        "hash_verified": True,
        "count_verified": True,
        "count": count,
        "persona_id": manifest["persona_id"],
        "relationship_id": manifest["relationship_id"],
        "conversations": declared,
    }
