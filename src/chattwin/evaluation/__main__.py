"""Explicit local CLI; never automatically sends messages or promotes a model."""

import argparse
import asyncio
import json
from pathlib import Path

from chattwin.domain import DomainError
from chattwin.importers import DataService
from chattwin.models import MockProvider
from chattwin.models.registry import ModelRegistry
from chattwin.storage import Store
from chattwin.training.spec import private_output

from . import (
    EvaluationRunner,
    EvaluationSpec,
    export_blind_sheet,
    frozen_test_cases,
    read_cases,
    summarize_scores,
)


def main():
    parser = argparse.ArgumentParser(
        description="Private offline HTTP model comparisons and human blind review"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--data-dir", type=Path, required=True)
    run.add_argument("--spec", type=Path, required=True)
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--cases", type=Path)
    source.add_argument("--dataset-id")
    blind = commands.add_parser("blind")
    blind.add_argument("--run-dir", type=Path, required=True)
    score = commands.add_parser("score")
    score.add_argument("--run-dir", type=Path, required=True)
    score.add_argument("--ratings", type=Path, required=True)
    score.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    try:
        if args.command == "blind":
            result = export_blind_sheet(private_output(args.run_dir))
        elif args.command == "score":
            result = summarize_scores(private_output(args.run_dir), args.ratings, args.reviewer)
        else:
            if not (args.data_dir / "chattwin.sqlite3").is_file():
                raise ValueError("use an existing ChatTwin data directory")
            store = Store(args.data_dir)
            try:
                store.migrate()
                data = DataService(store)
                spec = EvaluationSpec.model_validate_json(args.spec.read_text())
                cases = (
                    read_cases(args.cases)
                    if args.cases
                    else frozen_test_cases(
                        data, args.dataset_id, spec.persona_id, spec.relationship_id
                    )
                )
                registry = ModelRegistry(store, MockProvider(), lambda: None)
                result = asyncio.run(EvaluationRunner(store, data, registry).run(spec, cases))
            finally:
                store.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, DomainError) as exc:
        # Never print model responses, private input validation detail or credentials.
        print(
            json.dumps(
                {
                    "error": exc.code
                    if isinstance(exc, DomainError)
                    else "EVALUATION_INVALID_INPUT",
                    "detail": "Review the private run manifest and evaluation documentation.",
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
