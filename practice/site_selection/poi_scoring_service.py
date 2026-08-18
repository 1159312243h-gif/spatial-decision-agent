from __future__ import annotations

from .evidence import AgentState, EvidenceStatus, POIEvidence
from .poi_scoring import POIScoringConfig, POIScoringError, score_poi_feature_sets


def score_poi_state(
    state: AgentState,
    config: POIScoringConfig,
) -> AgentState:
    """Score every candidate parcel and return a newly validated state."""

    if config.project_type is not state.request.project_type:
        raise POIScoringError("评分配置项目类型必须与项目请求一致")

    evidence_by_parcel = _index_poi_evidence(state.poi_evidence)
    updated_evidence = [
        _score_parcel(
            state,
            parcel.parcel_id,
            evidence_by_parcel.get(parcel.parcel_id),
            config,
        )
        for parcel in state.request.candidate_parcels
    ]

    state_data = state.model_dump()
    state_data["poi_evidence"] = updated_evidence
    return AgentState.model_validate(state_data)


def _index_poi_evidence(
    items: list[POIEvidence],
) -> dict[str, POIEvidence]:
    indexed: dict[str, POIEvidence] = {}
    for evidence in items:
        if evidence.parcel_id in indexed:
            raise POIScoringError(
                f"候选地块存在重复 POI 证据：{evidence.parcel_id}"
            )
        indexed[evidence.parcel_id] = evidence
    return indexed


def _score_parcel(
    state: AgentState,
    parcel_id: str,
    evidence: POIEvidence | None,
    config: POIScoringConfig,
) -> POIEvidence:
    if evidence is None or evidence.status is not EvidenceStatus.READY:
        status = "missing" if evidence is None else evidence.status.value
        raise POIScoringError(
            f"地块 POI 证据未就绪：{parcel_id}, status={status}"
        )

    report = score_poi_feature_sets(
        state.profile,
        config,
        evidence.feature_sets,
    )
    if report.parcel_id != parcel_id:
        raise POIScoringError(
            f"POI 评分报告地块不一致：expected={parcel_id}, "
            f"actual={report.parcel_id}"
        )

    evidence_data = evidence.model_dump()
    evidence_data["soft_score"] = report.total_score
    evidence_data["score_report"] = report.model_dump()
    return POIEvidence.model_validate(evidence_data)
