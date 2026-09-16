from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.site_selection import SiteSelectionAnalysisResponse
from practice.site_selection import (
    AgentHarness,
    AgentHarnessConfig,
    AgentHarnessStatus,
    PromptBundle,
    PromptVersionRegistry,
    run_parallel_site_selection_workflow,
)
from tests.test_agent_collaboration import _runtime_for_reflection
from tests.test_site_selection_workflow import dependencies, manifests, request


def _bundle(runtime, version: str = "prompts-v1") -> PromptBundle:
    return PromptBundle(
        version=version,
        change_summary="fixture prompt bundle",
        created_at=datetime(2026, 9, 12, tzinfo=UTC),
        profiles={
            role: agent.profile
            for role, agent in runtime.roster.agents.items()
        },
    )


def test_harness_records_version_context_budget_and_terminal_state() -> None:
    deterministic = run_parallel_site_selection_workflow(
        request(),
        manifests(),
        dependencies(),
    )
    runtime, _, _ = _runtime_for_reflection()
    harness = AgentHarness(
        PromptVersionRegistry(_bundle(runtime)),
        lambda bundle: runtime,
        clock=lambda: datetime(2026, 9, 12, tzinfo=UTC),
    )

    reviewed = harness.review(
        deterministic,
        conversation_id="harness-test-001",
    )

    report = reviewed.agent_harness_report
    assert report is not None
    assert report.status is AgentHarnessStatus.COMPLETED
    assert report.prompt_version == "prompts-v1"
    assert report.context.evidence_reference_count > 1
    assert report.budget.used_llm_calls == 8
    assert report.budget.used_reflection_rounds == 1
    assert [trace.stage for trace in report.traces] == [
        "context_projection_and_guardrail",
        "multi_agent_review",
    ]
    assert (
        SiteSelectionAnalysisResponse.from_state(reviewed).agent_harness_report
        == report
    )


def test_harness_context_guardrail_fails_before_model_calls() -> None:
    deterministic = run_parallel_site_selection_workflow(
        request(),
        manifests(),
        dependencies(),
    )
    runtime, models, _ = _runtime_for_reflection()
    harness = AgentHarness(
        PromptVersionRegistry(_bundle(runtime)),
        lambda bundle: runtime,
        config=AgentHarnessConfig(max_evidence_references=1),
    )

    reviewed = harness.review(deterministic)

    assert reviewed.agent_harness_report is not None
    assert reviewed.agent_harness_report.status is AgentHarnessStatus.FAILED
    assert reviewed.collaboration_report is not None
    assert reviewed.collaboration_report.llm_calls == 0
    assert all(not model.calls for model in models.values())


def test_prompt_registry_requires_approval_and_keeps_rollback_audit() -> None:
    runtime, _, _ = _runtime_for_reflection()
    first = _bundle(runtime)
    second = first.model_copy(
        update={
            "version": "prompts-v2",
            "parent_version": first.version,
            "change_summary": "tighten citation instruction",
        }
    )
    registry = PromptVersionRegistry(first)
    registry.register(second)

    event = registry.activate(
        "prompts-v2",
        approval_reference="reviewer-001",
        activated_at=datetime(2026, 9, 12, tzinfo=UTC),
    )
    rollback = registry.rollback(
        "prompts-v1",
        approval_reference="reviewer-002",
        activated_at=datetime(2026, 9, 12, tzinfo=UTC),
    )

    assert event.previous_version == "prompts-v1"
    assert rollback.rollback is True
    assert registry.active_version == "prompts-v1"
    assert len(registry.events()) == 2
