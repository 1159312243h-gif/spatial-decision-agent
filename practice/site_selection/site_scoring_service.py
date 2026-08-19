from __future__ import annotations

from math import isfinite

from .evidence import AgentState, EvidenceStatus, GISEvidence, POIEvidence
from .poi_scoring import MissingMetricPolicy, ScoreDirection
from .site_scoring_contracts import (
    GISMetricScore,
    GISMetricScoringRule,
    GISScoreComponent,
    SiteScoreReport,
    SiteScoringConfig,
)


class SiteScoringError(RuntimeError):
    """Raised when GIS and POI evidence cannot be scored together safely."""


def score_site_state(
    state: AgentState,
    config: SiteScoringConfig,
) -> AgentState:
    if state.request.project_type is not config.project_type:
        raise SiteScoringError("场址评分配置项目类型与请求不一致")
    gis_by_parcel = _index_gis(state.gis_evidence)
    poi_by_parcel = _index_poi(state.poi_evidence)
    reports = [
        _score_parcel(
            parcel.parcel_id,
            state.request.project_type,
            gis_by_parcel.get(parcel.parcel_id),
            poi_by_parcel.get(parcel.parcel_id),
            config,
        )
        for parcel in state.request.candidate_parcels
    ]
    data = state.model_dump()
    data["site_score_reports"] = reports
    return AgentState.model_validate(data)


def _index_gis(items: list[GISEvidence]) -> dict[str, GISEvidence]:
    indexed = {}
    for item in items:
        if item.parcel_id in indexed:
            raise SiteScoringError(f"候选地块存在重复 GIS 证据：{item.parcel_id}")
        indexed[item.parcel_id] = item
    return indexed


def _index_poi(items: list[POIEvidence]) -> dict[str, POIEvidence]:
    indexed = {}
    for item in items:
        if item.parcel_id in indexed:
            raise SiteScoringError(f"候选地块存在重复 POI 证据：{item.parcel_id}")
        indexed[item.parcel_id] = item
    return indexed


def _score_parcel(
    parcel_id: str,
    project_type,
    gis: GISEvidence | None,
    poi: POIEvidence | None,
    config: SiteScoringConfig,
) -> SiteScoreReport:
    if gis is None or gis.status is not EvidenceStatus.READY:
        status = "missing" if gis is None else gis.status.value
        raise SiteScoringError(
            f"场址评分缺少 READY GIS 证据：{parcel_id}, status={status}"
        )
    if poi is None or poi.status is not EvidenceStatus.READY:
        status = "missing" if poi is None else poi.status.value
        raise SiteScoringError(
            f"场址评分缺少 READY POI 证据：{parcel_id}, status={status}"
        )
    if poi.soft_score is None or poi.score_report is None:
        raise SiteScoringError(f"场址评分缺少版本化 POI 分数：{parcel_id}")
    if not gis.dataset_ids:
        raise SiteScoringError(f"场址评分 GIS 证据缺少数据集来源：{parcel_id}")

    metric_scores = [
        _score_gis_metric(gis, rule)
        for rule in config.gis_metric_rules
    ]
    gis_score = sum(item.weighted_score for item in metric_scores)
    total = gis_score * config.gis_weight + poi.soft_score * config.poi_weight
    return SiteScoreReport(
        parcel_id=parcel_id,
        project_type=project_type,
        scoring_version=config.version,
        poi_scoring_version=poi.score_report.scoring_version,
        gis_component=GISScoreComponent(
            dataset_ids=gis.dataset_ids,
            metric_scores=metric_scores,
            score=gis_score,
        ),
        poi_score=poi.soft_score,
        gis_weight=config.gis_weight,
        poi_weight=config.poi_weight,
        total_score=total,
    )


def _score_gis_metric(
    evidence: GISEvidence,
    rule: GISMetricScoringRule,
) -> GISMetricScore:
    raw_value = evidence.metrics.get(rule.metric_key)
    if raw_value is None:
        if rule.missing_policy is MissingMetricPolicy.BLOCK:
            raise SiteScoringError(f"GIS 评分缺少指标：{rule.metric_key}")
        normalized = 0.0
    else:
        if not isfinite(raw_value):
            raise SiteScoringError(f"GIS 评分指标不是有限数：{rule.metric_key}")
        span = rule.upper_bound - rule.lower_bound
        if rule.direction is ScoreDirection.HIGHER_IS_BETTER:
            ratio = (raw_value - rule.lower_bound) / span
        else:
            ratio = (rule.upper_bound - raw_value) / span
        normalized = min(100.0, max(0.0, ratio * 100.0))
    return GISMetricScore(
        metric_key=rule.metric_key,
        direction=rule.direction,
        raw_value=raw_value,
        normalized_score=normalized,
        metric_weight=rule.weight,
        weighted_score=normalized * rule.weight,
        missing_policy=rule.missing_policy,
    )
