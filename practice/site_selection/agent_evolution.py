from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agent_collaboration import AgentPromptProfile
from .agent_evaluation import AgentEvaluationMetrics, AgentEvaluationReport
from .agent_harness import (
    PromptActivationEvent,
    PromptBundle,
    PromptVersionRegistry,
)
from .agent_orchestration import AgentRole
from .domain import NonEmptyString


class PromptCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: NonEmptyString
    bundle: PromptBundle
    hypothesis: NonEmptyString
    generated_by: NonEmptyString


class PromotionPolicy(BaseModel):
    """Offline quality/safety gates; no candidate can auto-promote."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_task_success_rate: float = Field(default=0.95, ge=0, le=1)
    min_evidence_reference_valid_rate: float = Field(default=1.0, ge=0, le=1)
    min_budget_convergence_rate: float = Field(default=1.0, ge=0, le=1)
    min_protocol_violation_detection_rate: float = Field(
        default=1.0,
        ge=0,
        le=1,
    )
    max_task_success_regression: float = Field(default=0.0, ge=0, le=1)
    max_reflection_recovery_regression: float = Field(default=0.0, ge=0, le=1)
    max_average_llm_call_increase: float = Field(default=1.0, ge=0)


class PromotionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: NonEmptyString
    baseline_version: NonEmptyString
    candidate_version: NonEmptyString
    suite_id: NonEmptyString
    suite_version: NonEmptyString
    gate_passed: bool
    gate_failures: list[NonEmptyString] = Field(default_factory=list)
    baseline_metrics: AgentEvaluationMetrics
    candidate_metrics: AgentEvaluationMetrics
    evaluated_at: datetime

    @model_validator(mode="after")
    def gate_result_is_consistent(self) -> PromotionDecision:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("Prompt 评测时间必须包含时区")
        if self.gate_passed == bool(self.gate_failures):
            raise ValueError("Prompt 门禁结论与失败项不一致")
        return self


class AgentEvolutionEngine:
    """Controlled evolution: propose, evaluate, approve, promote and rollback."""

    def __init__(
        self,
        registry: PromptVersionRegistry,
        *,
        policy: PromotionPolicy | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy or PromotionPolicy()
        self._decisions: dict[str, PromotionDecision] = {}

    def propose_candidate(
        self,
        *,
        version: str,
        prompt_updates: Mapping[AgentRole, str],
        hypothesis: str,
        generated_by: str,
        created_at: datetime | None = None,
    ) -> PromptCandidate:
        base = self._registry.active()
        if not prompt_updates:
            raise ValueError("Prompt 候选至少需要修改一个角色")
        unknown = set(prompt_updates) - set(base.profiles)
        if unknown:
            raise ValueError(
                "Prompt 候选包含未知角色："
                + ", ".join(sorted(role.value for role in unknown))
            )
        profiles = {
            role: (
                AgentPromptProfile(
                    **{
                        **profile.model_dump(),
                        "system_prompt": prompt_updates[role],
                    }
                )
                if role in prompt_updates
                else profile.model_copy(deep=True)
            )
            for role, profile in base.profiles.items()
        }
        bundle = PromptBundle(
            version=version,
            parent_version=base.version,
            change_summary=hypothesis,
            created_at=created_at or datetime.now(UTC),
            profiles=profiles,
        )
        self._registry.register(bundle)
        return PromptCandidate(
            candidate_id=f"candidate-{uuid4().hex[:12]}",
            bundle=bundle,
            hypothesis=hypothesis,
            generated_by=generated_by,
        )

    def evaluate(
        self,
        baseline: AgentEvaluationReport,
        candidate: AgentEvaluationReport,
        *,
        evaluated_at: datetime | None = None,
    ) -> PromotionDecision:
        if (baseline.suite_id, baseline.suite_version) != (
            candidate.suite_id,
            candidate.suite_version,
        ):
            raise ValueError("Prompt 晋级必须使用同一冻结评测集")
        if baseline.prompt_version != self._registry.active_version:
            raise ValueError("Baseline 必须对应当前活动 Prompt 版本")
        if baseline.failed:
            raise ValueError("Baseline 冻结评测必须全部通过")
        candidate_bundle = self._registry.get(candidate.prompt_version)
        if candidate_bundle.parent_version != baseline.prompt_version:
            raise ValueError("Candidate 必须直接基于当前 Baseline")
        failures = _promotion_failures(
            baseline.metrics,
            candidate.metrics,
            self._policy,
        )
        if candidate.failed:
            failures.insert(0, "Candidate 冻结评测存在失败案例")
        decision = PromotionDecision(
            decision_id=f"promotion-{uuid4().hex[:12]}",
            baseline_version=baseline.prompt_version,
            candidate_version=candidate.prompt_version,
            suite_id=baseline.suite_id,
            suite_version=baseline.suite_version,
            gate_passed=not failures,
            gate_failures=failures,
            baseline_metrics=baseline.metrics,
            candidate_metrics=candidate.metrics,
            evaluated_at=evaluated_at or datetime.now(UTC),
        )
        self._decisions[decision.decision_id] = decision
        return decision

    def promote(
        self,
        decision_id: str,
        *,
        approved_by: str,
        approved_at: datetime | None = None,
    ) -> PromptActivationEvent:
        try:
            decision = self._decisions[decision_id]
        except KeyError as exc:
            raise KeyError(f"未知 Prompt 晋级决策：{decision_id}") from exc
        if not decision.gate_passed:
            raise ValueError("Prompt 候选未通过冻结评测门禁")
        approval = approved_by.strip()
        if not approval:
            raise ValueError("Prompt 晋级必须由人工明确批准")
        return self._registry.activate(
            decision.candidate_version,
            approval_reference=(
                f"{approval};decision={decision.decision_id};"
                f"suite={decision.suite_id}@{decision.suite_version}"
            ),
            activated_at=approved_at,
        )

    def rollback(
        self,
        version: str,
        *,
        approved_by: str,
        approved_at: datetime | None = None,
    ) -> PromptActivationEvent:
        approval = approved_by.strip()
        if not approval:
            raise ValueError("Prompt 回滚必须由人工明确批准")
        return self._registry.rollback(
            version,
            approval_reference=f"{approval};rollback",
            activated_at=approved_at,
        )


def _promotion_failures(
    baseline: AgentEvaluationMetrics,
    candidate: AgentEvaluationMetrics,
    policy: PromotionPolicy,
) -> list[str]:
    failures = []
    if candidate.task_success_rate < policy.min_task_success_rate:
        failures.append("任务成功率低于绝对门槛")
    if (
        candidate.task_success_rate
        < baseline.task_success_rate - policy.max_task_success_regression
    ):
        failures.append("任务成功率相对 Baseline 回退")
    if (
        candidate.reflection_recovery_rate
        < baseline.reflection_recovery_rate
        - policy.max_reflection_recovery_regression
    ):
        failures.append("反思恢复率相对 Baseline 回退")
    if (
        candidate.evidence_reference_valid_rate
        < policy.min_evidence_reference_valid_rate
    ):
        failures.append("证据引用合规率未达到门槛")
    if candidate.budget_convergence_rate < policy.min_budget_convergence_rate:
        failures.append("预算收敛率未达到门槛")
    if (
        candidate.protocol_violation_detection_rate
        < policy.min_protocol_violation_detection_rate
    ):
        failures.append("协议违规检测率未达到门槛")
    if (
        candidate.average_llm_calls
        > baseline.average_llm_calls + policy.max_average_llm_call_increase
    ):
        failures.append("平均 LLM 调用数增幅超过预算")
    return failures
