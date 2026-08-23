from __future__ import annotations

from .domain import AnalysisScope
from .evidence import AgentState, EvidenceStatus, GISEvidence, PolicyEvidence


MARKET_SCOPE_NOTICE = (
    "当前运行仅进行商业选址分析；未取得可核验用地数据，"
    "用地、规划和政策合规状态均为待核验。"
)


def is_market_selection(state: AgentState) -> bool:
    return state.request.analysis_scope is AnalysisScope.MARKET_SELECTION


def mark_market_spatial_unverified(state: AgentState) -> AgentState:
    """Represent an intentional compliance skip without inventing geometry."""

    data = state.model_dump()
    data["gis_evidence"] = [
        GISEvidence(
            parcel_id=parcel.parcel_id,
            status=EvidenceStatus.NOT_RUN,
            notes=[MARKET_SCOPE_NOTICE],
        )
        for parcel in state.request.candidate_parcels
    ]
    return AgentState.model_validate(data)


def mark_market_policy_unverified(state: AgentState) -> AgentState:
    """Keep policy evidence explicit and non-ready for a market-only run."""

    data = state.model_dump()
    data["policy_evidence"] = [
        PolicyEvidence(
            parcel_id=parcel.parcel_id,
            status=EvidenceStatus.NOT_RUN,
            notes=[MARKET_SCOPE_NOTICE],
        )
        for parcel in state.request.candidate_parcels
    ]
    return AgentState.model_validate(data)
