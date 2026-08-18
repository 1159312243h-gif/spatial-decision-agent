from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from practice.site_selection import (
    AgentState,
    CandidateParcel,
    ConstraintLayerType,
    ConstraintObservation,
    EvidenceStatus,
    GISEvidence,
    PolicyReference,
    ProjectRequest,
    ProjectType,
    RuleConfigurationError,
    RuleDefinition,
    RuleEvaluationBlockedError,
    RuleOutcome,
    SpatialConstraintRelation,
    evaluate_policy_rules,
    get_project_profile,
)


NOW = datetime(2026, 8, 18, 23, 45, tzinfo=timezone.utc)
CONSTRAINT_ID = "ecology-observation"


def observation(
    *,
    triggered: bool = True,
    constraint_id: str = CONSTRAINT_ID,
) -> ConstraintObservation:
    return ConstraintObservation(
        parcel_id="A01",
        constraint_id=constraint_id,
        layer_type=ConstraintLayerType.ECOLOGICAL_PROTECTION,
        dataset_id="ecology-2026-08",
        dataset_version="2026.08",
        relation=SpatialConstraintRelation.INTERSECTS,
        analysis_crs="EPSG:32651",
        intersecting_feature_count=1 if triggered else 0,
        nearest_distance_m=0 if triggered else 50,
        triggered=triggered,
    )


def state(
    *,
    status: EvidenceStatus = EvidenceStatus.READY,
    observations: list[ConstraintObservation] | None = None,
) -> AgentState:
    request = ProjectRequest(
        request_id="REQ-rule-engine",
        project_type=ProjectType.SHOPPING_MALL,
        candidate_parcels=[
            CandidateParcel(
                parcel_id="A01",
                longitude=121.47,
                latitude=31.23,
                geometry_dataset_id="parcel-2026-08",
            )
        ],
        requested_at=NOW,
    )
    return AgentState(
        request=request,
        profile=get_project_profile(ProjectType.SHOPPING_MALL),
        gis_evidence=[
            GISEvidence(
                parcel_id="A01",
                status=status,
                dataset_ids=["parcel-2026-08"],
                crs="EPSG:32651" if status is EvidenceStatus.READY else None,
                geometry_valid=True if status is EvidenceStatus.READY else None,
                constraint_observations=(
                    observations
                    if observations is not None
                    else [observation()]
                ),
            )
        ],
    )


def policy() -> PolicyReference:
    return PolicyReference(
        policy_id="POLICY-DEMO-001",
        title="测试用空间管理规则",
        issuing_authority="测试机构",
        document_number="TEST-2026-001",
        clause="第十条",
        version="2026.1",
        jurisdiction="测试行政区",
        source_uri="policy://demo/POLICY-DEMO-001",
    )


def rule(
    *,
    version: str = "1.0",
    project_types: list[ProjectType] | None = None,
    constraint_id: str = CONSTRAINT_ID,
    expected_triggered: bool = True,
    valid_from: date = date(2026, 1, 1),
    valid_to: date | None = None,
) -> RuleDefinition:
    return RuleDefinition(
        rule_id="RULE-ECOLOGY-001",
        name="测试生态空间规则",
        version=version,
        applicable_project_types=(
            project_types or [ProjectType.SHOPPING_MALL]
        ),
        constraint_id=constraint_id,
        expected_triggered=expected_triggered,
        outcome=RuleOutcome.REVIEW_REQUIRED,
        message="命中测试生态空间条件，需要人工复核",
        policy=policy(),
        valid_from=valid_from,
        valid_to=valid_to,
    )


def test_rule_validity_period_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="valid_to"):
        rule(
            valid_from=date(2026, 8, 1),
            valid_to=date(2026, 7, 31),
        )


def test_rule_project_types_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="不能重复"):
        rule(
            project_types=[
                ProjectType.SHOPPING_MALL,
                ProjectType.SHOPPING_MALL,
            ]
        )


def test_unknown_rule_outcome_is_rejected() -> None:
    data = rule().model_dump()
    data["outcome"] = "approved"

    with pytest.raises(ValidationError, match="outcome"):
        RuleDefinition.model_validate(data)


def test_triggered_observation_produces_auditable_finding() -> None:
    result = evaluate_policy_rules(state(), [rule()])

    evidence = result.policy_evidence[0]
    finding = evidence.rule_findings[0]
    assert evidence.status is EvidenceStatus.READY
    assert evidence.evaluated_rule_ids == ["RULE-ECOLOGY-001@1.0"]
    assert evidence.policy_ids == ["POLICY-DEMO-001"]
    assert finding.rule_version == "1.0"
    assert finding.policy_version == "2026.1"
    assert finding.policy_clause == "第十条"
    assert finding.observation_dataset_version == "2026.08"
    assert finding.outcome is RuleOutcome.REVIEW_REQUIRED


def test_unmatched_rule_is_evaluated_without_claiming_compliance() -> None:
    result = evaluate_policy_rules(
        state(observations=[observation(triggered=False)]),
        [rule()],
    )

    evidence = result.policy_evidence[0]
    assert evidence.status is EvidenceStatus.READY
    assert evidence.evaluated_rule_ids == ["RULE-ECOLOGY-001@1.0"]
    assert evidence.rule_findings == []
    assert evidence.findings == []
    assert "不等于整体合规" in evidence.notes[0]


def test_rule_can_explicitly_match_a_false_observation() -> None:
    result = evaluate_policy_rules(
        state(observations=[observation(triggered=False)]),
        [rule(expected_triggered=False)],
    )

    assert len(result.policy_evidence[0].rule_findings) == 1
    assert result.policy_evidence[0].rule_findings[0].observed_triggered is False


def test_non_applicable_rule_is_not_evaluated() -> None:
    applicable = rule()
    other = rule(
        version="logistics-only",
        project_types=[ProjectType.LOGISTICS_PARK],
    )

    result = evaluate_policy_rules(state(), [other, applicable])

    assert result.policy_evidence[0].evaluated_rule_ids == [
        "RULE-ECOLOGY-001@1.0"
    ]


def test_no_applicable_active_rule_blocks_evaluation() -> None:
    with pytest.raises(RuleEvaluationBlockedError, match="没有适用"):
        evaluate_policy_rules(
            state(),
            [rule(project_types=[ProjectType.LOGISTICS_PARK])],
        )


def test_missing_required_observation_blocks_evaluation() -> None:
    with pytest.raises(RuleEvaluationBlockedError, match="缺少规则所需"):
        evaluate_policy_rules(
            state(observations=[]),
            [rule()],
        )


@pytest.mark.parametrize(
    "status",
    [EvidenceStatus.MISSING, EvidenceStatus.INVALID],
)
def test_non_ready_gis_evidence_blocks_evaluation(
    status: EvidenceStatus,
) -> None:
    with pytest.raises(RuleEvaluationBlockedError, match=status.value):
        evaluate_policy_rules(state(status=status), [rule()])


def test_overlapping_active_versions_are_rejected() -> None:
    with pytest.raises(RuleConfigurationError, match="多个有效版本"):
        evaluate_policy_rules(
            state(),
            [rule(version="1.0"), rule(version="2.0")],
        )


def test_request_date_selects_one_rule_version() -> None:
    old = rule(
        version="1.0",
        valid_from=date(2025, 1, 1),
        valid_to=date(2026, 7, 31),
    )
    current = rule(
        version="2.0",
        valid_from=date(2026, 8, 1),
    )

    result = evaluate_policy_rules(state(), [old, current])

    assert result.policy_evidence[0].evaluated_rule_ids == [
        "RULE-ECOLOGY-001@2.0"
    ]


def test_rerun_replaces_policy_evidence_instead_of_duplicating() -> None:
    first = evaluate_policy_rules(state(), [rule()])
    second = evaluate_policy_rules(first, [rule()])

    assert len(second.policy_evidence) == 1
    assert len(second.policy_evidence[0].rule_findings) == 1


def test_rule_engine_does_not_mutate_input_state() -> None:
    initial = state()

    result = evaluate_policy_rules(initial, [rule()])

    assert initial.policy_evidence == []
    assert len(result.policy_evidence) == 1
