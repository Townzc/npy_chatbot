"""Prepare only bundled fictional conversations for a real Qwen CUDA dry run."""

import argparse
import json
from pathlib import Path

from chattwin.importers import DataService
from chattwin.runtime_paths import package_root
from chattwin.storage import Store
from chattwin.training.spec import prepare_spec, private_output
from chattwin.training.worker import write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, required=True, help="new private directory outside Git"
    )
    args = parser.parse_args()
    root = private_output(args.root)
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    store = Store(root / "data")
    try:
        store.migrate()
        data = DataService(store)
        persona = data.create_persona("GPU validation · fictional owner")
        relationship = data.create_relationship(persona["id"], "GPU validation · fictional friend")
        data.import_file(
            package_root() / "fixtures/canonical_messages.synthetic.jsonl",
            persona["id"],
            relationship["id"],
            "demo_owner",
            "demo_source_account",
            format="canonical_jsonl",
            mapping={"conversation_kind": "private"},
            confirm_human=True,
        )
        dataset = data.build_dataset(persona["id"], relationship["id"])
        spec = prepare_spec(Path(dataset["path"]), root / "job", profile="rtx4090-dry-run")
        write_json(root / "spec.json", spec.model_dump(mode="json"))
        print(
            json.dumps(
                {
                    "spec": str(root / "spec.json"),
                    "dataset_counts": dataset["counts"],
                    "data_evidence": "bundled fictional conversations only",
                    "training_started": False,
                    "hardware": "UNVERIFIED",
                },
                indent=2,
            )
        )
    finally:
        store.close()


if __name__ == "__main__":
    main()
