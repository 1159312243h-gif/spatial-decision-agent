from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agent_orchestration import AgentRole
from .domain import NonEmptyString


class AgentMessageKind(StrEnum):
    DELEGATION = "delegation"
    FINDING = "finding"
    CRITIQUE = "critique"
    DECISION = "decision"


class AgentCollaborationStatus(StrEnum):
    ACCEPTED = "accepted"
    HUMAN_REVIEW = "human_review"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FAILED = "failed"


class AgentMessage(BaseModel):
    """Auditable natural-language message exchanged by two Agent roles."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: NonEmptyString
    conversation_id: NonEmptyString
    sender: AgentRole
    recipient: AgentRole
    kind: AgentMessageKind
    round_index: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=4_000)
    evidence_references: list[NonEmptyString] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def message_is_consistent(self) -> AgentMessage:
        if self.sender is self.recipient:
            raise ValueError("Agent 消息的发送方和接收方不能相同")
        if len(self.evidence_references) != len(set(self.evidence_references)):
            raise ValueError("Agent 消息不能包含重复证据引用")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Agent 消息时间必须包含时区")
        return self


class AgentMemoryRecord(BaseModel):
    """Role-scoped durable memory with optimistic revision control."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_scope: NonEmptyString
    role: AgentRole
    memory_key: NonEmptyString
    content: str = Field(min_length=1, max_length=2_000)
    evidence_references: list[NonEmptyString] = Field(default_factory=list)
    revision: int = Field(ge=1)
    updated_at: datetime

    @model_validator(mode="after")
    def memory_is_consistent(self) -> AgentMemoryRecord:
        if len(self.evidence_references) != len(set(self.evidence_references)):
            raise ValueError("Agent 记忆不能包含重复证据引用")
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("Agent 记忆时间必须包含时区")
        return self


class AgentMemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_key: NonEmptyString
    content: str = Field(min_length=1, max_length=2_000)
    evidence_references: list[NonEmptyString] = Field(default_factory=list)
    expected_revision: int | None = Field(default=None, ge=0)


class SupervisorAction(StrEnum):
    DELEGATE = "delegate"
    REVIEW = "review"
    HUMAN_REVIEW = "human_review"


class SupervisorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: SupervisorAction
    target_role: AgentRole | None = None
    objective: str = Field(min_length=1, max_length=1_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    evidence_references: list[NonEmptyString] = Field(default_factory=list)
    memory_update: AgentMemoryUpdate | None = None

    @model_validator(mode="after")
    def action_matches_target(self) -> SupervisorDecision:
        specialists = {AgentRole.POI, AgentRole.SPATIAL, AgentRole.POLICY}
        if self.action is SupervisorAction.DELEGATE:
            if self.target_role not in specialists:
                raise ValueError("delegate 必须指定 POI、Spatial 或 Policy Agent")
        elif self.target_role is not None:
            raise ValueError("非 delegate 决策不能指定 target_role")
        return self


class SpecialistStance(StrEnum):
    SUPPORT = "support"
    CHALLENGE = "challenge"
    INSUFFICIENT = "insufficient"


class SpecialistResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1, max_length=2_000)
    stance: SpecialistStance
    findings: list[NonEmptyString] = Field(min_length=1)
    evidence_references: list[NonEmptyString] = Field(min_length=1)
    suggested_next_role: AgentRole | None = None
    memory_update: AgentMemoryUpdate | None = None

    @model_validator(mode="after")
    def suggestion_targets_another_specialist(self) -> SpecialistResponse:
        allowed = {AgentRole.POI, AgentRole.SPATIAL, AgentRole.POLICY, AgentRole.REVIEW}
        if (
            self.suggested_next_role is not None
            and self.suggested_next_role not in allowed
        ):
            raise ValueError("专家 Agent 只能建议委派给证据角色或 Review Agent")
        if len(self.evidence_references) != len(set(self.evidence_references)):
            raise ValueError("专家响应不能包含重复证据引用")
        return self


class ReviewAction(StrEnum):
    ACCEPT = "accept"
    REDELEGATE = "redelegate"
    HUMAN_REVIEW = "human_review"


class ReviewVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: ReviewAction
    summary: str = Field(min_length=1, max_length=2_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    target_role: AgentRole | None = None
    follow_up_objective: str | None = Field(
        default=None,
        min_length=1,
        max_length=1_000,
    )
    evidence_references: list[NonEmptyString] = Field(default_factory=list)
    memory_update: AgentMemoryUpdate | None = None

    @model_validator(mode="after")
    def action_matches_follow_up(self) -> ReviewVerdict:
        specialists = {AgentRole.POI, AgentRole.SPATIAL, AgentRole.POLICY}
        if self.action is ReviewAction.REDELEGATE:
            if self.target_role not in specialists or self.follow_up_objective is None:
                raise ValueError("redelegate 必须指定专家角色和后续目标")
        elif self.target_role is not None or self.follow_up_objective is not None:
            raise ValueError("非 redelegate 结论不能包含后续委派")
        return self


class AgentCollaborationReport(BaseModel):
    """Bounded multi-Agent deliberation report; never rewrites business truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: NonEmptyString
    conversation_id: NonEmptyString
    status: AgentCollaborationStatus
    messages: list[AgentMessage] = Field(default_factory=list)
    delegation_count: int = Field(ge=0)
    reflection_rounds: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    final_summary: NonEmptyString
    human_review_reason: NonEmptyString | None = None
    role_memory_revisions: dict[AgentRole, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def terminal_fields_are_consistent(self) -> AgentCollaborationReport:
        needs_human = self.status in {
            AgentCollaborationStatus.HUMAN_REVIEW,
            AgentCollaborationStatus.BUDGET_EXHAUSTED,
            AgentCollaborationStatus.FAILED,
        }
        if needs_human != (self.human_review_reason is not None):
            raise ValueError("协作终态与人工复核原因不一致")
        if len({message.message_id for message in self.messages}) != len(self.messages):
            raise ValueError("协作报告不能包含重复 message_id")
        return self
