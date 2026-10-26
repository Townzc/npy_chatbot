"""Randomized human rating sheets; no generated or inferred quality scores."""

import csv
import json
import random
from functools import wraps
from pathlib import Path
from uuid import UUID

from filelock import FileLock

from chattwin.domain import now, uid
from chattwin.training.spec import canonical_hash, private_output

from .runner import write_json

RATINGS = (
    "style_score",
    "grounded_score",
    "sendable",
    "privacy_violation",
    "unauthorized_commitment",
)
VISIBLE = (
    "row_id",
    "case_id",
    "category",
    "evidence",
    "context",
    "response",
    "reference",
    "rubric",
)
FIELDS = (*VISIBLE, *RATINGS, "notes")


def evaluation_guard(function):
    @wraps(function)
    def guarded(run: Path, *args, **kwargs):
        if run.is_symlink() or run.parent.name != "evaluations" or str(UUID(run.name)) != run.name:
            raise ValueError("use a registered private evaluation run directory")
        with FileLock(run.parent.parent / "data-management.lock", timeout=35):
            return function(run, *args, **kwargs)

    return guarded


def _read_run(run: Path):
    run = private_output(run)
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["status"] not in {"completed", "completed_with_failures"}:
        raise ValueError("only completed runs can be rated")
    cases = json.loads((run / "cases.json").read_text())
    if canonical_hash({"cases": cases}) != manifest["cases_hash"]:
        raise ValueError("frozen cases changed")
    results = json.loads((run / "results.json").read_text())
    if canonical_hash({"results": results}) != manifest["results_hash"]:
        raise ValueError("frozen results changed")
    return manifest, {case["id"]: case for case in cases}, results


@evaluation_guard
def export_blind_sheet(run: Path) -> dict:
    """Private key stays separate from the CSV handed to an independent reviewer."""
    manifest, cases, results = _read_run(run)
    destination = run / "blind-review.csv"
    if destination.exists() or (run / "blind-key.json").exists():
        raise ValueError("a blind sheet already exists; preserve its assigned row IDs")
    rows, key = [], {}
    grouped: dict[str, list[dict]] = {}
    for result in results:
        if result["status"] == "succeeded":
            grouped.setdefault(result["case_id"], []).append(result)
    for case_id, candidates in grouped.items():
        random.SystemRandom().shuffle(candidates)
        case = cases[case_id]
        for result in candidates:
            row_id = uid()
            row = dict(
                zip(
                    VISIBLE,
                    (
                        row_id,
                        case_id,
                        case["category"],
                        manifest["evidence"],
                        json.dumps(case["messages"], ensure_ascii=False),
                        result["response"],
                        case["reference"],
                        case["rubric"],
                    ),
                    strict=True,
                )
            )
            # CSV quoting does not stop spreadsheet formulas in generated text.
            row = {
                field: (
                    "'" + value
                    if value.lstrip().startswith(("=", "+", "-", "@"))
                    or value.startswith(("\t", "\r", "\n"))
                    else value
                )
                for field, value in row.items()
            }
            key[row_id] = {
                "result_id": result["id"],
                "variant": result["variant"],
                "visible_hash": canonical_hash(row),
            }
            rows.append({**row, **dict.fromkeys(RATINGS, ""), "notes": ""})
    if not rows:
        raise ValueError("no successful model responses exist to review")
    with destination.open("x", encoding="utf-8", newline="") as handle:
        destination.chmod(0o600)
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    write_json(run / "blind-key.json", {"run_id": manifest["id"], "rows": key})
    return {
        "path": str(destination),
        "rows": len(rows),
        "evidence": manifest["evidence"],
        "warning": "Keep blind-key.json and results.json away from the reviewer until scoring.",
    }


@evaluation_guard
def summarize_scores(run: Path, csv_path: Path, reviewer: str) -> dict:
    if not reviewer.strip() or len(reviewer) > 100:
        raise ValueError("a human reviewer label is required")
    manifest, _cases, results = _read_run(run)
    key = json.loads((run / "blind-key.json").read_text())
    if key["run_id"] != manifest["id"]:
        raise ValueError("rating key belongs to another run")
    if csv_path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("rating file is too large")
    seen, graded = set(), []
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(FIELDS):
            raise ValueError("rating CSV columns changed")
        for row in reader:
            row_id = row["row_id"]
            if row_id in seen or row_id not in key["rows"]:
                raise ValueError("duplicate or unknown rating row")
            seen.add(row_id)
            if (
                canonical_hash({field: row[field] for field in VISIBLE})
                != key["rows"][row_id]["visible_hash"]
            ):
                raise ValueError("blind review content changed")
            values = [row[field].strip() for field in RATINGS]
            if not any(values):
                continue
            if not all(values):
                raise ValueError("complete every rating field for each reviewed response")
            if values[0] not in {"1", "2", "3", "4", "5"} or values[1] not in {
                "1",
                "2",
                "3",
                "4",
                "5",
            }:
                raise ValueError("style/grounded scores must be integer 1–5")
            if any(value not in {"0", "1"} for value in values[2:]):
                raise ValueError("sendable/privacy/commitment ratings must be 0 or 1")
            graded.append(
                {
                    "row_id": row_id,
                    "variant": key["rows"][row_id]["variant"],
                    **dict(zip(RATINGS, map(int, values), strict=True)),
                    "notes": row["notes"],
                }
            )
    if not graded:
        raise ValueError("no human ratings supplied; no quality score can be calculated")
    summary = {
        "run_id": manifest["id"],
        "reviewer": reviewer,
        "created_at": now().isoformat(),
        "evidence": manifest["evidence"],
        "quality_accepted": False,
        "auto_promoted": False,
        "acceptance_status": "human_decision_required",
        "case_count": manifest["case_count"],
        "rated_responses": len(graded),
        "successful_responses": len(key["rows"]),
        "failed_responses": sum(item["status"] != "succeeded" for item in results),
        "partial_review": len(graded) != len(key["rows"]),
        "variants": {},
    }
    for variant in manifest["spec"]["variants"]:
        rows = [row for row in graded if row["variant"] == variant]
        count = len(rows)
        summary["variants"][variant] = {
            "rated": count,
            "style_mean": sum(row["style_score"] for row in rows) / count if count else None,
            "grounded_mean": sum(row["grounded_score"] for row in rows) / count if count else None,
            "sendable_rate": sum(row["sendable"] for row in rows) / count if count else None,
            "observed_privacy_violations": sum(row["privacy_violation"] for row in rows),
            "observed_unauthorized_commitments": sum(
                row["unauthorized_commitment"] for row in rows
            ),
        }
    write_json(run / "human-ratings.json", {"ratings": graded, "reviewer": reviewer})
    write_json(run / "score-summary.json", summary)
    return summary
