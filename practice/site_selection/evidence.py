from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .constraints import ConstraintObservation
from .domain import DatasetManifest, NonEmptyString, ProjectRequest, ProjectType
from .poi import POIFeatureSet, POIQuery
from .poi_scoring import POIScoreReport
from .profiles import ProjectProfile
from .rules import PolicyFinding


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
    policy_evidence: list[PolicyEvidence] = Field(default_factory=list)
    results: list[AnalysisResult] = Field(default_factory=list)
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
        return self
