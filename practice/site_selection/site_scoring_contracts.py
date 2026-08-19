from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain import NonEmptyString, ProjectType
from .poi_scoring import MissingMetricPolicy, ScoreDirection


class GISMetricScoringRule(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    metric_key: NonEmptyString
    direction: ScoreDirection
    lower_bound: float = Field(ge=0)
    upper_bound: float = Field(gt=0)
    weight: float = Field(gt=0, le=1)
    missing_policy: MissingMetricPolicy = MissingMetricPolicy.BLOCK

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> GISMetricScoringRule:
        if self.upper_bound <= self.lower_bound:
            raise ValueError("GIS 评分 upper_bound 必须大于 lower_bound")
        return self


class SiteScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    project_type: ProjectType
    version: NonEmptyString
    gis_weight: float = Field(gt=0, le=1)
    poi_weight: float = Field(gt=0, le=1)
    gis_metric_rules: list[GISMetricScoringRule] = Field(min_length=1)

    @field_validator("gis_metric_rules")
    @classmethod
    def metric_keys_are_unique(
        cls,
        rules: list[GISMetricScoringRule],
    ) -> list[GISMetricScoringRule]:
        keys = [rule.metric_key for rule in rules]
        if len(keys) != len(set(keys)):
            raise ValueError("GIS 评分指标不能重复")
        return rules

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> SiteScoringConfig:
        if abs(self.gis_weight + self.poi_weight - 1) > 1e-9:
            raise ValueError("GIS 与 POI 评分权重之和必须为 1")
        metric_weight = sum(rule.weight for rule in self.gis_metric_rules)
        if abs(metric_weight - 1) > 1e-9:
            raise ValueError("GIS 指标权重之和必须为 1")
        return self


class GISMetricScore(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    metric_key: NonEmptyString
    direction: ScoreDirection
    raw_value: float | None = None
    normalized_score: float = Field(ge=0, le=100)
    metric_weight: float = Field(gt=0, le=1)
    weighted_score: float = Field(ge=0, le=100)
    missing_policy: MissingMetricPolicy


class GISScoreComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    dataset_ids: list[NonEmptyString] = Field(min_length=1)
    metric_scores: list[GISMetricScore] = Field(min_length=1)
    score: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def score_matches_metrics(self) -> GISScoreComponent:
        expected = sum(item.weighted_score for item in self.metric_scores)
        if abs(self.score - expected) > 1e-7:
            raise ValueError("GIS 组件分必须等于指标加权分之和")
        return self


class SiteScoreReport(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    parcel_id: NonEmptyString
    project_type: ProjectType
    scoring_version: NonEmptyString
    poi_scoring_version: NonEmptyString
    gis_component: GISScoreComponent
    poi_score: float = Field(ge=0, le=100)
    gis_weight: float = Field(gt=0, le=1)
    poi_weight: float = Field(gt=0, le=1)
    total_score: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def total_is_traceable(self) -> SiteScoreReport:
        if abs(self.gis_weight + self.poi_weight - 1) > 1e-9:
            raise ValueError("场址总评分组件权重之和必须为 1")
        expected = (
            self.gis_component.score * self.gis_weight
            + self.poi_score * self.poi_weight
        )
        if abs(self.total_score - expected) > 1e-7:
            raise ValueError("场址总分必须等于 GIS 与 POI 组件加权分")
        return self
