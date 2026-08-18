from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from practice.site_selection import (
    AgentState,
    AnalysisResult,
    AnalysisStatus,
    CandidateComparisonBlockedError,
    CandidateComparisonItem,
    CandidateComparisonReport,
    CandidateParcel,
    EvidenceStatus,
    GISEvidence,
    MissingMetricPolicy,
    POIEvidence,
    POIGroupScore,
    POIMetric,
    POIMetricScore,
    POIScoreReport,
    PolicyEvidence,
    PolicyFinding,
    ProjectIntakeSkill,
    ProjectRequest,
    ProjectType,
    RuleOutcome,
    ScoreDirection,
    compare_candidate_results,
)


NOW = datetime(2026, 8, 18, 23, 59, tzinfo=timezone.utc)
PARCEL_IDS = ("A01", "A02", "A03")


def request() -> ProjectRequest:
    return ProjectRequest(
        request_id="REQ-comparison",
        project_type=ProjectType.SHOPPING_MALL,
        candidate_parcels=[
            CandidateParcel(
                parcel_id=parcel_id,
                longitude=121.47 + index * 0.01,
                latitude=31.23,
            )
            for index, parcel_id in enumerate(PARCEL_IDS)
        ],
        requested_at=NOW,
    )


def score_report(
    parcel_id: str,
    score: float,
    *,
    version: str = "demo-compare-1.0",
) -> POIScoreReport:
    metric_score = POIMetricScore(
        metric=POIMetric.COUNT,
        direction=ScoreDirection.HIGHER_IS_BETTER,
        raw_value=score,
        normalized_score=score,
        metric_weight=1,
        weighted_score=score,
        missing_policy=MissingMetricPolicy.BLOCK,
    )
    group_score = POIGroupScore(
        group_key="comparison_demo",
        query_id=f"query-{parcel_id}",
        source_dataset_id="poi-comparison-demo",
        metric_scores=[metric_score],
        group_score=score,
        profile_weight=1,
        weighted_score=score,
    )
    return POIScoreReport(
        parcel_id=parcel_id,
        project_type=ProjectType.SHOPPING_MALL,
        scoring_version=version,
        group_scores=[group_score],
        total_score=score,
    )


def policy_finding(
    parcel_id: str,
    outcome: RuleOutcome,
    index: int,
) -> PolicyFinding:
    return PolicyFinding(
        parcel_id=parcel_id,
        rule_id=f"RULE-{parcel_id}-{index}",
        rule_version="1.0",
        constraint_id=f"constraint-{index}",
        observed_triggered=True,
        expected_triggered=True,
        outcome=outcome,
        message="合成测试政策命中",
        policy_id=f"POLICY-{parcel_id}-{index}",
        policy_title="合成测试政策",
        policy_version="2026.1",
        policy_clause="第一条",
        issuing_authority="测试机构",
        jurisdiction="测试行政区",
        source_uri=f"policy://comparison/{parcel_id}/{index}",
        observation_dataset_id="constraint-demo",
        observation_dataset_version="2026.08",
        observation_analysis_crs="EPSG:32651",
    )


def analysis_result(
    parcel_id: str,
    score: float | None,
    *,
    version: str = "demo-compare-1.0",
    include_report: bool = True,
    outcomes: tuple[RuleOutcome, ...] = (),
) -> AnalysisResult:
    report = (
        score_report(parcel_id, score, version=version)
        if score is not None and include_report
        else None
    )
    findings = [
        policy_finding(parcel_id, outcome, index)
        for index, outcome in enumerate(outcomes, start=1)
    ]
    return AnalysisResult(
        request_id="REQ-comparison",
        parcel_id=parcel_id,
        project_type=ProjectType.SHOPPING_MALL,
        gis_evidence=GISEvidence(
            parcel_id=parcel_id,
            status=EvidenceStatus.READY,
        ),
        poi_evidence=POIEvidence(
            parcel_id=parcel_id,
            status=EvidenceStatus.READY,
            soft_score=score,
            score_report=report,
        ),
        policy_evidence=PolicyEvidence(
            parcel_id=parcel_id,
            status=EvidenceStatus.READY,
            policy_ids=[finding.policy_id for finding in findings],
            evaluated_rule_ids=[
                f"{finding.rule_id}@{finding.rule_version}"
                for finding in findings
            ],
            rule_findings=findings,
        ),
        overall_soft_score=score,
    )


def completed_state(results: list[AnalysisResult]) -> AgentState:
    state = ProjectIntakeSkill().run(request())
    data = state.model_dump()
    data["results"] = [result.model_dump() for result in results]
    data["status"] = AnalysisStatus.COMPLETED
    return AgentState.model_validate(data)


def complete_results() -> list[AnalysisResult]:
    return [
        analysis_result("A01", 80),
        analysis_result("A02", 90),
        analysis_result("A03", 70),
    ]


def test_candidates_are_ranked_by_soft_score_descending() -> None:
    compared = compare_candidate_results(completed_state(complete_results()))

    report = compared.comparison_report
    assert report is not None
    assert report.scoring_version == "demo-compare-1.0"
    assert report.ranking_basis == "poi_soft_score_desc"
    assert [item.parcel_id for item in report.candidates] == [
        "A02",
        "A01",
        "A03",
    ]
    assert [item.soft_rank for item in report.candidates] == [1, 2, 3]


def test_ties_use_competition_ranking_and_stable_parcel_order() -> None:
    results = [
        analysis_result("A03", 70),
        analysis_result("A02", 80),
        analysis_result("A01", 80),
    ]

    report = compare_candidate_results(completed_state(results)).comparison_report

    assert report is not None
    assert [item.parcel_id for item in report.candidates] == [
        "A01",
        "A02",
        "A03",
    ]
    assert [item.soft_rank for item in report.candidates] == [1, 1, 3]
    assert [item.is_tied for item in report.candidates] == [True, True, False]


def test_policy_outcomes_are_displayed_but_do_not_change_soft_rank() -> None:
    results = [
        analysis_result(
            "A01",
            95,
            outcomes=(RuleOutcome.PROHIBITED, RuleOutcome.REVIEW_REQUIRED),
        ),
        analysis_result("A02", 80),
        analysis_result("A03", 70),
    ]

    report = compare_candidate_results(completed_state(results)).comparison_report

    assert report is not None
    first = report.candidates[0]
    assert first.parcel_id == "A01"
    assert first.soft_rank == 1
    assert first.policy_outcomes == [
        RuleOutcome.PROHIBITED,
        RuleOutcome.REVIEW_REQUIRED,
    ]
    assert any("不代表合规结论" in note for note in report.notes)


def test_comparison_does_not_mutate_input_state() -> None:
    state = completed_state(complete_results())
    before = state.model_dump()

    compared = compare_candidate_results(state)

    assert state.model_dump() == before
    assert state.comparison_report is None
    assert compared is not state


def test_missing_soft_score_blocks_comparison() -> None:
    results = complete_results()
    results[0] = analysis_result("A01", None)

    with pytest.raises(CandidateComparisonBlockedError, match="缺少 POI 软评分"):
        compare_candidate_results(completed_state(results))


def test_missing_score_report_blocks_comparison() -> None:
    results = complete_results()
    results[0] = analysis_result("A01", 80, include_report=False)

    with pytest.raises(CandidateComparisonBlockedError, match="缺少 POI 评分报告"):
        compare_candidate_results(completed_state(results))


def test_mixed_scoring_versions_block_comparison() -> None:
    results = complete_results()
    results[0] = analysis_result("A01", 80, version="demo-compare-2.0")

    with pytest.raises(CandidateComparisonBlockedError, match="混用评分版本"):
        compare_candidate_results(completed_state(results))


def test_duplicate_parcel_result_blocks_comparison() -> None:
    results = [*complete_results(), analysis_result("A01", 60)]

    with pytest.raises(CandidateComparisonBlockedError, match="重复分析结果"):
        compare_candidate_results(completed_state(results))


def test_missing_parcel_result_blocks_comparison() -> None:
    with pytest.raises(CandidateComparisonBlockedError, match="missing=.*A03"):
        compare_candidate_results(completed_state(complete_results()[:2]))


def test_report_contract_rejects_duplicate_parcels() -> None:
    item = CandidateComparisonItem(
        parcel_id="A01",
        soft_rank=1,
        soft_score=80,
        is_tied=True,
    )

    with pytest.raises(ValidationError, match="重复地块"):
        CandidateComparisonReport(
            request_id="REQ-comparison",
            project_type=ProjectType.SHOPPING_MALL,
            scoring_version="demo-compare-1.0",
            candidates=[item, item.model_copy(deep=True)],
        )


def test_report_contract_rejects_inconsistent_rank() -> None:
    with pytest.raises(ValidationError, match="名次不一致"):
        CandidateComparisonReport(
            request_id="REQ-comparison",
            project_type=ProjectType.SHOPPING_MALL,
            scoring_version="demo-compare-1.0",
            candidates=[
                CandidateComparisonItem(
                    parcel_id="A01",
                    soft_rank=2,
                    soft_score=80,
                )
            ],
        )


def test_analysis_result_rejects_score_different_from_poi_evidence() -> None:
    data = analysis_result("A01", 80).model_dump()
    data["overall_soft_score"] = 70

    with pytest.raises(ValidationError, match="POI 证据软评分一致"):
        AnalysisResult.model_validate(data)
