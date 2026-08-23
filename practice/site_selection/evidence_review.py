from __future__ import annotations

from .analysis_scope import MARKET_SCOPE_NOTICE, is_market_selection
from .evidence import AgentState, AnalysisStatus, EvidenceStatus
from .review_contracts import (
    EvidenceReviewIssue,
    EvidenceReviewReport,
    EvidenceReviewStatus,
    ReviewIssueSeverity,
)


class EvidenceReviewBlockedError(RuntimeError):
    """Raised when review is requested before result assembly is complete."""


def review_site_selection_evidence(
    state: AgentState,
    *,
    review_version: str = "evidence-review-v3",
) -> AgentState:
    """Audit lineage and completeness without generating a policy conclusion."""

    if state.status is not AnalysisStatus.COMPLETED:
        raise EvidenceReviewBlockedError("证据审查要求工作流结果已完成")
    if state.comparison_report is None:
        raise EvidenceReviewBlockedError("证据审查要求候选地块对比已完成")

    issues: list[EvidenceReviewIssue] = []
    market_selection = is_market_selection(state)
    for result in state.results:
        parcel_id = result.parcel_id
        gis = result.gis_evidence
        if market_selection and gis.status is EvidenceStatus.NOT_RUN:
            issues.append(
                EvidenceReviewIssue(
                    issue_code="land_compliance_unverified",
                    severity=ReviewIssueSeverity.WARNING,
                    parcel_id=parcel_id,
                    message=MARKET_SCOPE_NOTICE,
                )
            )
        elif (
            gis.status is not EvidenceStatus.READY
            or not gis.dataset_ids
            or not gis.crs
            or gis.geometry_valid is not True
        ):
            issues.append(
                EvidenceReviewIssue(
                    issue_code="gis_lineage_incomplete",
                    severity=ReviewIssueSeverity.BLOCKER,
                    parcel_id=parcel_id,
                    message="GIS 证据缺少 READY 状态、数据集、CRS 或几何校验",
                    evidence_refs=list(gis.dataset_ids),
                )
            )

        poi = result.poi_evidence
        if poi.status is not EvidenceStatus.READY or not poi.feature_sets:
            issues.append(
                EvidenceReviewIssue(
                    issue_code="poi_lineage_incomplete",
                    severity=ReviewIssueSeverity.BLOCKER,
                    parcel_id=parcel_id,
                    message="POI 证据缺少 READY FeatureSet 与来源元数据",
                )
            )
        else:
            source_refs = [
                (
                    f"{feature_set.source.provider.value}:"
                    f"{feature_set.source.dataset_id}:"
                    f"{feature_set.source.dataset_version or 'unversioned'}"
                )
                for feature_set in poi.feature_sets
            ]
            if any(
                feature_set.source.fallback_from is not None
                for feature_set in poi.feature_sets
            ):
                issues.append(
                    EvidenceReviewIssue(
                        issue_code="poi_fixture_fallback",
                        severity=ReviewIssueSeverity.WARNING,
                        parcel_id=parcel_id,
                        message="POI 在线数据源不可用，本次结果包含 Fixture 降级数据",
                        evidence_refs=source_refs,
                    )
                )
            truncated = [
                feature_set
                for feature_set in poi.feature_sets
                if feature_set.source.is_truncated
            ]
            if truncated:
                issues.append(
                    EvidenceReviewIssue(
                        issue_code="poi_result_truncated",
                        severity=ReviewIssueSeverity.WARNING,
                        parcel_id=parcel_id,
                        message=(
                            "POI 查询达到返回上限，数量与密度指标只能解释为下界"
                        ),
                        evidence_refs=[
                            (
                                f"{feature_set.query.group_key}:"
                                f"{feature_set.source.record_count}/"
                                f"{feature_set.source.available_record_count}"
                            )
                            for feature_set in truncated
                        ],
                    )
                )
            if any(
                feature_set.source.is_synthetic
                and feature_set.source.fallback_from is None
                for feature_set in poi.feature_sets
            ):
                issues.append(
                    EvidenceReviewIssue(
                        issue_code="poi_synthetic_source",
                        severity=ReviewIssueSeverity.WARNING,
                        parcel_id=parcel_id,
                        message="POI 来源为合成 Fixture，不代表真实城市设施现状",
                        evidence_refs=source_refs,
                    )
                )
            supplement_failures = [
                feature_set
                for feature_set in poi.feature_sets
                if feature_set.source.evidence_supplement_error is not None
            ]
            if supplement_failures:
                issues.append(
                    EvidenceReviewIssue(
                        issue_code="poi_candidate_supplement_failed",
                        severity=ReviewIssueSeverity.WARNING,
                        parcel_id=parcel_id,
                        message=(
                            "候选点局部在线补查失败，已保留同一发现快照的"
                            "可用切片；该评分组不能视为完整覆盖"
                        ),
                        evidence_refs=[
                            (
                                f"{feature_set.query.group_key}:"
                                f"{feature_set.source.evidence_supplement_error}"
                            )
                            for feature_set in supplement_failures
                        ],
                    )
                )

        if poi.soft_score is None or poi.score_report is None:
            issues.append(
                EvidenceReviewIssue(
                    issue_code="poi_score_lineage_incomplete",
                    severity=ReviewIssueSeverity.BLOCKER,
                    parcel_id=parcel_id,
                    message="POI 软评分缺少版本化评分报告",
                )
            )

        policy = result.policy_evidence
        if market_selection and policy.status is EvidenceStatus.NOT_RUN:
            pass
        elif (
            policy.status is not EvidenceStatus.READY
            or not policy.policy_ids
            or not policy.evaluated_rule_ids
        ):
            issues.append(
                EvidenceReviewIssue(
                    issue_code="policy_lineage_incomplete",
                    severity=ReviewIssueSeverity.BLOCKER,
                    parcel_id=parcel_id,
                    message="政策证据缺少政策 ID 或已评估规则版本",
                )
            )
        if policy.rule_findings:
            issues.append(
                EvidenceReviewIssue(
                    issue_code="policy_rule_match",
                    severity=ReviewIssueSeverity.WARNING,
                    parcel_id=parcel_id,
                    message="存在政策规则命中，必须保留人工复核",
                    evidence_refs=[
                        (
                            f"{finding.rule_id}@{finding.rule_version}:"
                            f"{finding.policy_id}:{finding.policy_clause}"
                        )
                        for finding in policy.rule_findings
                    ],
                )
            )
        elif not market_selection:
            issues.append(
                EvidenceReviewIssue(
                    issue_code="no_rule_match_is_not_compliance",
                    severity=ReviewIssueSeverity.INFO,
                    parcel_id=parcel_id,
                    message="未命中当前规则不等于整体合规",
                    evidence_refs=list(policy.evaluated_rule_ids),
                )
            )

        if result.site_score_report is not None:
            issues.append(
                EvidenceReviewIssue(
                    issue_code="gis_poi_soft_score",
                    severity=ReviewIssueSeverity.INFO,
                    parcel_id=parcel_id,
                    message="软评分由版本化 GIS+POI 配置生成，不代表合规结论",
                    evidence_refs=[result.site_score_report.scoring_version],
                )
            )

    for group_key, cohort in _poi_quality_cohorts(state).items():
        quality_states = {quality for _, quality in cohort}
        if len(quality_states) <= 1:
            continue
        issues.append(
            EvidenceReviewIssue(
                issue_code="poi_candidate_cohort_inconsistent",
                severity=ReviewIssueSeverity.WARNING,
                message=(
                    f"评分组 {group_key} 在候选之间混用了不同完整度的 POI "
                    "证据，数量差异不能直接解释为真实密度差异"
                ),
                evidence_refs=[
                    f"{parcel_id}:{quality}"
                    for parcel_id, quality in sorted(cohort)
                ],
            )
        )

    status = (
        EvidenceReviewStatus.BLOCKED
        if any(
            issue.severity is ReviewIssueSeverity.BLOCKER
            for issue in issues
        )
        else EvidenceReviewStatus.READY
    )
    report = EvidenceReviewReport(
        request_id=state.request.request_id,
        review_version=review_version,
        status=status,
        issues=issues,
        requires_human_review=any(
            issue.severity is ReviewIssueSeverity.WARNING
            for issue in issues
        ),
    )
    data = state.model_dump()
    data["evidence_review_report"] = report
    return AgentState.model_validate(data)


def _poi_quality_cohorts(state: AgentState) -> dict[str, list[tuple[str, str]]]:
    cohorts: dict[str, list[tuple[str, str]]] = {}
    for result in state.results:
        for feature_set in result.poi_evidence.feature_sets:
            source = feature_set.source
            if source.evidence_supplement_error is not None:
                quality = "supplement_failed"
            elif source.is_synthetic or source.fallback_from is not None:
                quality = "synthetic_fallback"
            elif source.is_truncated:
                quality = "real_truncated"
            else:
                quality = "real_complete"
            cohorts.setdefault(feature_set.query.group_key, []).append(
                (result.parcel_id, quality)
            )
    return cohorts
