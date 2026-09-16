from __future__ import annotations

from datetime import UTC, datetime

import pytest

from practice.site_selection import (
    AgentEvaluationMetrics,
    AgentEvaluationReport,
    AgentEvolutionEngine,
    AgentRole,
    PromptBundle,
    PromptVersionRegistry,
    default_agent_profiles,
)


NOW = datetime(2026, 9, 12, tzinfo=UTC)


def _metrics(*, success: float = 1, calls: float = 4) -> AgentEvaluationMetrics:
    return AgentEvaluationMetrics(
        task_success_rate=success,
        evidence_reference_valid_rate=1,
        reflection_recovery_rate=1,
        human_escalation_rate=0,
        budget_convergence_rate=1,
        protocol_violation_rate=0.1,
        protocol_violation_detection_rate=1,
        average_llm_calls=calls,
        average_delegations=1,
    )


def _report(version: str, metrics: AgentEvaluationMetrics) -> AgentEvaluationReport:
    return AgentEvaluationReport.model_construct(
        suite_id="agent-suite",
        suite_version="1.0.0",
        prompt_version=version,
        generated_at=NOW,
        total=1,
        passed=1,
        failed=0,
        metrics=metrics,
        results=[],
        environment={"runtime": "fixture"},
    )


def _engine() -> tuple[AgentEvolutionEngine, PromptVersionRegistry]:
    bundle = PromptBundle(
        version="prompts-v1",
        change_summary="baseline",
        created_at=NOW,
        profiles=default_agent_profiles("fixture-model"),
    )
    registry = PromptVersionRegistry(bundle)
    return AgentEvolutionEngine(registry), registry


def test_evolution_requires_gate_and_human_approval_then_can_rollback() -> None:
    engine, registry = _engine()
    candidate = engine.propose_candidate(
        version="prompts-v2",
        prompt_updates={
            AgentRole.REVIEW: "必须逐条核验引用；信息不足时转人工复核。"
        },
        hypothesis="reduce unsupported review conclusions",
        generated_by="offline-bad-case-optimizer",
        created_at=NOW,
    )
    decision = engine.evaluate(
        _report("prompts-v1", _metrics()),
        _report(candidate.bundle.version, _metrics()),
        evaluated_at=NOW,
    )

    assert decision.gate_passed is True
    with pytest.raises(ValueError, match="人工明确批准"):
        engine.promote(decision.decision_id, approved_by="")
    engine.promote(decision.decision_id, approved_by="reviewer-001")
    assert registry.active_version == "prompts-v2"
    engine.rollback("prompts-v1", approved_by="reviewer-002")
    assert registry.active_version == "prompts-v1"


def test_evolution_rejects_task_regression() -> None:
    engine, _ = _engine()
    candidate = engine.propose_candidate(
        version="prompts-v2",
        prompt_updates={AgentRole.POI: "核验 POI 证据。"},
        hypothesis="shorter prompt",
        generated_by="offline-optimizer",
        created_at=NOW,
    )
    decision = engine.evaluate(
        _report("prompts-v1", _metrics(success=1)),
        _report(candidate.bundle.version, _metrics(success=0.8)),
        evaluated_at=NOW,
    )

    assert decision.gate_passed is False
    assert "任务成功率相对 Baseline 回退" in decision.gate_failures
    with pytest.raises(ValueError, match="未通过冻结评测门禁"):
        engine.promote(decision.decision_id, approved_by="reviewer-001")
