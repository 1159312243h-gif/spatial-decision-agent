from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from math import isfinite
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain import NonEmptyString, ProjectType
from .poi import POIFeatureSet, POIMetric
from .profiles import POICategoryConfig, ProjectProfile


class ScoreDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class MissingMetricPolicy(StrEnum):
    BLOCK = "block"
    ZERO = "zero"


class POIScoringError(RuntimeError):
    """Raised when POI inputs cannot be scored deterministically."""


class POIMetricScoringRule(BaseModel):
    """Linear normalization rule for one raw POI metric."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    metric: POIMetric
    direction: ScoreDirection
    lower_bound: float = Field(ge=0)
    upper_bound: float = Field(gt=0)
    weight: float = Field(gt=0, le=1)
    missing_policy: MissingMetricPolicy = MissingMetricPolicy.BLOCK

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> POIMetricScoringRule:
        if self.upper_bound <= self.lower_bound:
            raise ValueError("评分 upper_bound 必须大于 lower_bound")
        return self


class POIGroupScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_key: NonEmptyString
    metric_rules: Annotated[
        list[POIMetricScoringRule],
        Field(min_length=1),
    ]

    @model_validator(mode="after")
    def metric_rules_are_complete(self) -> POIGroupScoringConfig:
        metrics = [rule.metric for rule in self.metric_rules]
        if len(metrics) != len(set(metrics)):
            raise ValueError("同一 POI 分组的评分指标不能重复")
        weight_sum = sum(rule.weight for rule in self.metric_rules)
        if abs(weight_sum - 1.0) > 1e-9:
            raise ValueError("POI 分组内指标权重之和必须为 1")
        return self


class POIScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_type: ProjectType
    version: NonEmptyString
    groups: Annotated[list[POIGroupScoringConfig], Field(min_length=1)]

    @field_validator("groups")
    @classmethod
    def group_keys_are_unique(
        cls,
        groups: list[POIGroupScoringConfig],
    ) -> list[POIGroupScoringConfig]:
        keys = [group.group_key for group in groups]
        if len(keys) != len(set(keys)):
            raise ValueError("POI 评分分组标识不能重复")
        return groups


class POIMetricScore(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    metric: POIMetric
    direction: ScoreDirection
    raw_value: float | None = None
    normalized_score: float = Field(ge=0, le=100)
    metric_weight: float = Field(gt=0, le=1)
    weighted_score: float = Field(ge=0, le=100)
    missing_policy: MissingMetricPolicy


class POIGroupScore(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    group_key: NonEmptyString
    query_id: NonEmptyString
    source_dataset_id: NonEmptyString
    metric_scores: Annotated[list[POIMetricScore], Field(min_length=1)]
    group_score: float = Field(ge=0, le=100)
    profile_weight: float = Field(gt=0, le=1)
    weighted_score: float = Field(ge=0, le=100)


class POIScoreReport(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    parcel_id: NonEmptyString
    project_type: ProjectType
    scoring_version: NonEmptyString
    group_scores: Annotated[list[POIGroupScore], Field(min_length=1)]
    total_score: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def totals_and_groups_are_consistent(self) -> POIScoreReport:
        group_keys = [group.group_key for group in self.group_scores]
        if len(group_keys) != len(set(group_keys)):
            raise ValueError("POI 评分报告分组不能重复")
        expected_total = sum(group.weighted_score for group in self.group_scores)
        if abs(self.total_score - expected_total) > 1e-7:
            raise ValueError("POI 总分必须等于分组加权分之和")
        return self


def normalize_metric_value(
    value: float,
    rule: POIMetricScoringRule,
) -> float:
    """Normalize one finite raw value to a clamped 0-100 score."""

    if not isfinite(value):
        raise POIScoringError(f"POI 指标值必须为有限数：{rule.metric.value}")

    span = rule.upper_bound - rule.lower_bound
    if rule.direction is ScoreDirection.HIGHER_IS_BETTER:
        ratio = (value - rule.lower_bound) / span
    else:
        ratio = (rule.upper_bound - value) / span
    return min(100.0, max(0.0, ratio * 100.0))


def score_poi_feature_sets(
    profile: ProjectProfile,
    config: POIScoringConfig,
    feature_sets: Iterable[POIFeatureSet],
) -> POIScoreReport:
    """Score one parcel's feature sets with a versioned transparent config."""

    if profile.project_type is not config.project_type:
        raise POIScoringError("评分配置项目类型必须与 ProjectProfile 一致")

    feature_list = list(feature_sets)
    if not feature_list:
        raise POIScoringError("POI 评分至少需要一个 FeatureSet")
    parcel_ids = {item.query.parcel_id for item in feature_list}
    if len(parcel_ids) != 1:
        raise POIScoringError("一次 POI 评分只能处理一个候选地块")

    profile_groups = _index_profile_groups(profile.poi_groups)
    scoring_groups = _index_scoring_groups(config.groups)
    features_by_group = _index_feature_sets(feature_list)
    _require_same_group_keys(profile_groups, scoring_groups, "评分配置")
    _require_same_group_keys(profile_groups, features_by_group, "POI 数据")

    group_scores = [
        _score_group(
            profile_groups[group.group_key],
            scoring_groups[group.group_key],
            features_by_group[group.group_key],
        )
        for group in profile.poi_groups
    ]
    total_score = sum(group.weighted_score for group in group_scores)
    return POIScoreReport(
        parcel_id=next(iter(parcel_ids)),
        project_type=profile.project_type,
        scoring_version=config.version,
        group_scores=group_scores,
        total_score=total_score,
    )


def _index_profile_groups(
    groups: Iterable[POICategoryConfig],
) -> dict[str, POICategoryConfig]:
    return {group.group_key: group for group in groups}


def _index_scoring_groups(
    groups: Iterable[POIGroupScoringConfig],
) -> dict[str, POIGroupScoringConfig]:
    return {group.group_key: group for group in groups}


def _index_feature_sets(
    feature_sets: Iterable[POIFeatureSet],
) -> dict[str, POIFeatureSet]:
    indexed: dict[str, POIFeatureSet] = {}
    for feature_set in feature_sets:
        group_key = feature_set.query.group_key
        if group_key in indexed:
            raise POIScoringError(f"候选地块存在重复 POI 分组：{group_key}")
        indexed[group_key] = feature_set
    return indexed


def _require_same_group_keys(
    profile_groups: dict[str, object],
    actual_groups: dict[str, object],
    label: str,
) -> None:
    profile_keys = set(profile_groups)
    actual_keys = set(actual_groups)
    if profile_keys != actual_keys:
        missing = sorted(profile_keys - actual_keys)
        extra = sorted(actual_keys - profile_keys)
        raise POIScoringError(
            f"{label}分组与 ProjectProfile 不一致："
            f"missing={missing}, extra={extra}"
        )


def _score_group(
    profile_group: POICategoryConfig,
    scoring_group: POIGroupScoringConfig,
    feature_set: POIFeatureSet,
) -> POIGroupScore:
    configured_metrics = {rule.metric for rule in scoring_group.metric_rules}
    profile_metrics = set(profile_group.metrics)
    if configured_metrics != profile_metrics:
        missing = sorted(metric.value for metric in profile_metrics - configured_metrics)
        extra = sorted(metric.value for metric in configured_metrics - profile_metrics)
        raise POIScoringError(
            f"评分指标与 Profile 分组不一致：{profile_group.group_key}, "
            f"missing={missing}, extra={extra}"
        )

    metric_scores = [
        _score_metric(scoring_group.group_key, rule, feature_set)
        for rule in scoring_group.metric_rules
    ]
    group_score = sum(item.weighted_score for item in metric_scores)
    weighted_score = group_score * profile_group.soft_score_weight
    return POIGroupScore(
        group_key=profile_group.group_key,
        query_id=feature_set.query.query_id,
        source_dataset_id=feature_set.source.dataset_id,
        metric_scores=metric_scores,
        group_score=group_score,
        profile_weight=profile_group.soft_score_weight,
        weighted_score=weighted_score,
    )


def _score_metric(
    group_key: str,
    rule: POIMetricScoringRule,
    feature_set: POIFeatureSet,
) -> POIMetricScore:
    raw_value = feature_set.metrics.get(rule.metric)
    if raw_value is None:
        if rule.missing_policy is MissingMetricPolicy.BLOCK:
            raise POIScoringError(
                f"POI 评分缺少指标：group={group_key}, metric={rule.metric.value}"
            )
        normalized_score = 0.0
    else:
        normalized_score = normalize_metric_value(raw_value, rule)

    return POIMetricScore(
        metric=rule.metric,
        direction=rule.direction,
        raw_value=raw_value,
        normalized_score=normalized_score,
        metric_weight=rule.weight,
        weighted_score=normalized_score * rule.weight,
        missing_policy=rule.missing_policy,
    )
