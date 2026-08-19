from __future__ import annotations

import pytest
from pydantic import ValidationError
from shapely.geometry import Point

from practice.site_selection import (
    GISMetricScoringRule,
    MissingMetricPolicy,
    ProjectType,
    ScoreDirection,
    SiteScoringConfig,
    SiteSelectionWorkflowDependencies,
    run_parallel_site_selection_workflow,
    run_site_selection_workflow,
)
from tests.test_site_selection_workflow import (
    constraint_frame,
    dependencies,
    manifests,
    request,
)


def scoring_config(
    *,
    metric_key: str = "area_hectares",
) -> SiteScoringConfig:
    return SiteScoringConfig(
        project_type=ProjectType.SHOPPING_MALL,
        version="site-score-fixture-1.0",
        gis_weight=0.4,
        poi_weight=0.6,
        gis_metric_rules=[
            GISMetricScoringRule(
                metric_key=metric_key,
                direction=ScoreDirection.HIGHER_IS_BETTER,
                lower_bound=0,
                upper_bound=2,
                weight=1,
                missing_policy=MissingMetricPolicy.BLOCK,
            )
        ],
    )


def composite_dependencies(
    *,
    config: SiteScoringConfig | None = None,
    constraint=None,
) -> SiteSelectionWorkflowDependencies:
    base = dependencies(constraint=constraint)
    return SiteSelectionWorkflowDependencies(
        poi_gateway=base.poi_gateway,
        poi_scoring_config=base.poi_scoring_config,
        spatial_gateway=base.spatial_gateway,
        constraint_specs=base.constraint_specs,
        rules=base.rules,
        buffer_distance_m=base.buffer_distance_m,
        site_scoring_config=config or scoring_config(),
    )


@pytest.mark.parametrize(
    "runner",
    [run_site_selection_workflow, run_parallel_site_selection_workflow],
)
def test_workflow_builds_traceable_gis_and_poi_score(runner) -> None:
    result = runner(
        request(),
        manifests(),
        composite_dependencies(),
    )

    report = result.site_score_reports[0]
    assert report.gis_component.score == pytest.approx(50)
    assert report.poi_score == pytest.approx(
        result.poi_evidence[0].score_report.total_score
    )
    assert report.total_score == pytest.approx(
        50 * 0.4 + report.poi_score * 0.6
    )
    assert result.results[0].site_score_report == report
    assert result.results[0].overall_soft_score == pytest.approx(
        report.total_score
    )
    assert result.comparison_report.scoring_version == "site-score-fixture-1.0"
    assert result.comparison_report.ranking_basis == "gis_poi_soft_score_desc"


def test_missing_configured_gis_metric_fails_closed() -> None:
    result = run_parallel_site_selection_workflow(
        request(),
        manifests(),
        composite_dependencies(config=scoring_config(metric_key="unknown_metric")),
    )

    assert result.status.value == "failed"
    assert result.results == []
    assert any("site_scoring" in error for error in result.errors)
    assert any("unknown_metric" in error for error in result.errors)


def test_hard_rule_match_does_not_change_soft_score() -> None:
    matched = run_parallel_site_selection_workflow(
        request(),
        manifests(),
        composite_dependencies(),
    )
    unmatched = run_parallel_site_selection_workflow(
        request(),
        manifests(),
        composite_dependencies(constraint=constraint_frame(Point(150, 50))),
    )

    assert matched.policy_evidence[0].rule_findings
    assert unmatched.policy_evidence[0].rule_findings == []
    assert matched.site_score_reports[0].total_score == pytest.approx(
        unmatched.site_score_reports[0].total_score
    )


def test_site_scoring_requires_explicit_valid_weights() -> None:
    payload = scoring_config().model_dump()
    payload["gis_weight"] = 0.8

    with pytest.raises(ValidationError, match="权重之和"):
        SiteScoringConfig.model_validate(payload)


def test_dependencies_reject_cross_project_scoring_config() -> None:
    base = dependencies()
    config_data = scoring_config().model_dump()
    config_data["project_type"] = "logistics_park"

    with pytest.raises(ValueError, match="项目类型不一致"):
        SiteSelectionWorkflowDependencies(
            poi_gateway=base.poi_gateway,
            poi_scoring_config=base.poi_scoring_config,
            spatial_gateway=base.spatial_gateway,
            constraint_specs=base.constraint_specs,
            rules=base.rules,
            site_scoring_config=SiteScoringConfig.model_validate(config_data),
        )
