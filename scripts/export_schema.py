"""Generate public schemas without touching the owner's data directory."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from chattwin import domain
from chattwin.api import create_app
from chattwin.jobs.models import (
    JobLogEvent,
    JobLogs,
    JobView,
    TrainingEnvironment,
    TrainingJobRequest,
)
from chattwin.models.registry import (
    ActivateDeployment,
    ArtifactRecord,
    DeploymentInput,
    DeploymentRecord,
)
from chattwin.training.spec import TrainingSpec

root = Path(__file__).resolve().parents[1] / "schemas"
root.mkdir(exist_ok=True)
with TemporaryDirectory() as directory:
    app = create_app(directory, token="schema-generation-only")
    (root / "openapi.json").write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"
    )
    app.state.store.close()
for name in (
    "Message",
    "Persona",
    "Binding",
    "Candidate",
    "ModeCommand",
    "SendRequest",
    "SendReceipt",
    "GenerationRequest",
    "GenerationResult",
    "Job",
):
    (root / f"{name}.json").write_text(
        json.dumps(getattr(domain, name).model_json_schema(), ensure_ascii=False, indent=2) + "\n"
    )
(root / "TrainingSpec.json").write_text(
    json.dumps(TrainingSpec.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
)
for contract in (
    TrainingJobRequest,
    JobView,
    JobLogEvent,
    JobLogs,
    TrainingEnvironment,
    ArtifactRecord,
    DeploymentRecord,
    DeploymentInput,
    ActivateDeployment,
):
    (root / f"{contract.__name__}.json").write_text(
        json.dumps(contract.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
    )
