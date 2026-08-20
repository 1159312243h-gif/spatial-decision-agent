from __future__ import annotations

import asyncio
from collections.abc import Iterable
from time import perf_counter
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .agent_orchestration import (
    AgentExecutionPlan,
    AgentStepStatus,
    AgentStepTrace,
    build_site_selection_execution_plan,
    order_agent_traces,
    trace_for,
)
from .agents import (
    PolicyAgent,
    PolicyAgentInput,
    ReviewAgent,
    ReviewAgentInput,
    SpatialAgent,
    SpatialAgentBlockedError,
    SpatialAgentInput,
)
from .comparison import CandidateComparisonBlockedError
from .domain import DatasetManifest, ProjectRequest
from .evidence import AgentState, AnalysisStatus
from .intake import ProjectIntakeSkill
from .poi_scoring import POIScoringError
from .poi_scoring_service import score_poi_state
from .poi_service import execute_poi_queries
from .results import ResultAssemblyBlockedError
from .rule_engine import (
    RuleConfigurationError,
    RuleEvaluationBlockedError,
)
from .spatial.analysis import GISAnalysisBlockedError
from .spatial.constraint_analysis import ConstraintAnalysisBlockedError
from .workflow import SiteSelectionWorkflowDependencies
from .site_scoring_service import SiteScoringError, score_site_state


class ParallelWorkflowState(TypedDict, total=False):
    """Internal graph state with one writer for every parallel branch field."""

    initial_state: AgentState
    poi_state: AgentState
    spatial_state: AgentState
    policy_state: AgentState
    merged_state: AgentState
    final_state: AgentState
    poi_error: str
    spatial_error: str
    policy_error: str
    poi_trace: AgentStepTrace
    spatial_trace: AgentStepTrace
    policy_trace: AgentStepTrace


def build_parallel_site_selection_graph(
    dependencies: SiteSelectionWorkflowDependencies,
):
    """Compile POI and spatial-policy branches with an explicit fan-in."""

    spatial_agent = SpatialAgent(
        dependencies.spatial_gateway,
        dependencies.constraint_specs,
        buffer_distance_m=dependencies.buffer_distance_m,
    )
    policy_agent = PolicyAgent(dependencies.rules)
    review_agent = ReviewAgent()
    plan = build_site_selection_execution_plan()
    poi_manifest = plan.step("poi_evidence")
    spatial_manifest = plan.step("spatial_evidence")
    policy_manifest = plan.step("policy_rules")
    merge_manifest = plan.step("merge_gate")
    review_manifest = plan.step("review")

    async def poi_branch(initial: AgentState) -> dict[str, AgentState | str]:
        started_at = perf_counter()
        try:
            result = await asyncio.to_thread(
                execute_poi_queries,
                initial,
                dependencies.poi_gateway,
            )
            result = await asyncio.to_thread(
                score_poi_state,
                result,
                dependencies.poi_scoring_config,
            )
        except Exception as exc:
            return {
                "poi_error": _branch_error("poi", exc),
                "poi_trace": trace_for(
                    poi_manifest,
                    AgentStepStatus.FAILED,
                    _elapsed_ms(started_at),
                    error_type=type(exc).__name__,
                ),
            }
        return {
            "poi_state": result,
            "poi_trace": trace_for(
                poi_manifest,
                AgentStepStatus.SUCCEEDED,
                _elapsed_ms(started_at),
            ),
        }

    async def spatial_branch(
        initial: AgentState,
    ) -> dict[str, AgentState | str]:
        started_at = perf_counter()
        try:
            output = await asyncio.to_thread(
                spatial_agent.run,
                SpatialAgentInput(state=initial),
            )
        except Exception as exc:
            return {
                "spatial_error": _branch_error("spatial", exc),
                "spatial_trace": trace_for(
                    spatial_manifest,
                    AgentStepStatus.FAILED,
                    _elapsed_ms(started_at),
                    error_type=type(exc).__name__,
                ),
            }
        return {
            "spatial_state": output.state,
            "spatial_trace": trace_for(
                spatial_manifest,
                AgentStepStatus.SUCCEEDED,
                _elapsed_ms(started_at),
            ),
        }

    async def parallel_sources(
        state: ParallelWorkflowState,
    ) -> dict[str, AgentState | str]:
        poi_update, spatial_update = await asyncio.gather(
            poi_branch(state["initial_state"]),
            spatial_branch(state["initial_state"]),
        )
        return {**poi_update, **spatial_update}

    async def policy_branch(
        state: ParallelWorkflowState,
    ) -> dict[str, AgentState | str]:
        if "spatial_error" in state:
            return {
                "policy_trace": trace_for(
                    policy_manifest,
                    AgentStepStatus.SKIPPED,
                    0,
                )
            }
        spatial_state = state.get("spatial_state")
        if spatial_state is None:
            return {
                "policy_error": "policy 失败：空间分支未返回状态",
                "policy_trace": trace_for(
                    policy_manifest,
                    AgentStepStatus.FAILED,
                    0,
                    error_type="MissingSpatialState",
                ),
            }
        started_at = perf_counter()
        try:
            output = await asyncio.to_thread(
                policy_agent.run,
                PolicyAgentInput(state=spatial_state),
            )
        except Exception as exc:
            return {
                "policy_error": _branch_error("policy", exc),
                "policy_trace": trace_for(
                    policy_manifest,
                    AgentStepStatus.FAILED,
                    _elapsed_ms(started_at),
                    error_type=type(exc).__name__,
                ),
            }
        return {
            "policy_state": output.state,
            "policy_trace": trace_for(
                policy_manifest,
                AgentStepStatus.SUCCEEDED,
                _elapsed_ms(started_at),
            ),
        }

    def merge_branches(
        state: ParallelWorkflowState,
    ) -> dict[str, AgentState]:
        started_at = perf_counter()
        branch_traces = [
            state[key]
            for key in ("poi_trace", "spatial_trace", "policy_trace")
            if key in state
        ]
        errors = [
            state[key]
            for key in ("poi_error", "spatial_error", "policy_error")
            if key in state
        ]
        if errors:
            merge_trace = trace_for(
                merge_manifest,
                AgentStepStatus.FAILED,
                _elapsed_ms(started_at),
                error_type="DependencyFailed",
            )
            return {
                "merged_state": _failed_state(
                    state["initial_state"],
                    errors,
                    plan=plan,
                    traces=[*branch_traces, merge_trace],
                )
            }

        poi_state = state.get("poi_state")
        policy_state = state.get("policy_state")
        if poi_state is None or policy_state is None:
            missing = []
            if poi_state is None:
                missing.append("poi_state")
            if policy_state is None:
                missing.append("policy_state")
            return {
                "merged_state": _failed_state(
                    state["initial_state"],
                    ["parallel_merge 失败：缺少 " + ", ".join(missing)],
                    plan=plan,
                    traces=[
                        *branch_traces,
                        trace_for(
                            merge_manifest,
                            AgentStepStatus.FAILED,
                            _elapsed_ms(started_at),
                            error_type="MissingBranchState",
                        ),
                    ],
                )
            }

        data = state["initial_state"].model_dump()
        data["poi_feature_sets"] = poi_state.poi_feature_sets
        data["poi_evidence"] = poi_state.poi_evidence
        data["gis_evidence"] = policy_state.gis_evidence
        data["policy_evidence"] = policy_state.policy_evidence
        data["status"] = AnalysisStatus.ANALYZING
        data["execution_plan"] = plan
        data["agent_trace"] = order_agent_traces(
            plan,
            [
                *state["initial_state"].agent_trace,
                *branch_traces,
                trace_for(
                    merge_manifest,
                    AgentStepStatus.SUCCEEDED,
                    _elapsed_ms(started_at),
                ),
            ],
        )
        merged = AgentState.model_validate(data)
        if dependencies.site_scoring_config is not None:
            try:
                merged = score_site_state(
                    merged,
                    dependencies.site_scoring_config,
                )
            except Exception as exc:
                return {
                    "merged_state": _failed_state(
                        merged,
                        [_branch_error("site_scoring", exc)],
                        plan=plan,
                        traces=[
                            trace.model_copy(
                                update={
                                    "status": AgentStepStatus.FAILED,
                                    "error_type": type(exc).__name__,
                                }
                            )
                            if trace.node_id == "merge_gate"
                            else trace
                            for trace in merged.agent_trace
                        ],
                    )
                }
        return {"merged_state": merged}

    def review_branch(
        state: ParallelWorkflowState,
    ) -> dict[str, AgentState]:
        merged = state["merged_state"]
        if merged.status is AnalysisStatus.FAILED:
            return {
                "final_state": _state_with_traces(
                    merged,
                    plan,
                    [
                        *merged.agent_trace,
                        trace_for(
                            review_manifest,
                            AgentStepStatus.SKIPPED,
                            0,
                        ),
                    ],
                )
            }
        started_at = perf_counter()
        try:
            output = review_agent.run(ReviewAgentInput(state=merged))
        except Exception as exc:
            return {
                "final_state": _failed_state(
                    merged,
                    [_branch_error("review", exc)],
                    plan=plan,
                    traces=[
                        *merged.agent_trace,
                        trace_for(
                            review_manifest,
                            AgentStepStatus.FAILED,
                            _elapsed_ms(started_at),
                            error_type=type(exc).__name__,
                        ),
                    ],
                )
            }
        return {
            "final_state": _state_with_traces(
                output.state,
                plan,
                [
                    *merged.agent_trace,
                    trace_for(
                        review_manifest,
                        AgentStepStatus.SUCCEEDED,
                        _elapsed_ms(started_at),
                    ),
                ],
            )
        }

    builder = StateGraph(ParallelWorkflowState)
    builder.add_node("parallel_sources", parallel_sources)
    builder.add_node("policy", policy_branch)
    builder.add_node("merge", merge_branches)
    builder.add_node("review", review_branch)
    builder.add_edge(START, "parallel_sources")
    builder.add_edge("parallel_sources", "policy")
    builder.add_edge("policy", "merge")
    builder.add_edge("merge", "review")
    builder.add_edge("review", END)
    return builder.compile()


def run_parallel_site_selection_workflow(
    request: ProjectRequest,
    datasets: Iterable[DatasetManifest],
    dependencies: SiteSelectionWorkflowDependencies,
    *,
    intake_skill: ProjectIntakeSkill | None = None,
) -> AgentState:
    """Run the dependency-correct parallel graph and return its final state."""

    return asyncio.run(
        run_parallel_site_selection_workflow_async(
            request,
            datasets,
            dependencies,
            intake_skill=intake_skill,
        )
    )


async def run_parallel_site_selection_workflow_async(
    request: ProjectRequest,
    datasets: Iterable[DatasetManifest],
    dependencies: SiteSelectionWorkflowDependencies,
    *,
    intake_skill: ProjectIntakeSkill | None = None,
) -> AgentState:
    """Async entrypoint for servers that already own an event loop."""

    plan = build_site_selection_execution_plan()
    intake_started_at = perf_counter()
    initial = (intake_skill or ProjectIntakeSkill()).run(request)
    data = initial.model_dump()
    data["datasets"] = [dataset.model_dump() for dataset in datasets]
    data["execution_plan"] = plan
    data["agent_trace"] = [
        trace_for(
            plan.step("intake"),
            AgentStepStatus.SUCCEEDED,
            _elapsed_ms(intake_started_at),
        )
    ]
    initial = AgentState.model_validate(data)
    output = await build_parallel_site_selection_graph(dependencies).ainvoke(
        {"initial_state": initial},
        config={"max_concurrency": 2},
    )
    return AgentState.model_validate(output["final_state"])


_EXPECTED_ERRORS = (
    CandidateComparisonBlockedError,
    ConstraintAnalysisBlockedError,
    GISAnalysisBlockedError,
    POIScoringError,
    ResultAssemblyBlockedError,
    RuleConfigurationError,
    RuleEvaluationBlockedError,
    SpatialAgentBlockedError,
    SiteScoringError,
)


def _branch_error(step_name: str, exc: Exception) -> str:
    detail = (
        str(exc)
        if isinstance(exc, _EXPECTED_ERRORS)
        else f"未处理异常：{type(exc).__name__}"
    )
    return f"{step_name} 失败：{detail}"


def _failed_state(
    state: AgentState,
    errors: list[str],
    *,
    plan: AgentExecutionPlan | None = None,
    traces: list[AgentStepTrace] | None = None,
) -> AgentState:
    data = state.model_dump()
    data["status"] = AnalysisStatus.FAILED
    data["errors"] = [*state.errors, *errors]
    data["results"] = []
    data["comparison_report"] = None
    if plan is not None:
        data["execution_plan"] = plan
    if traces is not None:
        active_plan = plan or state.execution_plan
        if active_plan is None:
            raise ValueError("失败状态 trace 必须绑定 Agent 执行计划")
        merged_traces = {trace.node_id: trace for trace in state.agent_trace}
        merged_traces.update({trace.node_id: trace for trace in traces})
        data["agent_trace"] = order_agent_traces(
            active_plan,
            list(merged_traces.values()),
        )
    return AgentState.model_validate(data)


def _state_with_traces(
    state: AgentState,
    plan: AgentExecutionPlan,
    traces: list[AgentStepTrace],
) -> AgentState:
    data = state.model_dump()
    data["execution_plan"] = plan
    data["agent_trace"] = order_agent_traces(plan, traces)
    return AgentState.model_validate(data)


def _elapsed_ms(started_at: float) -> float:
    return max(0.0, (perf_counter() - started_at) * 1_000)
