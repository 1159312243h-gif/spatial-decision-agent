from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain import NonEmptyString, ProjectType


class RuleOutcome(StrEnum):
    """A matched rule outcome; absence of a match is not a compliance pass."""

    NOTICE = "notice"
    REVIEW_REQUIRED = "review_required"
    RESTRICTED = "restricted"
    PROHIBITED = "prohibited"


class PolicyReference(BaseModel):
    """Auditable source metadata for one policy clause."""

    model_config = ConfigDict(extra="forbid")

    policy_id: NonEmptyString
    title: NonEmptyString
    issuing_authority: NonEmptyString
    document_number: NonEmptyString | None = None
    clause: NonEmptyString
    version: NonEmptyString
    jurisdiction: NonEmptyString
    source_uri: NonEmptyString


class RuleDefinition(BaseModel):
    """Versioned deterministic mapping from one observation to an outcome."""

    model_config = ConfigDict(extra="forbid")

    rule_id: NonEmptyString
    name: NonEmptyString
    version: NonEmptyString
    applicable_project_types: Annotated[list[ProjectType], Field(min_length=1)]
    constraint_id: NonEmptyString
    expected_triggered: bool = True
    outcome: RuleOutcome
    message: NonEmptyString
    policy: PolicyReference
    valid_from: date
    valid_to: date | None = None
    enabled: bool = True

    @field_validator("applicable_project_types")
    @classmethod
    def project_types_are_unique(
        cls,
        values: list[ProjectType],
    ) -> list[ProjectType]:
        if len(values) != len(set(values)):
            raise ValueError("规则适用项目类型不能重复")
        return values

    @model_validator(mode="after")
    def validity_period_is_ordered(self) -> RuleDefinition:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("规则 valid_to 不能早于 valid_from")
        return self

    def is_effective_on(self, value: date) -> bool:
        return self.valid_from <= value and (
            self.valid_to is None or value <= self.valid_to
        )


class PolicyFinding(BaseModel):
    """One matched rule with complete rule, policy, and observation lineage."""

    model_config = ConfigDict(extra="forbid")

    parcel_id: NonEmptyString
    rule_id: NonEmptyString
    rule_version: NonEmptyString
    constraint_id: NonEmptyString
    observed_triggered: bool
    expected_triggered: bool
    outcome: RuleOutcome
    message: NonEmptyString
    policy_id: NonEmptyString
    policy_title: NonEmptyString
    policy_version: NonEmptyString
    policy_clause: NonEmptyString
    issuing_authority: NonEmptyString
    jurisdiction: NonEmptyString
    source_uri: NonEmptyString
    observation_dataset_id: NonEmptyString
    observation_dataset_version: NonEmptyString
    observation_analysis_crs: NonEmptyString

    @model_validator(mode="after")
    def finding_represents_a_match(self) -> PolicyFinding:
        if self.observed_triggered != self.expected_triggered:
            raise ValueError("PolicyFinding 只能记录已命中的规则")
        return self
