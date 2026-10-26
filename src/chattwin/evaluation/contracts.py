"""Offline evaluation contracts; references are never generation messages."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Variant = Literal["B0", "B1", "B2", "B3"]
Category = Literal["style", "multi_turn", "facts", "privacy", "commitment", "unsupported"]


def all_variants() -> list[Variant]:
    return ["B0", "B1", "B2", "B3"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Turn(Strict):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class EvaluationCase(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    category: Category
    messages: list[Turn] = Field(min_length=1, max_length=16)
    source_cutoff: datetime
    reference: str = Field(default="", max_length=8000)
    rubric: str = Field(min_length=1, max_length=8000)
    synthetic: bool = False
    provenance: Literal["manual_reviewed", "frozen_test"] = "manual_reviewed"
    dataset_id: str | None = None
    dataset_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    example_id: str | None = None
    source_message_ids: list[str] = Field(default_factory=list)
    target_message_ids: list[str] = Field(default_factory=list)

    @field_validator("source_cutoff")
    @classmethod
    def cutoff_is_aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("source_cutoff requires a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def source_contract(self):
        if self.messages[-1].role != "user":
            raise ValueError("the visible context must end with a user turn")
        if self.provenance == "frozen_test" and not all(
            (self.dataset_id, self.dataset_hash, self.example_id, self.target_message_ids)
        ):
            raise ValueError("frozen test cases require immutable dataset and target lineage")
        if self.provenance == "manual_reviewed" and any(
            (
                self.dataset_id,
                self.dataset_hash,
                self.example_id,
                self.source_message_ids,
                self.target_message_ids,
            )
        ):
            raise ValueError("manual cases cannot impersonate imported dataset lineage")
        return self


class ModelPin(Strict):
    base_model_id: str = Field(min_length=1, max_length=4096)
    base_model_revision: str = Field(pattern=r"^(?:[0-9a-f]{40}|local:[0-9a-f]{64})$")
    tokenizer_revision: str = Field(pattern=r"^(?:[0-9a-f]{40}|local:[0-9a-f]{64})$")
    chat_template_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvaluationSpec(Strict):
    schema_version: Literal["1.0"] = "1.0"
    persona_id: str = Field(min_length=1)
    relationship_id: str = Field(min_length=1)
    base_deployment_id: str = Field(min_length=1)
    adapter_deployment_id: str | None = None
    base_pin: ModelPin
    variants: list[Variant] = Field(default_factory=all_variants)
    mode: Literal["formal", "synthetic-protocol"] = "formal"
    max_tokens: int = Field(default=256, ge=1, le=4096)
    temperature: Literal[0] = 0
    max_cases: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode="after")
    def comparison_contract(self):
        if not self.variants or len(set(self.variants)) != len(self.variants):
            raise ValueError("variants must be nonempty and unique")
        if "B3" in self.variants and not self.adapter_deployment_id:
            raise ValueError("B3 requires a registered verified adapter deployment")
        if self.base_deployment_id == "mock-v1":
            raise ValueError("evaluation requires an explicit HTTP model deployment")
        if self.mode == "formal" and set(self.variants) != {"B0", "B1", "B2", "B3"}:
            raise ValueError("formal comparisons require all B0–B3 variants")
        return self
