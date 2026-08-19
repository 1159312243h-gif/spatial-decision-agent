from __future__ import annotations

from threading import Barrier

from practice.site_selection import (
    AnalysisStatus,
    SiteSelectionWorkflowDependencies,
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
