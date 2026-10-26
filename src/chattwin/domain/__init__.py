"""Versioned contracts. No framework, database, channel or model SDK imports."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Scope(Contract):
    persona_id: str
    relationship_id: str


class Persona(Contract):
    id: str = Field(default_factory=uid)
    name: str
    target_identity_id: str
    identity_mapping_version: int = 1
    version: int = 1


class Source(Contract):
    platform: str
    importer: str
    importer_version: str
    source_account_id: str
    source_message_id: str | None = None
    import_batch_id: str
    file_sha256: str
    record_index: int


class Content(Contract):
    type: str = "text"
    text: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    reply_to: str | None = None
    unsupported_type: str | int | None = None


class UsePolicy(Contract):
    context: bool = True
    style: bool = False
    training_target: bool = False


class MessageUse(Contract):
    persona_id: str
    relationship_id: str | None = None
    identity_mapping_version: int
    sender_role: Literal["owner", "partner", "other", "system"]
    use_policy: UsePolicy = Field(default_factory=UsePolicy)


class Message(Contract):
    schema_version: Literal["1.0"] = "1.0"
    id: str = Field(default_factory=uid)
    source: Source
    conversation_id: str
    relationship_id: str | None = None
    sender_id: str
    origin: Literal["human", "ai", "mode_notice", "platform_system", "unknown"] = "unknown"
    occurred_at: datetime
    ingested_at: datetime = Field(default_factory=now)
    sequence: int
    content: Content
    use_context: MessageUse | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at", "ingested_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timezone required")
        return value.astimezone(UTC)


class Binding(Scope):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(default_factory=uid)
    channel_account_id: str
    conversation_id: str
    recipient_id: str
    channel: Literal["fake", "web", "onebot"] = "fake"


class Mode(StrEnum):
    HUMAN = "HUMAN"
    ENABLING = "ENABLING"
    AI_ACTIVE = "AI_ACTIVE"
    PAUSED = "PAUSED"


class ModeCommand(Contract):
    command_id: str = Field(min_length=1, max_length=128)
    action: Literal["enable", "takeover", "pause"]
    expected_control_epoch: int | None = None


class Candidate(Contract):
    id: str = Field(default_factory=uid)
    binding_id: str
    control_epoch: int
    context_seq: int
    persona_version: int = 1
    memory_version: int = 1
    model_deployment_id: str = "mock-v1"
    input_message_ids: list[str] = Field(default_factory=list)
    text: str = Field(min_length=1, max_length=4000)
    expires_at: datetime


class SendRequest(Contract):
    outbox_id: str
    binding: Binding
    kind: Literal["ai_reply", "enable_notice", "takeover_notice"]
    text: str


class SendReceipt(Contract):
    status: Literal["confirmed", "rejected", "unknown"]
    platform_message_id: str | None = None
    detail: str | None = None


class ChannelCapabilities(Contract):
    receive_private: bool = False
    send_text: bool = False
    self_echo: bool = False
    history_lookup: bool = False
    stable_message_id: bool = False
    idempotent_send: bool = False
    recipient_identity_kind: str = "stable_id"
    tested_version: str = "unverified"


class GenerationRequest(Scope):
    messages: list[dict[str, str]]
    max_tokens: int = Field(default=256, ge=1, le=4096)
    model: str = "mock"
    temperature: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)


class GenerationResult(Contract):
    text: str
    model: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    usage_reported: bool = False
    synthetic: bool = False


class Job(Contract):
    id: str = Field(default_factory=uid)
    kind: str
    status: Literal[
        "queued", "validating", "running", "succeeded", "failed", "cancelled", "interrupted"
    ] = "queued"
    progress: float = 0
    error: str | None = None


class DomainError(Exception):
    def __init__(self, code: str, detail: str, status: int = 409):
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status
