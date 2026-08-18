from datetime import datetime, timezone
from math import inf, nan

import pytest
from pydantic import ValidationError

from practice.site_selection import (
    CandidateParcel,
    MissingMetricPolicy,
    POIFeatureSet,
    POIGroupScoringConfig,
    POIMetric,
    POIMetricScoringRule,
    POIProvider,
    POIScoringConfig,
    POIScoringError,
    POISourceMeta,
    ProjectRequest,
    ProjectType,
    ScoreDirection,
    build_poi_queries,
    get_project_profile,
    normalize_metric_value,
    score_poi_feature_sets,
)


NOW = datetime(2026, 8, 18, 23, 58, tzinfo=timezone.utc)


def metric_rule(
    *,
    metric: POIMetric = POIMetric.COUNT,
    direction: ScoreDirection = ScoreDirection.HIGHER_IS_BETTER,
    lower: float = 0,
    upper: float = 100,
    weight: float = 1,
    missing_policy: MissingMetricPolicy = MissingMetricPolicy.BLOCK,
) -> POIMetricScoringRule:
    return POIMetricScoringRule(
        metric=metric,
        direction=direction,
        lower_bound=lower,
        upper_bound=upper,
        weight=weight,
        missing_policy=missing_policy,
    )


def scoring_config(
    *,
    missing_policy: MissingMetricPolicy = MissingMetricPolicy.BLOCK,
) -> POIScoringConfig:
    profile = get_project_profile(ProjectType.SHOPPING_MALL)
    groups = []
    for group in profile.poi_groups:
        weight = 1 / len(group.metrics)
        groups.append(
            POIGroupScoringConfig(
                group_key=group.group_key,
                metric_rules=[
                    metric_rule(
                        metric=metric,
                        direction=(
                            ScoreDirection.LOWER_IS_BETTER
                            if metric in {
                                POIMetric.NEAREST_DISTANCE_M,
                                POIMetric.AVERAGE_DISTANCE_M,
                            }
                            else ScoreDirection.HIGHER_IS_BETTER
                        ),
                        weight=weight,
                        missing_policy=missing_policy,
                    )
                    for metric in group.metrics
                ],
            )
        )
    return POIScoringConfig(
        project_type=ProjectType.SHOPPING_MALL,
        version="demo-1.0",
        groups=groups,
    )


def feature_sets(
    *,
    missing_group: str | None = None,
    missing_metric: POIMetric | None = None,
    parcel_id: str = "A01",
) -> list[POIFeatureSet]:
    profile = get_project_profile(ProjectType.SHOPPING_MALL)
    request = ProjectRequest(
        request_id="REQ-score",
        project_type=ProjectType.SHOPPING_MALL,
        candidate_parcels=[
            CandidateParcel(
                parcel_id=parcel_id,
                longitude=121.47,
                latitude=31.23,
            )
        ],
        requested_at=NOW,
    )
    queries = build_poi_queries(request, profile)
    items = []
    for query, group in zip(queries, profile.poi_groups, strict=True):
        metrics = {metric: 50.0 for metric in group.metrics}
        if query.group_key == missing_group and missing_metric is not None:
            metrics.pop(missing_metric, None)
        items.append(
            POIFeatureSet(
                query=query,
                records=[],
                source=POISourceMeta(
                    provider=POIProvider.MOCK,
                    dataset_id=f"poi-{query.group_key}",
                    queried_at=NOW,
                    record_count=0,
                ),
                metrics=metrics,
            )
        )
    return items


@pytest.mark.parametrize(
    ("value", "expected"),
    [(-10, 0), (50, 50), (110, 100)],
)
def test_higher_is_better_is_linear_and_clamped(
    value: float,
    expected: float,
) -> None:
    assert normalize_metric_value(value, metric_rule()) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(-10, 100), (50, 50), (110, 0)],
)
def test_lower_is_better_is_linear_and_clamped(
    value: float,
    expected: float,
) -> None:
    rule = metric_rule(direction=ScoreDirection.LOWER_IS_BETTER)

    assert normalize_metric_value(value, rule) == pytest.approx(expected)


def test_scoring_bounds_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="upper_bound"):
        metric_rule(lower=100, upper=100)


def test_metric_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match="权重之和"):
        POIGroupScoringConfig(
            group_key="public_transit",
            metric_rules=[
                metric_rule(metric=POIMetric.COUNT, weight=0.4),
                metric_rule(
                    metric=POIMetric.NEAREST_DISTANCE_M,
                    weight=0.4,
                ),
            ],
        )


def test_group_metrics_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="不能重复"):
        POIGroupScoringConfig(
            group_key="public_transit",
            metric_rules=[
                metric_rule(weight=0.5),
                metric_rule(weight=0.5),
            ],
        )


def test_scoring_group_keys_must_be_unique() -> None:
    group = POIGroupScoringConfig(
        group_key="public_transit",
        metric_rules=[metric_rule()],
    )

    with pytest.raises(ValidationError, match="分组标识不能重复"):
        POIScoringConfig(
            project_type=ProjectType.SHOPPING_MALL,
            version="invalid",
            groups=[group, group],
        )


def test_midpoint_inputs_produce_auditable_fifty_point_report() -> None:
    profile = get_project_profile(ProjectType.SHOPPING_MALL)

    report = score_poi_feature_sets(
        profile,
        scoring_config(),
        feature_sets(),
    )

    assert report.parcel_id == "A01"
    assert report.scoring_version == "demo-1.0"
    assert report.total_score == pytest.approx(50)
    assert len(report.group_scores) == len(profile.poi_groups)
    assert all(group.group_score == pytest.approx(50) for group in report.group_scores)
    assert report.group_scores[0].source_dataset_id == "poi-public_transit"
    assert report.group_scores[0].metric_scores[0].raw_value == 50


def test_project_type_mismatch_is_blocked() -> None:
    config = scoring_config().model_copy(
        update={"project_type": ProjectType.LOGISTICS_PARK}
    )

    with pytest.raises(POIScoringError, match="项目类型"):
        score_poi_feature_sets(
            get_project_profile(ProjectType.SHOPPING_MALL),
            config,
            feature_sets(),
        )


def test_config_must_cover_exact_profile_groups() -> None:
    config_data = scoring_config().model_dump()
    config_data["groups"] = config_data["groups"][:-1]
    config = POIScoringConfig.model_validate(config_data)

    with pytest.raises(POIScoringError, match="评分配置分组"):
        score_poi_feature_sets(
            get_project_profile(ProjectType.SHOPPING_MALL),
            config,
            feature_sets(),
        )


def test_config_must_cover_exact_profile_metrics() -> None:
    config_data = scoring_config().model_dump()
    first_group = config_data["groups"][0]
    first_group["metric_rules"] = [first_group["metric_rules"][0]]
    first_group["metric_rules"][0]["weight"] = 1
    config = POIScoringConfig.model_validate(config_data)

    with pytest.raises(POIScoringError, match="评分指标"):
        score_poi_feature_sets(
            get_project_profile(ProjectType.SHOPPING_MALL),
            config,
            feature_sets(),
        )


def test_duplicate_feature_group_is_blocked() -> None:
    items = feature_sets()
    items.append(items[0].model_copy(deep=True))

    with pytest.raises(POIScoringError, match="重复 POI 分组"):
        score_poi_feature_sets(
            get_project_profile(ProjectType.SHOPPING_MALL),
            scoring_config(),
            items,
        )


def test_missing_metric_blocks_by_default() -> None:
    with pytest.raises(POIScoringError, match="缺少指标"):
        score_poi_feature_sets(
            get_project_profile(ProjectType.SHOPPING_MALL),
            scoring_config(),
            feature_sets(
                missing_group="public_transit",
                missing_metric=POIMetric.COUNT,
            ),
        )


def test_explicit_zero_policy_scores_missing_metric_as_zero() -> None:
    report = score_poi_feature_sets(
        get_project_profile(ProjectType.SHOPPING_MALL),
        scoring_config(missing_policy=MissingMetricPolicy.ZERO),
        feature_sets(
            missing_group="public_transit",
            missing_metric=POIMetric.COUNT,
        ),
    )

    first_metric = report.group_scores[0].metric_scores[0]
    assert first_metric.raw_value is None
    assert first_metric.normalized_score == 0
    assert report.total_score < 50


@pytest.mark.parametrize("value", [nan, inf, -inf])
def test_non_finite_raw_metric_is_blocked(value: float) -> None:
    with pytest.raises(POIScoringError, match="有限数"):
        normalize_metric_value(value, metric_rule())
