from __future__ import annotations

from threading import Barrier
from dataclasses import replace

from app.site_selection_bootstrap import _fixture_poi_scoring_config

from practice.site_selection import (
    AnalysisScope,
    AnalysisStatus,
    EvidenceStatus,
    ProjectType,
    SiteSelectionWorkflowDependencies,
    build_parallel_site_selection_graph,
    build_site_selection_execution_plan,
    run_parallel_site_selection_workflow,
)
from tests.test_site_selection_workflow import (
    dependencies,
    manifests,
    request,
    target_frame,
)


def test_parallel_workflow_matches_auditable_business_result() -> None:
    result = run_parallel_site_selection_workflow(
        request(),
        manifests(),
        dependencies(),
    )

    assert result.status is AnalysisStatus.COMPLETED
    assert result.errors == []
    assert result.gis_evidence[0].metrics["area_hectares"] == 1
    assert result.poi_evidence[0].score_report is not None
    assert result.policy_evidence[0].rule_findings
    assert result.comparison_report is not None
    assert result.execution_plan is not None
    assert [trace.node_id for trace in result.agent_trace] == [
        "intake",
        "poi_evidence",
        "spatial_evidence",
        "policy_rules",
        "merge_gate",
        "review",
    ]
    assert {trace.status.value for trace in result.agent_trace} == {
        "succeeded"
    }


def test_market_selection_completes_without_inventing_land_evidence() -> None:
    market_request = request().model_copy(
        update={
            "project_type": ProjectType.COFFEE_SHOP,
            "analysis_scope": AnalysisScope.MARKET_SELECTION,
            "candidate_parcels": [
                parcel.model_copy(
                    update={
                        "area_hectares": None,
                        "geometry_dataset_id": None,
                    }
                )
                for parcel in request().candidate_parcels
            ],
        }
    )

    result = run_parallel_site_selection_workflow(
        market_request,
        manifests(),
        replace(
            dependencies(),
            poi_scoring_config=_fixture_poi_scoring_config(
                ProjectType.COFFEE_SHOP
            ),
            site_scoring_config=None,
        ),
    )

    assert result.status is AnalysisStatus.COMPLETED
    assert result.errors == []
    assert result.request.analysis_scope is AnalysisScope.MARKET_SELECTION
    assert result.comparison_report.ranking_basis == "poi_soft_score_desc"
    assert all(
        item.status is EvidenceStatus.NOT_RUN for item in result.gis_evidence
    )
    assert all(
        item.status is EvidenceStatus.NOT_RUN for item in result.policy_evidence
    )
    assert all(item.site_score_report is None for item in result.results)
    assert result.evidence_review_report.status.value == "ready"
    assert {
        issue.issue_code for issue in result.evidence_review_report.issues
    } >= {"land_compliance_unverified"}
    trace_statuses = {
        trace.node_id: trace.status.value for trace in result.agent_trace
    }
    assert trace_statuses["spatial_evidence"] == "skipped"
    assert trace_statuses["policy_rules"] == "skipped"


def test_runtime_graph_nodes_are_the_reviewed_plan_nodes() -> None:
    plan = build_site_selection_execution_plan()
    graph = build_parallel_site_selection_graph(dependencies()).get_graph()

    runtime_nodes = set(graph.nodes) - {"__start__", "__end__"}

    assert runtime_nodes == {step.node_id for step in plan.steps}


def test_poi_and_spatial_branches_start_concurrently() -> None:
    configured = dependencies()
    barrier = Barrier(2, timeout=2)

    class BarrierPOIGateway:
        first_search = True

        def search(self, query):
            if self.first_search:
                self.first_search = False
                barrier.wait()
            return configured.poi_gateway.search(query)

    class BarrierSpatialGateway:
        first_load = True

        def load(self, manifest):
            if self.first_load:
                self.first_load = False
                barrier.wait()
            return configured.spatial_gateway.load(manifest)

    parallel_dependencies = SiteSelectionWorkflowDependencies(
        poi_gateway=BarrierPOIGateway(),
        poi_scoring_config=configured.poi_scoring_config,
        spatial_gateway=BarrierSpatialGateway(),
        constraint_specs=configured.constraint_specs,
        rules=configured.rules,
        buffer_distance_m=configured.buffer_distance_m,
    )

    result = run_parallel_site_selection_workflow(
        request(),
        manifests(),
        parallel_dependencies,
    )

    assert result.status is AnalysisStatus.COMPLETED


def test_parallel_spatial_failure_is_sanitized_and_stops_policy() -> None:
    result = run_parallel_site_selection_workflow(
        request(),
        manifests(),
        dependencies(target=target_frame(crs=None)),
    )

    assert result.status is AnalysisStatus.FAILED
    assert result.policy_evidence == []
    assert result.results == []
    assert "spatial 失败" in result.errors[0]
    assert "missing_crs" in result.errors[0]
    trace_statuses = {
        trace.node_id: trace.status.value for trace in result.agent_trace
    }
    assert trace_statuses == {
        "intake": "succeeded",
        "poi_evidence": "succeeded",
        "spatial_evidence": "failed",
        "policy_rules": "skipped",
        "merge_gate": "failed",
        "review": "skipped",
    }
    spatial_trace = next(
        trace
        for trace in result.agent_trace
        if trace.node_id == "spatial_evidence"
    )
    assert spatial_trace.error_type == "SpatialAgentBlockedError"
