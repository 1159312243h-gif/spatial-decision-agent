from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .constraints import ConstraintObservation
from .domain import DatasetManifest, NonEmptyString, ProjectRequest, ProjectType
from .poi import POIFeatureSet, POIQuery
from .poi_scoring import POIScoreReport
from .profiles import ProjectProfile
from .rules import PolicyFinding, RuleOutcome
from .site_scoring_contracts import SiteScoreReport
from .review_contracts import EvidenceReviewReport


class EvidenceStatus(StrEnum):
    READY = "ready"
    MISSING = "missing"
    INVALID = "invalid"
    NOT_RUN = "not_run"


class AnalysisStatus(StrEnum):
    INTAKE = "intake"
    DATA_PENDING = "data_pending"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


class GISEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parcel_id: NonEmptyString
    status: EvidenceStatus
    dataset_ids: list[NonEmptyString] = Field(default_factory=list)
    crs: NonEmptyString | None = None
    geometry_valid: bool | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    constraint_observations: list[ConstraintObservation] = Field(
        default_factory=list,
    )
    notes: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def observations_target_same_parcel(self) -> GISEvidence:
        if any(
            observation.parcel_id != self.parcel_id
            for observation in self.constraint_observations
        ):
            raise ValueError("空间约束观察必须属于同一候选地块")
        return self


class POIEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parcel_id: NonEmptyString
    status: EvidenceStatus
    feature_sets: list[POIFeatureSet] = Field(default_factory=list)
    soft_score: float | None = Field(default=None, ge=0, le=100)
    score_report: POIScoreReport | None = None
    notes: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def score_lineage_is_consistent(self) -> POIEvidence:
        if any(
            feature_set.query.parcel_id != self.parcel_id
            for feature_set in self.feature_sets
        ):
            raise ValueError("POI FeatureSet 必须属于同一候选地块")
        if self.score_report is None:
            return self
        if self.score_report.parcel_id != self.parcel_id:
            raise ValueError("POI 评分报告必须属于同一候选地块")
        if self.soft_score is None:
            raise ValueError("存在 POI 评分报告时 soft_score 不能为空")
        if abs(self.soft_score - self.score_report.total_score) > 1e-7:
            raise ValueError("POI soft_score 必须等于评分报告总分")
        return self


class PolicyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parcel_id: NonEmptyString
    status: EvidenceStatus
    policy_ids: list[NonEmptyString] = Field(default_factory=list)
    evaluated_rule_ids: list[NonEmptyString] = Field(default_factory=list)
    findings: list[NonEmptyString] = Field(default_factory=list)
    rule_findings: list[PolicyFinding] = Field(default_factory=list)
    notes: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def rule_lineage_is_consistent(self) -> PolicyEvidence:
        if len(self.policy_ids) != len(set(self.policy_ids)):
            raise ValueError("PolicyEvidence policy_ids 不能重复")
        if len(self.evaluated_rule_ids) != len(set(self.evaluated_rule_ids)):
            raise ValueError("PolicyEvidence evaluated_rule_ids 不能重复")
        if any(
            finding.parcel_id != self.parcel_id
            for finding in self.rule_findings
        ):
            raise ValueError("政策规则命中记录必须属于同一候选地块")
        if any(
            finding.policy_id not in self.policy_ids
            for finding in self.rule_findings
        ):
            raise ValueError("规则命中的 policy_id 必须出现在 policy_ids 中")
        finding_rule_ids = {
            f"{finding.rule_id}@{finding.rule_version}"
            for finding in self.rule_findings
        }
        if not finding_rule_ids.issubset(set(self.evaluated_rule_ids)):
            raise ValueError("规则命中必须来自已评估的规则版本")
        return self


class AnalysisResult(BaseModel):
    """One parcel-level result that keeps evidence and conclusion separate."""

    model_config = ConfigDict(extra="forbid")

    request_id: NonEmptyString
    parcel_id: NonEmptyString
    project_type: ProjectType
    gis_evidence: GISEvidence
    poi_evidence: POIEvidence
    policy_evidence: PolicyEvidence
    overall_soft_score: float | None = Field(default=None, ge=0, le=100)
    site_score_report: SiteScoreReport | None = None
    conclusion: NonEmptyString | None = None
    warnings: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def evidence_targets_same_parcel(self) -> AnalysisResult:
        parcel_ids = {
            self.parcel_id,
            self.gis_evidence.parcel_id,
            self.poi_evidence.parcel_id,
            self.policy_evidence.parcel_id,
        }
        if len(parcel_ids) != 1:
            raise ValueError("分析结果中的证据必须属于同一候选地块")
        evidence_score = (
            self.site_score_report.total_score
            if self.site_score_report is not None
            else self.poi_evidence.soft_score
        )
        score_error = (
            "分析结果软评分必须与场址评分报告一致"
            if self.site_score_report is not None
            else "分析结果软评分必须与 POI 证据软评分一致"
        )
        if (self.overall_soft_score is None) != (evidence_score is None):
            raise ValueError(score_error)
        if (
            self.overall_soft_score is not None
            and evidence_score is not None
            and abs(self.overall_soft_score - evidence_score) > 1e-7
        ):
            raise ValueError(score_error)
        if self.site_score_report is not None:
            if self.site_score_report.parcel_id != self.parcel_id:
                raise ValueError("场址评分报告必须属于同一候选地块")
            if self.site_score_report.project_type is not self.project_type:
                raise ValueError("场址评分报告项目类型必须与结果一致")
        return self


class CandidateComparisonItem(BaseModel):
    """One candidate's position in a POI soft-score-only comparison."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    parcel_id: NonEmptyString
    soft_rank: int = Field(ge=1)
    soft_score: float = Field(ge=0, le=100)
    is_tied: bool = False
    policy_outcomes: list[RuleOutcome] = Field(default_factory=list)

    @model_validator(mode="after")
    def policy_outcomes_are_unique(self) -> CandidateComparisonItem:
        if len(self.policy_outcomes) != len(set(self.policy_outcomes)):
            raise ValueError("候选地块对比中的政策结果等级不能重复")
        return self


class CandidateComparisonReport(BaseModel):
    """Auditable ranking based only on versioned POI soft scores."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    request_id: NonEmptyString
    project_type: ProjectType
    scoring_version: NonEmptyString
    ranking_basis: Literal[
        "poi_soft_score_desc",
        "gis_poi_soft_score_desc",
    ] = "poi_soft_score_desc"
    candidates: list[CandidateComparisonItem] = Field(min_length=1)
    notes: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def ranking_is_consistent(self) -> CandidateComparisonReport:
        parcel_ids = [item.parcel_id for item in self.candidates]
        if len(parcel_ids) != len(set(parcel_ids)):
            raise ValueError("候选地块对比结果不能包含重复地块")

        for index, item in enumerate(self.candidates):
            tied_count = sum(
                item.soft_score == other.soft_score
                for other in self.candidates
            )
            if item.is_tied != (tied_count > 1):
                raise ValueError("候选地块并列标记必须与软评分一致")

            expected_rank = 1
            if index > 0:
                previous = self.candidates[index - 1]
                if item.soft_score > previous.soft_score:
                    raise ValueError("候选地块必须按软评分降序排列")
                if item.soft_score == previous.soft_score:
                    expected_rank = previous.soft_rank
                    if item.parcel_id < previous.parcel_id:
                        raise ValueError("同分候选地块必须按 parcel_id 稳定排序")
                else:
                    expected_rank = index + 1
            if item.soft_rank != expected_rank:
                raise ValueError("候选地块软评分名次不一致")
        return self


class AgentState(BaseModel):
    """Business state for the future site-selection workflow.

    This is separate from practice.llm_api.agent_state.AgentState, which is
    the runtime state of the generic tool-calling demonstration graph.
    """

    model_config = ConfigDict(extra="forbid")

    request: ProjectRequest
    profile: ProjectProfile
    datasets: list[DatasetManifest] = Field(default_factory=list)
    poi_queries: list[POIQuery] = Field(default_factory=list)
    poi_feature_sets: list[POIFeatureSet] = Field(default_factory=list)
    gis_evidence: list[GISEvidence] = Field(default_factory=list)
    poi_evidence: list[POIEvidence] = Field(default_factory=list)
    site_score_reports: list[SiteScoreReport] = Field(default_factory=list)
    policy_evidence: list[PolicyEvidence] = Field(default_factory=list)
    results: list[AnalysisResult] = Field(default_factory=list)
    comparison_report: CandidateComparisonReport | None = None
    evidence_review_report: EvidenceReviewReport | None = None
    errors: list[NonEmptyString] = Field(default_factory=list)
    status: AnalysisStatus = AnalysisStatus.INTAKE

    @model_validator(mode="after")
    def references_match_request(self) -> AgentState:
        if self.request.project_type != self.profile.project_type:
            raise ValueError("项目请求类型必须与 ProjectProfile 类型一致")

        parcel_ids = {
            parcel.parcel_id for parcel in self.request.candidate_parcels
        }
        referenced_ids = {
            query.parcel_id for query in self.poi_queries
        }
        referenced_ids.update(item.parcel_id for item in self.gis_evidence)
        referenced_ids.update(item.parcel_id for item in self.poi_evidence)
        referenced_ids.update(item.parcel_id for item in self.site_score_reports)
        referenced_ids.update(item.parcel_id for item in self.policy_evidence)
        referenced_ids.update(item.parcel_id for item in self.results)

        unknown_ids = referenced_ids - parcel_ids
        if unknown_ids:
            joined = ", ".join(sorted(unknown_ids))
            raise ValueError(f"状态引用了请求中不存在的候选地块：{joined}")

        for result in self.results:
            if result.request_id != self.request.request_id:
                raise ValueError("分析结果 request_id 必须与项目请求一致")
            if result.project_type != self.request.project_type:
                raise ValueError("分析结果项目类型必须与项目请求一致")

        if self.comparison_report is not None:
            report = self.comparison_report
            if report.request_id != self.request.request_id:
                raise ValueError("候选地块对比报告 request_id 必须与请求一致")
            if report.project_type != self.request.project_type:
                raise ValueError("候选地块对比报告项目类型必须与请求一致")
            result_ids = {result.parcel_id for result in self.results}
            report_ids = {item.parcel_id for item in report.candidates}
            if not self.results or report_ids != result_ids or report_ids != parcel_ids:
                raise ValueError("候选地块对比报告必须完整覆盖分析结果和请求地块")
        if (
            self.evidence_review_report is not None
            and self.evidence_review_report.request_id != self.request.request_id
        ):
            raise ValueError("证据审查报告 request_id 必须与请求一致")
        return self
