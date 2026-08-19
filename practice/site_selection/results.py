from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .evidence import (
    AgentState,
    AnalysisResult,
    AnalysisStatus,
    EvidenceStatus,
    GISEvidence,
    POIEvidence,
    PolicyEvidence,
)
from .site_scoring_contracts import SiteScoreReport


class ResultAssemblyBlockedError(RuntimeError):
    """Raised when parcel-level evidence is incomplete or inconsistent."""


def assemble_analysis_results(state: AgentState) -> AgentState:
    """Build parcel results while keeping hard evidence and soft scores separate."""

    gis_by_parcel = _index_by_parcel(state.gis_evidence, "GIS")
    poi_by_parcel = _index_by_parcel(state.poi_evidence, "POI")
    policy_by_parcel = _index_by_parcel(state.policy_evidence, "policy")
    site_score_by_parcel = _index_by_parcel(
        state.site_score_reports,
        "site score",
    )

    results = [
        _assemble_parcel_result(
            state,
            parcel.parcel_id,
            gis_by_parcel.get(parcel.parcel_id),
            poi_by_parcel.get(parcel.parcel_id),
            policy_by_parcel.get(parcel.parcel_id),
            site_score_by_parcel.get(parcel.parcel_id),
            require_site_score=bool(state.site_score_reports),
        )
        for parcel in state.request.candidate_parcels
    ]

    state_data = state.model_dump()
    state_data["results"] = results
    state_data["comparison_report"] = None
    state_data["status"] = AnalysisStatus.COMPLETED
    return AgentState.model_validate(state_data)


def _index_by_parcel(
    items: Iterable[Any],
    evidence_name: str,
) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for item in items:
        parcel_id = item.parcel_id
        if parcel_id in indexed:
            raise ResultAssemblyBlockedError(
                f"候选地块存在重复 {evidence_name} 证据：{parcel_id}"
            )
        indexed[parcel_id] = item
    return indexed


def _assemble_parcel_result(
    state: AgentState,
    parcel_id: str,
    gis_evidence: GISEvidence | None,
    poi_evidence: POIEvidence | None,
    policy_evidence: PolicyEvidence | None,
    site_score_report: SiteScoreReport | None,
    *,
    require_site_score: bool,
) -> AnalysisResult:
    evidence_items = {
        "GIS": gis_evidence,
        "POI": poi_evidence,
        "policy": policy_evidence,
    }
    for evidence_name, evidence in evidence_items.items():
        if evidence is None:
            raise ResultAssemblyBlockedError(
                f"候选地块缺少 {evidence_name} 证据：{parcel_id}"
            )
        if evidence.status is not EvidenceStatus.READY:
            raise ResultAssemblyBlockedError(
                f"候选地块 {evidence_name} 证据未就绪："
                f"{parcel_id}, status={evidence.status.value}"
            )

    if gis_evidence is None or poi_evidence is None or policy_evidence is None:
        raise AssertionError("evidence presence was checked above")
    if require_site_score and site_score_report is None:
        raise ResultAssemblyBlockedError(
            f"候选地块缺少 GIS+POI 场址评分：{parcel_id}"
        )

    warnings = list(policy_evidence.notes)
    if policy_evidence.rule_findings:
        warnings.append(
            "PolicyEvidence 中存在规则命中，需按结论等级处理并人工复核"
        )
    if poi_evidence.soft_score is None:
        warnings.append(
            "POI 指标已采集，但尚未配置归一化评分规则，未生成软评分"
        )

    return AnalysisResult(
        request_id=state.request.request_id,
        parcel_id=parcel_id,
        project_type=state.request.project_type,
        gis_evidence=gis_evidence,
        poi_evidence=poi_evidence,
        policy_evidence=policy_evidence,
        overall_soft_score=(
            site_score_report.total_score
            if site_score_report is not None
            else poi_evidence.soft_score
        ),
        site_score_report=site_score_report,
        conclusion=None,
        warnings=warnings,
    )
