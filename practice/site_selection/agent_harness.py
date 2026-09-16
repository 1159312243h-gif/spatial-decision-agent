from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from threading import RLock
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agent_collaboration import (
    AgentPromptProfile,
    CollaborationBudget,
    MultiAgentReviewRuntime,
    build_collaboration_evidence,
)
from .agent_collaboration_contracts import (
    AgentCollaborationReport,
    AgentCollaborationStatus,
)
from .agent_harness_contracts import (
    AgentHarnessBudgetSnapshot,
    AgentHarnessContextSnapshot,
    AgentHarnessReport,
    AgentHarnessStageStatus,
    AgentHarnessStageTrace,
    AgentHarnessStatus,
)
from .agent_orchestration import AgentRole
from .domain import NonEmptyString
from .evidence import AgentState, AnalysisStatus


_REQUIRED_ROLES = {
    AgentRole.SUPERVISOR,
    AgentRole.POI,
    AgentRole.SPATIAL,
    AgentRole.POLICY,
    AgentRole.REVIEW,
}


class PromptBundle(BaseModel):
    """Immutable, complete Prompt configuration promoted as one unit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: NonEmptyString
    parent_version: NonEmptyString | None = None
    change_summary: NonEmptyString
    created_at: datetime
    profiles: dict[AgentRole, AgentPromptProfile]

    @model_validator(mode="after")
    def bundle_is_complete(self) -> PromptBundle:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Prompt 版本时间必须包含时区")
        if set(self.profiles) != _REQUIRED_ROLES:
            raise ValueError("Prompt 版本必须完整覆盖五个 Agent 角色")
        if any(profile.role is not role for role, profile in self.profiles.items()):
            raise ValueError("Prompt 版本角色键与 profile.role 不一致")
        if self.parent_version == self.version:
            raise ValueError("Prompt 版本不能以自身为父版本")
        return self


class PromptActivationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    previous_version: NonEmptyString
    active_version: NonEmptyString
    approval_reference: NonEmptyString
    activated_at: datetime
    rollback: bool = False


class PromptVersionRegistry:
    """Thread-safe Prompt registry with explicit approval and rollback audit."""

    def __init__(self, initial: PromptBundle) -> None:
        self._bundles = {initial.version: initial.model_copy(deep=True)}
        self._active_version = initial.version
        self._events: list[PromptActivationEvent] = []
        self._lock = RLock()

    @property
    def active_version(self) -> str:
        with self._lock:
            return self._active_version

    def active(self) -> PromptBundle:
        return self.get(self.active_version)

    def get(self, version: str) -> PromptBundle:
        with self._lock:
            try:
                return self._bundles[version].model_copy(deep=True)
            except KeyError as exc:
                raise KeyError(f"未知 Prompt 版本：{version}") from exc

    def register(self, bundle: PromptBundle) -> None:
        with self._lock:
            if bundle.version in self._bundles:
                raise ValueError(f"Prompt 版本已存在：{bundle.version}")
            if (
                bundle.parent_version is not None
                and bundle.parent_version not in self._bundles
            ):
                raise ValueError(f"Prompt 父版本不存在：{bundle.parent_version}")
            self._bundles[bundle.version] = bundle.model_copy(deep=True)

    def activate(
        self,
        version: str,
        *,
        approval_reference: str,
        activated_at: datetime | None = None,
        rollback: bool = False,
    ) -> PromptActivationEvent:
        approval = approval_reference.strip()
        if not approval:
            raise ValueError("Prompt 晋级必须提供人工批准记录")
        timestamp = activated_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Prompt 晋级时间必须包含时区")
        with self._lock:
            if version not in self._bundles:
                raise KeyError(f"未知 Prompt 版本：{version}")
            previous = self._active_version
            if version == previous:
                raise ValueError("目标 Prompt 已是活动版本")
            event = PromptActivationEvent(
                previous_version=previous,
                active_version=version,
                approval_reference=approval,
                activated_at=timestamp,
                rollback=rollback,
            )
            self._active_version = version
            self._events.append(event)
            return event

    def rollback(
        self,
        version: str,
        *,
        approval_reference: str,
        activated_at: datetime | None = None,
    ) -> PromptActivationEvent:
        return self.activate(
            version,
            approval_reference=approval_reference,
            activated_at=activated_at,
            rollback=True,
        )

    def events(self) -> list[PromptActivationEvent]:
        with self._lock:
            return [event.model_copy(deep=True) for event in self._events]


class AgentHarnessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    harness_version: NonEmptyString = "site-selection-harness-v1"
    max_context_characters: int = Field(default=120_000, ge=1_000)
    max_evidence_references: int = Field(default=2_000, ge=1)


class AgentRuntimeFactory(Protocol):
    def __call__(self, bundle: PromptBundle) -> MultiAgentReviewRuntime: ...


class AgentHarness:
    """Unified outer runtime for versioning, context, budgets and guardrails."""

    def __init__(
        self,
        registry: PromptVersionRegistry,
        runtime_factory: AgentRuntimeFactory,
        *,
        config: AgentHarnessConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._registry = registry
        self._runtime_factory = runtime_factory
        self._config = config or AgentHarnessConfig()
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def registry(self) -> PromptVersionRegistry:
        return self._registry

    @property
    def config(self) -> AgentHarnessConfig:
        return self._config

    def runtime_for_active_version(self) -> MultiAgentReviewRuntime:
        """Resolve the active immutable Prompt bundle into one review runtime."""

        return self._runtime_factory(self._registry.active())

    def review(
        self,
        state: AgentState,
        *,
        conversation_id: str | None = None,
    ) -> AgentState:
        if state.status is not AnalysisStatus.COMPLETED:
            raise ValueError("Agent Harness 只能处理已完成的确定性分析")
        if state.evidence_review_report is None:
            raise ValueError("Agent Harness 要求先完成确定性证据审查")

        started_at = self._clock()
        traces: list[AgentHarnessStageTrace] = []
        stage_started = perf_counter()
        evidence, references = build_collaboration_evidence(state)
        serialized = json.dumps(
            evidence,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        context = AgentHarnessContextSnapshot(
            serialized_characters=len(serialized),
            evidence_reference_count=len(references),
            candidate_count=len(evidence["candidates"]),
            review_issue_count=len(evidence["review_issues"]),
        )
        context_failure = self._context_failure(context)
        traces.append(
            AgentHarnessStageTrace(
                stage="context_projection_and_guardrail",
                status=(
                    AgentHarnessStageStatus.FAILED
                    if context_failure
                    else AgentHarnessStageStatus.SUCCEEDED
                ),
                elapsed_ms=_elapsed_ms(stage_started),
                detail=context_failure,
            )
        )

        bundle = self._registry.active()
        runtime = self._runtime_factory(bundle)
        budget = runtime.budget
        if context_failure:
            collaboration = AgentCollaborationReport(
                request_id=state.request.request_id,
                conversation_id=conversation_id or f"harness-{uuid4().hex[:12]}",
                status=AgentCollaborationStatus.FAILED,
                final_summary=context_failure,
                human_review_reason=context_failure,
                delegation_count=0,
                reflection_rounds=0,
                llm_calls=0,
            )
            reviewed = _state_with_collaboration(state, collaboration)
            traces.append(
                AgentHarnessStageTrace(
                    stage="multi_agent_review",
                    status=AgentHarnessStageStatus.SKIPPED,
                    elapsed_ms=0,
                    detail="上下文门禁失败，禁止调用模型",
                )
            )
        else:
            stage_started = perf_counter()
            reviewed = runtime.review(
                state,
                conversation_id=conversation_id,
                prepared_evidence=(evidence, references),
            )
            collaboration = reviewed.collaboration_report
            if collaboration is None:
                raise RuntimeError("多 Agent Runtime 未返回协作报告")
            traces.append(
                AgentHarnessStageTrace(
                    stage="multi_agent_review",
                    status=(
                        AgentHarnessStageStatus.SUCCEEDED
                        if collaboration.status
                        is AgentCollaborationStatus.ACCEPTED
                        else AgentHarnessStageStatus.FAILED
                    ),
                    elapsed_ms=_elapsed_ms(stage_started),
                    detail=collaboration.human_review_reason,
                )
            )

        finished_at = self._clock()
        harness_status = _harness_status(collaboration.status)
        report = AgentHarnessReport(
            harness_run_id=f"harness-{state.request.request_id}-{uuid4().hex[:12]}",
            request_id=state.request.request_id,
            harness_version=self._config.harness_version,
            prompt_version=bundle.version,
            status=harness_status,
            collaboration_status=collaboration.status,
            context=context,
            budget=_budget_snapshot(budget, collaboration),
            traces=traces,
            started_at=started_at,
            finished_at=finished_at,
            failure_reason=(
                None
                if harness_status is AgentHarnessStatus.COMPLETED
                else collaboration.human_review_reason
                or collaboration.final_summary
            ),
        )
        data = reviewed.model_dump(mode="json")
        data["agent_harness_report"] = report.model_dump(mode="json")
        return AgentState.model_validate(data)

    def _context_failure(
        self,
        context: AgentHarnessContextSnapshot,
    ) -> str | None:
        if context.serialized_characters > self._config.max_context_characters:
            return "结构化证据上下文超过 Harness 字符预算"
        if context.evidence_reference_count > self._config.max_evidence_references:
            return "证据引用数量超过 Harness 白名单预算"
        return None


def _state_with_collaboration(
    state: AgentState,
    report: AgentCollaborationReport,
) -> AgentState:
    data = state.model_dump(mode="json")
    data["collaboration_report"] = report.model_dump(mode="json")
    return AgentState.model_validate(data)


def _harness_status(status: AgentCollaborationStatus) -> AgentHarnessStatus:
    return {
        AgentCollaborationStatus.ACCEPTED: AgentHarnessStatus.COMPLETED,
        AgentCollaborationStatus.HUMAN_REVIEW: AgentHarnessStatus.HUMAN_REVIEW,
        AgentCollaborationStatus.BUDGET_EXHAUSTED: (
            AgentHarnessStatus.BUDGET_EXHAUSTED
        ),
        AgentCollaborationStatus.FAILED: AgentHarnessStatus.FAILED,
    }[status]


def _budget_snapshot(
    budget: CollaborationBudget,
    report: AgentCollaborationReport,
) -> AgentHarnessBudgetSnapshot:
    return AgentHarnessBudgetSnapshot(
        max_delegations=budget.max_delegations,
        max_reflection_rounds=budget.max_reflection_rounds,
        max_llm_calls=budget.max_llm_calls,
        used_delegations=report.delegation_count,
        used_reflection_rounds=report.reflection_rounds,
        used_llm_calls=report.llm_calls,
    )


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1_000, 3)
