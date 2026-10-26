"""Owner job requests contain no filesystem destinations, shell text or credentials."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TrainingJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    persona_id: str = Field(min_length=1)
    relationship_id: str = Field(min_length=1)
    precision: Literal["bfloat16", "float16"] = "bfloat16"
    rank: int = Field(default=8, ge=1, le=128)
    alpha: int = Field(default=16, ge=1, le=1024)
    dropout: float = Field(default=0.05, ge=0, lt=1)
    max_sequence_length: int = Field(default=1024, ge=16, le=32768)
    batch_size: int = Field(default=1, ge=1, le=128)
    gradient_accumulation: int = Field(default=4, ge=1, le=1024)
    learning_rate: float = Field(default=2e-4, gt=0, le=0.1)
    epochs: int = Field(default=1, ge=1, le=100)
    max_steps: int = Field(default=100, ge=1, le=1000000)
    seed: int = Field(default=42, ge=0)
    allow_model_download: bool = False


class JobView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str
    status: Literal[
        "queued", "validating", "running", "succeeded", "failed", "cancelled", "interrupted"
    ]
    persona_id: str
    relationship_id: str
    dataset_id: str
    created_at: str
    updated_at: str
    phase: str = "queued"
    step: int = 0
    progress: float = 0
    heartbeat: str | None = None
    cancel_requested: bool = False
    error_code: str | None = None
    error_summary: str | None = None
    output_path: str | None = None
    artifact_ready: bool = False
    loss: float | None = None


class JobLogEvent(BaseModel):
    at: str
    event: str
    detail: str


class JobLogs(BaseModel):
    events: list[JobLogEvent]
    raw_logs_exposed: Literal[False] = False


class TrainingEnvironment(BaseModel):
    python_available: bool
    dependencies_available: bool
    platform: str
    python_version: str | None = None
    dependencies: dict[str, str] = Field(default_factory=dict)
    cuda_available: bool = False
    cuda_bf16_supported: bool = False
    supports_reference_training: bool = False
    tiny_available: bool = False
    blockers: list[str] = Field(default_factory=list)
    reference_model: dict[str, str]
    download_default_disabled: Literal[True] = True
