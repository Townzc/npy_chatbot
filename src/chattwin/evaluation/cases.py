"""Read reviewed scenarios or derive cases strictly from a frozen test split."""

import json
from contextlib import nullcontext
from pathlib import Path

from filelock import FileLock

from chattwin.domain import DomainError
from chattwin.storage import datasets
from chattwin.training.spec import canonical_hash, sha256_file

from .contracts import EvaluationCase


def read_cases(path: Path) -> list[EvaluationCase]:
    if path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("case file must be a regular JSONL file under 16 MiB")
    cases = [
        EvaluationCase.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    if not cases or len(cases) > 1000 or len({case.id for case in cases}) != len(cases):
        raise ValueError("case IDs must be unique; provide 1–1000 cases")
    return cases


def frozen_test_cases(
    data, dataset_id: str, persona_id: str, relationship_id: str, *, _locked=False
) -> list[EvaluationCase]:
    with (
        nullcontext() if _locked else FileLock(data.store.root / "data-management.lock", timeout=30)
    ):
        data.require_scope(persona_id, relationship_id)
        records = data.store.rows(
            datasets,
            datasets.c.id == dataset_id,
            datasets.c.persona_id == persona_id,
            datasets.c.relationship_id == relationship_id,
        )
        if not records or records[0]["payload"].get("status") == "revoked":
            raise DomainError("DATASET_REVOKED", "Evaluation dataset absent or revoked", 409)
        registered = records[0]["payload"]
        # IDs come from the registry, but also require a single safe path component.
        if Path(dataset_id).name != dataset_id or dataset_id in {".", ".."}:
            raise ValueError("invalid dataset ID")
        root = data.store.root / "datasets" / dataset_id
        if root.is_symlink():
            raise ValueError("dataset symlinks are not allowed")
        manifest = json.loads((root / "manifest.json").read_text())
        digest = canonical_hash(
            {k: v for k, v in manifest.items() if k not in {"dataset_hash", "path"}}
        )
        if (
            manifest.get("dataset_hash") != digest
            or registered.get("dataset_hash") != digest
            or (manifest.get("persona_id"), manifest.get("relationship_id"))
            != (persona_id, relationship_id)
        ):
            raise ValueError("evaluation dataset hash/scope changed")
        for name in ("train.jsonl", "validation.jsonl", "test.jsonl"):
            if (root / name).is_symlink() or sha256_file(root / name) != manifest["files"][name]:
                raise ValueError("frozen dataset file hash changed")
        segments = {segment["id"]: segment for segment in manifest["segments"]}
        cases = []
        for line in (root / "test.jsonl").read_text().splitlines():
            example = json.loads(line)
            segment = segments[example["segment_id"]]
            turns = example["messages"]
            if (
                segment["split"] != "test"
                or example["target_index"] != len(turns) - 1
                or turns[-1]["role"] != "assistant"
                or not set(example["source_message_ids"]).issubset(segment["source_message_ids"])
                or not set(example["target_message_ids"]).issubset(example["source_message_ids"])
            ):
                raise ValueError("frozen test lineage is inconsistent")
            cases.append(
                EvaluationCase(
                    id=example["id"],
                    category="multi_turn" if len(turns) > 2 else "style",
                    messages=turns[:-1],
                    reference=turns[-1]["content"],
                    rubric="独立评估风格、适用性、事实依据、隐私和未经授权的承诺；参考回答不是唯一正确答案。",
                    source_cutoff=segment["start"],
                    provenance="frozen_test",
                    synthetic=bool(manifest.get("synthetic", False)),
                    dataset_id=dataset_id,
                    dataset_hash=digest,
                    example_id=example["id"],
                    source_message_ids=example["source_message_ids"],
                    target_message_ids=example["target_message_ids"],
                )
            )
        if not cases:
            raise ValueError("frozen dataset has no independent test examples")
        return cases


def validate_case_lineage(data, cases: list[EvaluationCase], spec) -> None:
    frozen = {}
    for case in cases:
        if case.provenance != "frozen_test":
            continue
        assert case.dataset_id is not None
        if case.dataset_id not in frozen:
            frozen[case.dataset_id] = {
                item.id: item
                for item in frozen_test_cases(
                    data, case.dataset_id, spec.persona_id, spec.relationship_id, _locked=True
                )
            }
        expected = frozen[case.dataset_id].get(case.id)
        if expected is None or expected != case:
            raise ValueError("case differs from its frozen test example")
