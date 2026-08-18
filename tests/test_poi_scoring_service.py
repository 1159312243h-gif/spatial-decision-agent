from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from practice.site_selection import (
    AgentState,
    CandidateParcel,
    EvidenceStatus,
    MissingMetricPolicy,
    MockPOIGateway,
    POIGroupScoringConfig,
    POIMetric,
    POIMetricScoringRule,
    POIScoringConfig,
    POIScoringError,
    ProjectIntakeSkill,
    ProjectRequest,
    ProjectType,
    ScoreDirection,
    execute_poi_queries,
    get_project_profile,
    score_poi_state,
)


NOW = datetime(2026, 8, 18, 23, 59, tzinfo=timezone.utc)


def scoring_config(
    *,
    missing_policy: MissingMetricPolicy = MissingMetricPolicy.ZERO,
) -> POIScoringConfig:
    profile = get_project_profile(ProjectType.SHOPPING_MALL)
    groups = []
    for group in profile.poi_groups:
        metric_weight = 1 / len(group.metrics)
        groups.append(
            POIGroupScoringConfig(
                group_key=group.group_key,
                metric_rules=[
                    POIMetricScoringRule(
                        metric=metric,
                        direction=(
                            ScoreDirection.LOWER_IS_BETTER
                            if metric
                            in {
                                POIMetric.NEAREST_DISTANCE_M,
                                POIMetric.AVERAGE_DISTANCE_M,
                            }
                            else ScoreDirection.HIGHER_IS_BETTER
                        ),
                        lower_bound=0,
                        upper_bound=100,
                        weight=metric_weight,
                        missing_policy=missing_policy,
                    )
                    for metric in group.metrics
                ],
            )
        )
    return POIScoringConfig(
        project_type=ProjectType.SHOPPING_MALL,
        version="demo-state-1.0",
        groups=groups,
    )


def ready_state() -> AgentState:
    request = ProjectRequest(
        request_id="REQ-score-state",
        project_type=ProjectType.SHOPPING_MALL,
        candidate_parcels=[
            CandidateParcel(
                parcel_id="A01",
                longitude=121.47,
                latitude=31.23,
            )
        ],
        requested_at=NOW,
    )
    intake_state = ProjectIntakeSkill().run(request)
    return execute_poi_queries(
        intake_state,
        MockPOIGateway(clock=lambda: NOW),
    )


def replace_evidence(state: AgentState, evidence_items: list[object]) -> AgentState:
    data = state.model_dump()
    data["poi_evidence"] = [
        item.model_dump() if hasattr(item, "model_dump") else item
        for item in evidence_items
    ]
    return AgentState.model_validate(data)


def test_score_poi_state_writes_auditable_report_and_total() -> None:
    state = ready_state()

    scored = score_poi_state(state, scoring_config())

    evidence = scored.poi_evidence[0]
    assert evidence.score_report is not None
    assert evidence.score_report.scoring_version == "demo-state-1.0"
    assert evidence.soft_score == pytest.approx(evidence.score_report.total_score)
    assert 0 <= evidence.soft_score <= 100


def test_score_poi_state_does_not_mutate_input() -> None:
    state = ready_state()
    before = state.model_dump()

    scored = score_poi_state(state, scoring_config())

    assert state.model_dump() == before
    assert state.poi_evidence[0].soft_score is None
    assert scored is not state


def test_missing_poi_evidence_blocks_scoring() -> None:
    state = replace_evidence(ready_state(), [])

    with pytest.raises(POIScoringError, match="status=missing"):
        score_poi_state(state, scoring_config())


def test_non_ready_poi_evidence_blocks_scoring() -> None:
    state = ready_state()
    non_ready = state.poi_evidence[0].model_copy(
        update={"status": EvidenceStatus.MISSING}
    )
    state = replace_evidence(state, [non_ready])

    with pytest.raises(POIScoringError, match="status=missing"):
        score_poi_state(state, scoring_config())


def test_duplicate_poi_evidence_blocks_scoring() -> None:
    state = ready_state()
    evidence = state.poi_evidence[0]
    state = replace_evidence(state, [evidence, evidence.model_copy(deep=True)])

    with pytest.raises(POIScoringError, match="重复 POI 证据"):
        score_poi_state(state, scoring_config())


def test_report_and_soft_score_mismatch_is_rejected() -> None:
    scored = score_poi_state(ready_state(), scoring_config())
    data = scored.model_dump()
    data["poi_evidence"][0]["soft_score"] += 1

    with pytest.raises(ValidationError, match="soft_score"):
        AgentState.model_validate(data)


def test_block_policy_rejects_missing_distance_metric() -> None:
    with pytest.raises(POIScoringError, match="缺少指标"):
        score_poi_state(
            ready_state(),
            scoring_config(missing_policy=MissingMetricPolicy.BLOCK),
        )
