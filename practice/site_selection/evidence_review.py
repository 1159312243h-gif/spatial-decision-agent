from __future__ import annotations

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
    review_version: str = "evidence-review-v1",
) -> AgentState:
    """Audit lineage and completeness without generating a policy conclusion."""

    if state.status is not AnalysisStatus.COMPLETED:
        raise EvidenceReviewBlockedError("证据审查要求工作流结果已完成")
    if state.comparison_report is None:
        raise EvidenceReviewBlockedError("证据审查要求候选地块对比已完成")

    issues: list[EvidenceReviewIssue] = []
    for result in state.results:
        parcel_id = result.parcel_id
        gis = result.gis_evidence
        if (
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
        if (
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
        else:
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
