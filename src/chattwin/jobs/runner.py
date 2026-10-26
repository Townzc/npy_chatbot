"""Child process holds the execution lease even if its API parent disappears."""

import argparse
import os
from pathlib import Path

from filelock import FileLock, Timeout

from chattwin.training.spec import TrainingSpec
from chattwin.training.worker import train, worker_environment, write_json


def main() -> None:
    environment = worker_environment()
    os.environ.clear()
    os.environ.update(environment)
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--lease", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    try:
        with FileLock(args.lease, timeout=0):
            spec = TrainingSpec.model_validate_json(args.spec.read_text())
            result = train(spec)
            status = result.get("status")
            if isinstance(status, dict):
                status = status.get("status")
            write_json(args.result, {"status": status, "error_code": None})
            if status != "succeeded":
                raise SystemExit(2)
    except Timeout:
        write_json(args.result, {"status": "failed", "error_code": "EXECUTION_LEASE_BUSY"})
        raise SystemExit(3) from None
    except Exception as exc:
        write_json(
            args.result,
            {"status": "failed", "error_code": "TRAINING_FAILED", "error_type": type(exc).__name__},
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
