from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from practice.site_selection import (
    FrozenAgentEvaluationRunner,
    FrozenEvaluationRunner,
    PromptBundle,
    default_agent_profiles,
    load_agent_evaluation_suite,
)


ROOT = Path(__file__).parents[1]


def test_frozen_agent_suite_covers_success_reflection_and_guardrails() -> None:
    base_state = FrozenEvaluationRunner(
        ROOT / "data" / "fixtures"
    ).build_runtime_state()
    bundle = PromptBundle(
        version="prompts-v1",
        change_summary="fixture prompts",
        created_at=datetime(2026, 9, 12, tzinfo=UTC),
        profiles=default_agent_profiles("fixture-model"),
    )

    report = FrozenAgentEvaluationRunner(base_state, bundle).run_suite(
        load_agent_evaluation_suite(ROOT / "evals" / "agent-cases.json")
    )

    assert report.total == 6
    assert report.passed == 6
    assert report.failed == 0
    assert report.metrics.task_success_rate == 1
    assert report.metrics.evidence_reference_valid_rate == 1
    assert report.metrics.reflection_recovery_rate == 1
    assert report.metrics.budget_convergence_rate == 1
    assert report.metrics.protocol_violation_detection_rate == 1
    assert report.metrics.human_escalation_rate == pytest.approx(1 / 6, abs=1e-6)
