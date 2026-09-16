from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agent_collaboration_contracts import AgentCollaborationStatus
from .domain import NonEmptyString


class AgentHarnessStatus(StrEnum):
    COMPLETED = "completed"
    HUMAN_REVIEW = "human_review"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FAILED = "failed"


class AgentHarnessStageStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentHarnessContextSnapshot(BaseModel):
    """Auditable size of the structured context admitted by the Harness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    serialized_characters: int = Field(ge=0)
    evidence_reference_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    review_issue_count: int = Field(ge=0)


class AgentHarnessBudgetSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_delegations: int = Field(ge=1)
    max_reflection_rounds: int = Field(ge=0)
    max_llm_calls: int = Field(ge=2)
    used_delegations: int = Field(ge=0)
    used_reflection_rounds: int = Field(ge=0)
    used_llm_calls: int = Field(ge=0)


class AgentHarnessStageTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: NonEmptyString
    status: AgentHarnessStageStatus
    elapsed_ms: float = Field(ge=0)
    detail: NonEmptyString | None = None


class AgentHarnessReport(BaseModel):
    """One immutable record of context, guardrails, budget and Agent outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    harness_run_id: NonEmptyString
    request_id: NonEmptyString
    harness_version: NonEmptyString
    prompt_version: NonEmptyString
    status: AgentHarnessStatus
    collaboration_status: AgentCollaborationStatus
    context: AgentHarnessContextSnapshot
    budget: AgentHarnessBudgetSnapshot
    traces: list[AgentHarnessStageTrace] = Field(min_length=1)
    started_at: datetime
    finished_at: datetime
    failure_reason: NonEmptyString | None = None

    @model_validator(mode="after")
    def terminal_state_is_consistent(self) -> AgentHarnessReport:
        for value in (self.started_at, self.finished_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Harness 时间必须包含时区")
        if self.finished_at < self.started_at:
            raise ValueError("Harness 完成时间不能早于开始时间")
        failed = self.status in {
            AgentHarnessStatus.HUMAN_REVIEW,
            AgentHarnessStatus.BUDGET_EXHAUSTED,
            AgentHarnessStatus.FAILED,
        }
        if failed != (self.failure_reason is not None):
            raise ValueError("Harness 终态与失败原因不一致")
        expected = {
            AgentCollaborationStatus.ACCEPTED: AgentHarnessStatus.COMPLETED,
            AgentCollaborationStatus.HUMAN_REVIEW: AgentHarnessStatus.HUMAN_REVIEW,
            AgentCollaborationStatus.BUDGET_EXHAUSTED: (
                AgentHarnessStatus.BUDGET_EXHAUSTED
            ),
            AgentCollaborationStatus.FAILED: AgentHarnessStatus.FAILED,
        }[self.collaboration_status]
        if self.status is not expected:
            raise ValueError("Harness 与协作终态不一致")
        return self
