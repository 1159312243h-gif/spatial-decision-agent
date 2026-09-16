from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agent_collaboration import (
    AgentRoster,
    CollaborationBudget,
    InMemoryAgentMemoryStore,
    MultiAgentReviewRuntime,
    RoleAgent,
)
from .agent_collaboration_contracts import AgentCollaborationStatus
from .agent_harness import (
    AgentHarness,
    AgentHarnessConfig,
    PromptBundle,
    PromptVersionRegistry,
)
from .agent_harness_contracts import AgentHarnessStatus
from .agent_orchestration import AgentRole
from .domain import NonEmptyString
from .evidence import AgentState


class ScriptedAgentStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: AgentRole
    response: dict[str, Any]


class AgentEvaluationExpected(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: AgentHarnessStatus
    collaboration_status: AgentCollaborationStatus
    delegation_count: int = Field(ge=0)
    reflection_rounds: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    protocol_violation_detected: bool = False


class AgentEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: NonEmptyString
    scenario: NonEmptyString
    goal: Literal["accept", "safe_terminal"]
    steps: list[ScriptedAgentStep] = Field(min_length=1)
    budget: CollaborationBudget = Field(default_factory=CollaborationBudget)
    expected: AgentEvaluationExpected


class AgentEvaluationSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: NonEmptyString
    version: NonEmptyString
    frozen_at: datetime
    cases: list[AgentEvaluationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def suite_is_consistent(self) -> AgentEvaluationSuite:
        if self.frozen_at.tzinfo is None or self.frozen_at.utcoffset() is None:
            raise ValueError("Agent 冻结评测时间必须包含时区")
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Agent 冻结评测 case_id 不能重复")
        return self


class AgentEvaluationActual(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: AgentHarnessStatus
    collaboration_status: AgentCollaborationStatus
    delegation_count: int = Field(ge=0)
    reflection_rounds: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    evidence_reference_valid: bool
    budget_converged: bool
    reflection_recovered: bool
    human_escalated: bool
    protocol_violation_detected: bool


class AgentEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: NonEmptyString
    scenario: NonEmptyString
    goal: Literal["accept", "safe_terminal"]
    passed: bool
    elapsed_ms: float = Field(ge=0)
    expected: AgentEvaluationExpected
    actual: AgentEvaluationActual


class AgentEvaluationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_success_rate: float = Field(ge=0, le=1)
    evidence_reference_valid_rate: float = Field(ge=0, le=1)
    reflection_recovery_rate: float = Field(ge=0, le=1)
    human_escalation_rate: float = Field(ge=0, le=1)
    budget_convergence_rate: float = Field(ge=0, le=1)
    protocol_violation_rate: float = Field(ge=0, le=1)
    protocol_violation_detection_rate: float = Field(ge=0, le=1)
    average_llm_calls: float = Field(ge=0)
    average_delegations: float = Field(ge=0)


class AgentEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: NonEmptyString
    suite_version: NonEmptyString
    prompt_version: NonEmptyString
    generated_at: datetime
    total: int = Field(ge=1)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    metrics: AgentEvaluationMetrics
    results: list[AgentEvaluationResult] = Field(min_length=1)
    environment: dict[str, NonEmptyString]

    @model_validator(mode="after")
    def counts_are_consistent(self) -> AgentEvaluationReport:
        if self.passed + self.failed != self.total or len(self.results) != self.total:
            raise ValueError("Agent 评测汇总数量不一致")
        return self


class _ScriptedAgentModel:
    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self._outputs = [dict(output) for output in outputs]

    def generate(self, *, profile, response_model, payload):
        if not self._outputs:
            raise AssertionError(f"unexpected {profile.role.value} Agent call")
        output = _resolve_reference_placeholders(self._outputs.pop(0), payload)
        return response_model.model_validate(output)


class FrozenAgentEvaluationRunner:
    """Reproducible protocol evaluation using scripted Agent responses."""

    def __init__(self, base_state: AgentState, prompt_bundle: PromptBundle) -> None:
        self._base_state = base_state.model_copy(deep=True)
        self._prompt_bundle = prompt_bundle.model_copy(deep=True)

    def run_suite(self, suite: AgentEvaluationSuite) -> AgentEvaluationReport:
        results = [self.run_case(case) for case in suite.cases]
        passed = sum(result.passed for result in results)
        return AgentEvaluationReport(
            suite_id=suite.suite_id,
            suite_version=suite.version,
            prompt_version=self._prompt_bundle.version,
            generated_at=datetime.now(timezone.utc),
            total=len(results),
            passed=passed,
            failed=len(results) - passed,
            metrics=_aggregate_metrics(results),
            results=results,
            environment={
                "runtime": "local scripted multi-agent fixtures",
                "network": "disabled by evaluation design",
                "scope": "protocol and guardrail regression, not model quality",
            },
        )

    def run_case(self, case: AgentEvaluationCase) -> AgentEvaluationResult:
        started_at = perf_counter()
        by_role: dict[AgentRole, list[dict[str, Any]]] = defaultdict(list)
        for step in case.steps:
            by_role[step.role].append(step.response)
        roles = set(self._prompt_bundle.profiles)
        models = {role: _ScriptedAgentModel(by_role[role]) for role in roles}
        stores = {role: InMemoryAgentMemoryStore() for role in roles}

        def runtime_factory(bundle: PromptBundle) -> MultiAgentReviewRuntime:
            return MultiAgentReviewRuntime(
                AgentRoster(
                    agents={
                        role: RoleAgent(
                            profile=bundle.profiles[role],
                            model=models[role],
                            memory_store=stores[role],
                        )
                        for role in bundle.profiles
                    }
                ),
                budget=case.budget,
            )

        harness = AgentHarness(
            PromptVersionRegistry(self._prompt_bundle),
            runtime_factory,
            config=AgentHarnessConfig(
                harness_version="frozen-agent-eval-v1",
                max_context_characters=500_000,
                max_evidence_references=10_000,
            ),
        )
        reviewed = harness.review(
            self._base_state,
            conversation_id=f"agent-eval-{case.case_id.lower()}",
        )
        report = reviewed.collaboration_report
        harness_report = reviewed.agent_harness_report
        if report is None or harness_report is None:
            raise RuntimeError("Agent 冻结评测未生成 Harness/协作报告")
        allowed = _allowed_references(self._base_state)
        references = [
            reference
            for message in report.messages
            for reference in message.evidence_references
        ]
        actual = AgentEvaluationActual(
            status=harness_report.status,
            collaboration_status=report.status,
            delegation_count=report.delegation_count,
            reflection_rounds=report.reflection_rounds,
            llm_calls=report.llm_calls,
            evidence_reference_valid=set(references).issubset(allowed),
            budget_converged=(
                report.delegation_count <= case.budget.max_delegations
                and report.reflection_rounds
                <= case.budget.max_reflection_rounds
                and report.llm_calls <= case.budget.max_llm_calls
            ),
            reflection_recovered=(
                report.reflection_rounds > 0
                and report.status is AgentCollaborationStatus.ACCEPTED
            ),
            human_escalated=(
                report.status is AgentCollaborationStatus.HUMAN_REVIEW
            ),
            protocol_violation_detected=(
                report.status is AgentCollaborationStatus.FAILED
                and "AgentProtocolViolationError" in report.final_summary
            ),
        )
        expected = case.expected
        passed = all(
            (
                actual.status is expected.status,
                actual.collaboration_status is expected.collaboration_status,
                actual.delegation_count == expected.delegation_count,
                actual.reflection_rounds == expected.reflection_rounds,
                actual.llm_calls == expected.llm_calls,
                actual.protocol_violation_detected
                is expected.protocol_violation_detected,
                actual.evidence_reference_valid,
                actual.budget_converged,
            )
        )
        return AgentEvaluationResult(
            case_id=case.case_id,
            scenario=case.scenario,
            goal=case.goal,
            passed=passed,
            elapsed_ms=round((perf_counter() - started_at) * 1_000, 3),
            expected=expected,
            actual=actual,
        )


def load_agent_evaluation_suite(path: str | Path) -> AgentEvaluationSuite:
    return AgentEvaluationSuite.model_validate_json(Path(path).read_text("utf-8"))


def write_agent_evaluation_report(
    report: AgentEvaluationReport,
    path: str | Path,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def _allowed_references(state: AgentState) -> set[str]:
    from .agent_collaboration import build_collaboration_evidence

    _, references = build_collaboration_evidence(state)
    return references


def _resolve_reference_placeholders(
    value: Any,
    payload: Mapping[str, Any],
) -> Any:
    if isinstance(value, dict):
        return {
            key: _resolve_reference_placeholders(item, payload)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_resolve_reference_placeholders(item, payload) for item in value]
    if not isinstance(value, str) or not value.startswith("$ref:"):
        return value
    prefix = value.removeprefix("$ref:")
    if prefix == "unknown":
        return "external:invented-fact"
    return next(
        reference
        for reference in payload["evidence"]["allowed_references"]
        if reference.startswith(prefix + ":")
    )


def _aggregate_metrics(
    results: list[AgentEvaluationResult],
) -> AgentEvaluationMetrics:
    total = len(results)
    accept_cases = [result for result in results if result.goal == "accept"]
    reflection_cases = [
        result
        for result in results
        if result.goal == "accept" and result.expected.reflection_rounds > 0
    ]
    adversarial = [
        result
        for result in results
        if result.expected.protocol_violation_detected
    ]
    return AgentEvaluationMetrics(
        task_success_rate=_ratio(
            sum(
                result.actual.status is AgentHarnessStatus.COMPLETED
                for result in accept_cases
            ),
            len(accept_cases),
        ),
        evidence_reference_valid_rate=_ratio(
            sum(result.actual.evidence_reference_valid for result in results),
            total,
        ),
        reflection_recovery_rate=_ratio(
            sum(result.actual.reflection_recovered for result in reflection_cases),
            len(reflection_cases),
        ),
        human_escalation_rate=_ratio(
            sum(result.actual.human_escalated for result in results),
            total,
        ),
        budget_convergence_rate=_ratio(
            sum(result.actual.budget_converged for result in results),
            total,
        ),
        protocol_violation_rate=_ratio(
            sum(result.actual.protocol_violation_detected for result in results),
            total,
        ),
        protocol_violation_detection_rate=_ratio(
            sum(
                result.actual.protocol_violation_detected
                for result in adversarial
            ),
            len(adversarial),
        ),
        average_llm_calls=round(
            sum(result.actual.llm_calls for result in results) / total,
            3,
        ),
        average_delegations=round(
            sum(result.actual.delegation_count for result in results) / total,
            3,
        ),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0
