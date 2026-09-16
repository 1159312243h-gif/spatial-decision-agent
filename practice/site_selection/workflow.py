from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from .comparison import CandidateComparisonBlockedError, compare_candidate_results
from .agent_collaboration import MultiAgentReviewRuntime
from .agent_harness import AgentHarness
from .analysis_scope import (
    is_market_selection,
    mark_market_policy_unverified,
    mark_market_spatial_unverified,
)
from .constraints import ConstraintLayerSpec
from .domain import DatasetManifest, ProjectRequest
from .evidence import AgentState, AnalysisStatus, EvidenceStatus
from .evidence_review import (
    EvidenceReviewBlockedError,
    review_site_selection_evidence,
)
from .intake import ProjectIntakeSkill
from .poi_scoring import POIScoringConfig, POIScoringError
from .poi_scoring_service import score_poi_state
from .poi_service import POIGateway, execute_poi_queries
from .results import ResultAssemblyBlockedError, assemble_analysis_results
from .rule_engine import (
    RuleConfigurationError,
    RuleEvaluationBlockedError,
    evaluate_policy_rules,
)
from .rules import RuleDefinition
from .spatial.analysis import GISAnalysisBlockedError, run_gis_analysis
from .spatial.constraint_analysis import (
    ConstraintAnalysisBlockedError,
    run_spatial_constraint_analysis,
)
from .spatial.gateway import SpatialDatasetGateway, collect_gis_evidence
from .site_scoring_contracts import SiteScoringConfig
from .site_scoring_service import SiteScoringError, score_site_state


RouteName = Literal["next", "failed"]


class WorkflowEvidenceBlockedError(RuntimeError):
    """Raised when a collection node produces non-ready mandatory evidence."""


@dataclass(frozen=True)
class SiteSelectionWorkflowDependencies:
    """Explicit runtime dependencies for the deterministic business graph."""

    poi_gateway: POIGateway
    poi_scoring_config: POIScoringConfig
    spatial_gateway: SpatialDatasetGateway
    constraint_specs: Sequence[ConstraintLayerSpec]
    rules: Sequence[RuleDefinition]
    buffer_distance_m: float = 500
    site_scoring_config: SiteScoringConfig | None = None
    multi_agent_runtime: MultiAgentReviewRuntime | AgentHarness | None = None

    def __post_init__(self) -> None:
        specs = tuple(self.constraint_specs)
        rules = tuple(self.rules)
        if not specs:
            raise ValueError("业务工作流至少需要一个空间约束配置")
        if not rules:
            raise ValueError("业务工作流至少需要一条版本化规则")
        if self.buffer_distance_m <= 0:
            raise ValueError("业务工作流缓冲距离必须大于 0")
        if (
            self.site_scoring_config is not None
            and self.site_scoring_config.project_type
            is not self.poi_scoring_config.project_type
        ):
            raise ValueError("场址评分配置与 POI 评分配置项目类型不一致")
        object.__setattr__(self, "constraint_specs", specs)
        object.__setattr__(self, "rules", rules)


def route_after_step(state: AgentState) -> RouteName:
    return "failed" if state.status is AnalysisStatus.FAILED else "next"


def build_site_selection_graph(
    dependencies: SiteSelectionWorkflowDependencies,
):
    """Compile the deterministic site-selection business workflow."""

    builder = StateGraph(AgentState)
    builder.add_node(
        "poi",
        _safe_node(
            "poi",
            lambda state: execute_poi_queries(
                state,
                dependencies.poi_gateway,
            ),
        ),
    )
    builder.add_node(
        "poi_scoring",
        _safe_node(
            "poi_scoring",
            lambda state: score_poi_state(
                state,
                dependencies.poi_scoring_config,
            ),
        ),
    )
    builder.add_node(
        "gis_collection",
        _safe_node(
            "gis_collection",
            lambda state: (
                mark_market_spatial_unverified(state)
                if is_market_selection(state)
                else _collect_ready_gis_evidence(
                    state,
                    dependencies.spatial_gateway,
                )
            ),
        ),
    )
    builder.add_node(
        "gis_metrics",
        _safe_node(
            "gis_metrics",
            lambda state: (
                state
                if is_market_selection(state)
                else run_gis_analysis(
                    state,
                    dependencies.spatial_gateway,
                    buffer_distance_m=dependencies.buffer_distance_m,
                )
            ),
        ),
    )
    builder.add_node(
        "spatial_constraints",
        _safe_node(
            "spatial_constraints",
            lambda state: (
                state
                if is_market_selection(state)
                else run_spatial_constraint_analysis(
                    state,
                    dependencies.spatial_gateway,
                    dependencies.constraint_specs,
                )
            ),
        ),
    )
    builder.add_node(
        "policy_rules",
        _safe_node(
            "policy_rules",
            lambda state: (
                mark_market_policy_unverified(state)
                if is_market_selection(state)
                else evaluate_policy_rules(
                    state,
                    dependencies.rules,
                )
            ),
        ),
    )
    builder.add_node(
        "site_scoring",
        _safe_node(
            "site_scoring",
            lambda state: (
                score_site_state(state, dependencies.site_scoring_config)
                if dependencies.site_scoring_config is not None
                and not is_market_selection(state)
                else state
            ),
        ),
    )
    builder.add_node(
        "results",
        _safe_node("results", assemble_analysis_results),
    )
    builder.add_node(
        "comparison",
        _safe_node("comparison", compare_candidate_results),
    )
    builder.add_node(
        "evidence_review",
        _safe_node(
            "evidence_review",
            lambda state: _review_with_optional_collaboration(
                state,
                dependencies.multi_agent_runtime,
            ),
        ),
    )
    builder.add_node("failed", _failed_node)

    builder.add_edge(START, "poi")
    _add_guarded_edge(builder, "poi", "poi_scoring")
    _add_guarded_edge(builder, "poi_scoring", "gis_collection")
    _add_guarded_edge(builder, "gis_collection", "gis_metrics")
    _add_guarded_edge(builder, "gis_metrics", "spatial_constraints")
    _add_guarded_edge(builder, "spatial_constraints", "site_scoring")
    _add_guarded_edge(builder, "site_scoring", "policy_rules")
    _add_guarded_edge(builder, "policy_rules", "results")
    _add_guarded_edge(builder, "results", "comparison")
    _add_guarded_edge(builder, "comparison", "evidence_review")
    builder.add_edge("evidence_review", END)
    builder.add_edge("failed", END)
    return builder.compile()


def run_site_selection_workflow(
    request: ProjectRequest,
    datasets: Iterable[DatasetManifest],
    dependencies: SiteSelectionWorkflowDependencies,
    *,
    intake_skill: ProjectIntakeSkill | None = None,
) -> AgentState:
    """Create intake state, run the graph, and return a validated result."""

    initial = (intake_skill or ProjectIntakeSkill()).run(request)
    initial_data = initial.model_dump()
    initial_data["datasets"] = [
        dataset.model_dump()
        for dataset in datasets
    ]
    initial = AgentState.model_validate(initial_data)

    output = build_site_selection_graph(dependencies).invoke(initial)
    if isinstance(output, AgentState):
        return output
    return AgentState.model_validate(output)


def _add_guarded_edge(
    builder: StateGraph,
    source: str,
    next_node: str,
) -> None:
    builder.add_conditional_edges(
        source,
        route_after_step,
        {
            "next": next_node,
            "failed": "failed",
        },
    )


def _safe_node(
    step_name: str,
    operation: Callable[[AgentState], AgentState],
) -> Callable[[AgentState], dict[str, Any]]:
    def node(state: AgentState) -> dict[str, Any]:
        try:
            result = operation(state)
        except Exception as exc:
            return _failure_update(state, step_name, exc)

        result_data = result.model_dump()
        if result.status is not AnalysisStatus.COMPLETED:
            result_data["status"] = AnalysisStatus.ANALYZING
        return result_data

    return node


def _collect_ready_gis_evidence(
    state: AgentState,
    gateway: SpatialDatasetGateway,
) -> AgentState:
    result = collect_gis_evidence(state, gateway)
    issues = [
        (
            f"{evidence.parcel_id}: status={evidence.status.value}, "
            f"notes={'; '.join(evidence.notes) or 'none'}"
        )
        for evidence in result.gis_evidence
        if evidence.status is not EvidenceStatus.READY
    ]
    if issues:
        raise WorkflowEvidenceBlockedError(
            "GIS 强制证据未就绪：" + " | ".join(issues)
        )
    return result


def _review_with_optional_collaboration(
    state: AgentState,
    runtime: MultiAgentReviewRuntime | AgentHarness | None,
) -> AgentState:
    reviewed = review_site_selection_evidence(state)
    return runtime.review(reviewed) if runtime is not None else reviewed


_EXPECTED_ERRORS = (
    CandidateComparisonBlockedError,
    EvidenceReviewBlockedError,
    ConstraintAnalysisBlockedError,
    GISAnalysisBlockedError,
    POIScoringError,
    ResultAssemblyBlockedError,
    RuleConfigurationError,
    RuleEvaluationBlockedError,
    SiteScoringError,
    WorkflowEvidenceBlockedError,
)


def _failure_update(
    state: AgentState,
    step_name: str,
    exc: Exception,
) -> dict[str, Any]:
    if isinstance(exc, _EXPECTED_ERRORS):
        detail = str(exc)
    else:
        detail = f"未处理异常：{type(exc).__name__}"

    state_data = state.model_dump()
    state_data["status"] = AnalysisStatus.FAILED
    state_data["errors"] = [
        *state.errors,
        f"{step_name} 失败：{detail}",
    ]
    return state_data


def _failed_node(state: AgentState) -> dict[str, Any]:
    return {
        "status": AnalysisStatus.FAILED,
        "results": [],
        "comparison_report": None,
    }
