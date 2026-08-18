from __future__ import annotations

from collections.abc import Iterable

from .evidence import (
    AgentState,
    AnalysisResult,
    AnalysisStatus,
    CandidateComparisonItem,
    CandidateComparisonReport,
)
from .rules import RuleOutcome


class CandidateComparisonBlockedError(RuntimeError):
    """Raised when completed parcel results cannot be compared safely."""


_OUTCOME_SEVERITY = {
    RuleOutcome.NOTICE: 0,
    RuleOutcome.REVIEW_REQUIRED: 1,
    RuleOutcome.RESTRICTED: 2,
    RuleOutcome.PROHIBITED: 3,
}


def compare_candidate_results(state: AgentState) -> AgentState:
    """Build a stable soft-score ranking without making a policy decision."""

    if state.status is not AnalysisStatus.COMPLETED:
        raise CandidateComparisonBlockedError("候选地块对比要求结果组装已完成")

    results_by_parcel = _index_results(state.results)
    request_ids = {
        parcel.parcel_id for parcel in state.request.candidate_parcels
    }
    result_ids = set(results_by_parcel)
    if result_ids != request_ids:
        missing = sorted(request_ids - result_ids)
        extra = sorted(result_ids - request_ids)
        raise CandidateComparisonBlockedError(
            "候选地块结果与请求不一致："
            f"missing={missing}, extra={extra}"
        )

    versions = set()
    scored_results: list[AnalysisResult] = []
    for parcel_id in sorted(request_ids):
        result = results_by_parcel[parcel_id]
        if result.overall_soft_score is None:
            raise CandidateComparisonBlockedError(
                f"候选地块缺少 POI 软评分：{parcel_id}"
            )
        report = result.poi_evidence.score_report
        if report is None:
            raise CandidateComparisonBlockedError(
                f"候选地块缺少 POI 评分报告：{parcel_id}"
            )
        if report.project_type is not state.request.project_type:
            raise CandidateComparisonBlockedError(
                f"候选地块评分报告项目类型不一致：{parcel_id}"
            )
        versions.add(report.scoring_version)
        scored_results.append(result)

    if len(versions) != 1:
        raise CandidateComparisonBlockedError(
            f"候选地块不能混用评分版本：{sorted(versions)}"
        )

    ordered = sorted(
        scored_results,
        key=lambda result: (-_required_score(result), result.parcel_id),
    )
    comparison = CandidateComparisonReport(
        request_id=state.request.request_id,
        project_type=state.request.project_type,
        scoring_version=next(iter(versions)),
        candidates=_build_ranked_items(ordered),
        notes=[
            "排名仅依据同一版本的 POI 软评分，不代表合规结论或推荐决定",
            "政策规则命中仅随候选地块展示，不参与软评分名次计算",
        ],
    )

    state_data = state.model_dump()
    state_data["comparison_report"] = comparison.model_dump()
    return AgentState.model_validate(state_data)


def _index_results(
    results: Iterable[AnalysisResult],
) -> dict[str, AnalysisResult]:
    indexed: dict[str, AnalysisResult] = {}
    for result in results:
        if result.parcel_id in indexed:
            raise CandidateComparisonBlockedError(
                f"候选地块存在重复分析结果：{result.parcel_id}"
            )
        indexed[result.parcel_id] = result
    return indexed


def _required_score(result: AnalysisResult) -> float:
    score = result.overall_soft_score
    if score is None:
        raise AssertionError("soft score presence was checked above")
    return score


def _build_ranked_items(
    ordered: list[AnalysisResult],
) -> list[CandidateComparisonItem]:
    items: list[CandidateComparisonItem] = []
    for index, result in enumerate(ordered):
        score = _required_score(result)
        if index == 0:
            rank = 1
        else:
            previous_score = _required_score(ordered[index - 1])
            rank = (
                items[-1].soft_rank
                if score == previous_score
                else index + 1
            )

        is_tied = any(
            other.parcel_id != result.parcel_id
            and score == _required_score(other)
            for other in ordered
        )
        outcomes = sorted(
            {finding.outcome for finding in result.policy_evidence.rule_findings},
            key=_OUTCOME_SEVERITY.__getitem__,
            reverse=True,
        )
        items.append(
            CandidateComparisonItem(
                parcel_id=result.parcel_id,
                soft_rank=rank,
                soft_score=score,
                is_tied=is_tied,
                policy_outcomes=outcomes,
            )
        )
    return items
