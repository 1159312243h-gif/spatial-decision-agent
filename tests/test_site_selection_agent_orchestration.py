from __future__ import annotations

import pytest
from pydantic import ValidationError

from practice.site_selection import (
    AgentExecutionPlan,
    AgentRole,
    AgentSkillManifest,
    AgentStepStatus,
    AgentStepTrace,
    build_site_selection_execution_plan,
    build_site_selection_supervisor_execution_plan,
    order_agent_traces,
)


def manifest(
    node_id: str,
    *,
    depends_on: list[str] | None = None,
) -> AgentSkillManifest:
    return AgentSkillManifest(
        node_id=node_id,
        role=AgentRole.ORCHESTRATOR,
        skill_name=f"{node_id}Skill",
        skill_version="v1",
        depends_on=depends_on or [],
        output_contract=f"{node_id}Output",
    )


def trace_for(step: AgentSkillManifest) -> AgentStepTrace:
    return AgentStepTrace(
        node_id=step.node_id,
        role=step.role,
        skill_name=step.skill_name,
        skill_version=step.skill_version,
        depends_on=step.depends_on,
        parallel_group=step.parallel_group,
        critical=step.critical,
        status=AgentStepStatus.SUCCEEDED,
        elapsed_ms=1,
    )


def test_default_plan_is_closed_acyclic_and_dependency_correct() -> None:
    plan = build_site_selection_execution_plan()
    steps = {step.node_id: step for step in plan.steps}

    assert [step.node_id for step in plan.steps] == [
        "intake",
        "poi_evidence",
        "spatial_evidence",
        "policy_rules",
        "merge_gate",
        "review",
    ]
    assert steps["poi_evidence"].parallel_group == "evidence_collection"
    assert steps["spatial_evidence"].parallel_group == "evidence_collection"
    assert steps["merge_gate"].depends_on == ["poi_evidence", "policy_rules"]
    assert all(step.llm_allowed is False for step in plan.steps)


def test_supervisor_plan_has_explicit_human_confirmation_dependency() -> None:
    plan = build_site_selection_supervisor_execution_plan()
    steps = {step.node_id: step for step in plan.steps}

    assert [step.node_id for step in plan.steps] == [
        "supervisor_intake",
        "candidate_discovery",
        "candidate_confirmation",
        "analysis_submitted",
        "analysis_wait",
        "analysis_completed",
    ]
    assert steps["candidate_confirmation"].depends_on == [
        "candidate_discovery"
    ]
    assert steps["analysis_submitted"].depends_on == [
        "candidate_confirmation"
    ]
    assert steps["analysis_wait"].depends_on == ["analysis_submitted"]
    assert steps["analysis_completed"].depends_on == ["analysis_wait"]
    assert all(step.llm_allowed is False for step in plan.steps)


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        ([manifest("a", depends_on=["missing"])], "未知依赖"),
        (
            [
                manifest("a", depends_on=["b"]),
                manifest("b", depends_on=["a"]),
            ],
            "循环依赖",
        ),
    ],
)
def test_plan_rejects_unknown_or_cyclic_dependencies(
    steps: list[AgentSkillManifest],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        AgentExecutionPlan(plan_id="invalid-plan", version="v1", steps=steps)


def test_plan_requires_topologically_ordered_steps_for_trace_order() -> None:
    with pytest.raises(ValidationError, match="拓扑顺序"):
        AgentExecutionPlan(
            plan_id="misordered-plan",
            version="v1",
            steps=[
                manifest("dependent", depends_on=["root"]),
                manifest("root"),
            ],
        )


def test_traces_are_ordered_by_plan_not_completion_order() -> None:
    plan = build_site_selection_execution_plan()
    traces = [trace_for(plan.step(node_id)) for node_id in (
        "review",
        "spatial_evidence",
        "intake",
    )]

    ordered = order_agent_traces(plan, traces)

    assert [trace.node_id for trace in ordered] == [
        "intake",
        "spatial_evidence",
        "review",
    ]


def test_trace_must_match_reviewed_skill_manifest() -> None:
    plan = build_site_selection_execution_plan()
    valid = trace_for(plan.step("intake"))
    invalid = valid.model_copy(update={"skill_version": "unreviewed-v2"})

    with pytest.raises(ValueError, match="manifest"):
        order_agent_traces(plan, [invalid])
