from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from practice.site_selection import (
    AnalysisScope,
    AgentCollaborationReport,
    AgentHarnessReport,
    AgentExecutionPlan,
    AgentStepTrace,
    AnalysisResult,
    AnalysisStatus,
    CandidateComparisonReport,
    CandidateDiscoveryReport,
    CandidateSelection,
    CandidateParcel,
    DatasetManifest,
    EvidenceReviewReport,
    HumanReviewState,
    AgentState,
    POIFeatureSet,
    POIQuery,
    PreflightDecision,
    PreflightStatus,
    ProjectProfile,
    ProjectType,
    SiteSelectionDraft,
    RunStageTrace,
    SiteSelectionSupervisorRun,
    SupervisorAnalysisStatus,
    SupervisorConfirmationRequest,
    SupervisorStatus,
)
from practice.site_selection.storage import (
    RunEvent,
    RunState,
    RunStatus,
    SupervisorSessionEvent,
)
from app.services.site_selection_explanation import SiteSelectionEvidenceExplanation


NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class CandidateParcelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parcel_id: NonEmptyString
    name: NonEmptyString | None = None
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    area_hectares: float | None = Field(default=None, gt=0)
    geometry_dataset_id: NonEmptyString | None = None

    def to_domain(self) -> CandidateParcel:
        return CandidateParcel.model_validate(self.model_dump())


class SiteSelectionAnalysisCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_type: ProjectType
    analysis_scope: AnalysisScope = AnalysisScope.FULL_COMPLIANCE
    candidate_parcels: list[CandidateParcelInput] = Field(min_length=1)
    poi_evidence_snapshot_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9._-]+$",
    )

    @model_validator(mode="after")
    def candidate_ids_are_unique(self) -> SiteSelectionAnalysisCreate:
        parcel_ids = [parcel.parcel_id for parcel in self.candidate_parcels]
        if len(parcel_ids) != len(set(parcel_ids)):
            raise ValueError("候选地块编号不能重复")
        if (
            self.analysis_scope is AnalysisScope.MARKET_SELECTION
            and self.project_type
            not in {ProjectType.COFFEE_SHOP, ProjectType.CONVENIENCE_STORE}
        ):
            raise ValueError("市场选址分析当前只支持咖啡店和便利店")
        return self


class SiteSelectionPreflightRequest(BaseModel):
    """Potentially incomplete request accepted before strict analysis input."""

    model_config = ConfigDict(extra="forbid")

    project_type: NonEmptyString | None = None
    candidate_parcels: list[CandidateParcelInput] = Field(default_factory=list)
    datasets: list[DatasetManifest] = Field(default_factory=list)

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> SiteSelectionPreflightRequest:
        parcel_ids = [parcel.parcel_id for parcel in self.candidate_parcels]
        if len(parcel_ids) != len(set(parcel_ids)):
            raise ValueError("候选地块编号不能重复")
        dataset_ids = [dataset.dataset_id for dataset in self.datasets]
        if len(dataset_ids) != len(set(dataset_ids)):
            raise ValueError("数据集编号不能重复")
        return self

    def to_draft(self) -> SiteSelectionDraft:
        return SiteSelectionDraft(
            project_type=self.project_type,
            candidate_parcels=[
                parcel.to_domain() for parcel in self.candidate_parcels
            ],
            datasets=[dataset.model_copy(deep=True) for dataset in self.datasets],
        )


class SiteSelectionPreflightResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PreflightStatus
    project_type: ProjectType | None = None
    profile: ProjectProfile | None = None
    missing_fields: list[NonEmptyString] = Field(default_factory=list)
    unsupported_value: NonEmptyString | None = None

    @classmethod
    def from_decision(
        cls,
        decision: PreflightDecision,
    ) -> SiteSelectionPreflightResponse:
        return cls.model_validate(decision.model_dump())


class SiteSelectionAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: NonEmptyString
    requested_at: datetime
    project_type: ProjectType
    analysis_scope: AnalysisScope
    status: AnalysisStatus
    results: list[AnalysisResult] = Field(default_factory=list)
    comparison_report: CandidateComparisonReport | None = None
    evidence_review_report: EvidenceReviewReport | None = None
    execution_plan: AgentExecutionPlan | None = None
    agent_trace: list[AgentStepTrace] = Field(default_factory=list)
    collaboration_report: AgentCollaborationReport | None = None
    agent_harness_report: AgentHarnessReport | None = None
    errors: list[NonEmptyString] = Field(default_factory=list)

    @classmethod
    def from_state(cls, state: AgentState) -> SiteSelectionAnalysisResponse:
        return cls(
            request_id=state.request.request_id,
            requested_at=state.request.requested_at,
            project_type=state.request.project_type,
            analysis_scope=state.request.analysis_scope,
            status=state.status,
            results=state.results,
            comparison_report=state.comparison_report,
            evidence_review_report=state.evidence_review_report,
            execution_plan=state.execution_plan,
            agent_trace=state.agent_trace,
            collaboration_report=state.collaboration_report,
            agent_harness_report=state.agent_harness_report,
            errors=state.errors,
        )


class SiteSelectionRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: NonEmptyString
    status: RunStatus
    updated_at: datetime
    error: NonEmptyString | None = None
    request_id: NonEmptyString | None = None
    analysis: SiteSelectionAnalysisResponse | None = None
    report_url: NonEmptyString | None = None
    report_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    explanation: SiteSelectionEvidenceExplanation | None = None
    human_review: HumanReviewState | None = None
    trace: list[RunStageTrace] = Field(default_factory=list)
    poi_evidence_snapshot_id: NonEmptyString | None = None
    poi_evidence_snapshot_reused: bool = False

    @classmethod
    def from_state(cls, state: RunState) -> SiteSelectionRunResponse:
        raw_analysis = state.details.get("analysis")
        analysis = (
            SiteSelectionAnalysisResponse.from_state(
                AgentState.model_validate(raw_analysis)
            )
            if raw_analysis is not None
            else None
        )
        return cls(
            run_id=state.run_id,
            status=state.status,
            updated_at=state.updated_at,
            error=state.error,
            request_id=state.details.get("request_id"),
            analysis=analysis,
            report_url=state.details.get("report_url"),
            report_sha256=state.details.get("report_sha256"),
            explanation=state.details.get("explanation"),
            human_review=state.details.get("human_review"),
            trace=state.details.get("trace", []),
            poi_evidence_snapshot_id=state.details.get(
                "poi_evidence_snapshot_id"
            ),
            poi_evidence_snapshot_reused=bool(
                state.details.get("poi_evidence_snapshot_reused", False)
            ),
        )


class HumanReviewAcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: NonEmptyString | None = None


class SiteSelectionRunEventsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: NonEmptyString
    events: list[RunEvent] = Field(default_factory=list)


class SiteSelectionSupervisorConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_checkpoint_id: NonEmptyString
    selected_candidate_ids: list[NonEmptyString] = Field(min_length=1)
    reviewer_id: NonEmptyString
    note: NonEmptyString | None = None

    @model_validator(mode="after")
    def candidate_ids_are_unique(self) -> SiteSelectionSupervisorConfirmRequest:
        if len(self.selected_candidate_ids) != len(
            set(self.selected_candidate_ids)
        ):
            raise ValueError("人工确认的候选 ID 不能重复")
        return self

    def to_domain(self) -> CandidateSelection:
        return CandidateSelection(
            selected_candidate_ids=self.selected_candidate_ids,
            reviewer_id=self.reviewer_id,
            note=self.note,
        )


class SiteSelectionSupervisorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: NonEmptyString
    checkpoint_id: NonEmptyString
    session_ttl_seconds: int = Field(ge=0)
    status: SupervisorStatus
    discovery_report: CandidateDiscoveryReport | None = None
    confirmation_request: SupervisorConfirmationRequest | None = None
    confirmation: CandidateSelection | None = None
    analysis_run_id: NonEmptyString | None = None
    analysis_run_status: SupervisorAnalysisStatus | None = None
    analysis_error_type: NonEmptyString | None = None
    analysis: SiteSelectionAnalysisResponse | None = None
    execution_plan: AgentExecutionPlan
    supervisor_trace: list[AgentStepTrace] = Field(default_factory=list)

    @classmethod
    def from_run(
        cls,
        run: SiteSelectionSupervisorRun,
        *,
        session_ttl_seconds: int,
    ) -> SiteSelectionSupervisorResponse:
        return cls(
            session_id=run.session_id,
            checkpoint_id=run.checkpoint_id,
            session_ttl_seconds=max(0, session_ttl_seconds),
            status=run.status,
            discovery_report=run.discovery_report,
            confirmation_request=run.confirmation_request,
            confirmation=run.confirmation,
            analysis_run_id=run.analysis_run_id,
            analysis_run_status=run.analysis_run_status,
            analysis_error_type=run.analysis_error_type,
            analysis=(
                SiteSelectionAnalysisResponse.from_state(run.analysis_state)
                if run.analysis_state is not None
                else None
            ),
            execution_plan=run.execution_plan,
            supervisor_trace=run.supervisor_trace,
        )


class SiteSelectionSupervisorEventsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: NonEmptyString
    events: list[SupervisorSessionEvent] = Field(default_factory=list)


class SiteSelectionPOIPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_type: ProjectType
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    categories: list[NonEmptyString] = Field(min_length=1)
    radius_m: int = Field(ge=100, le=50_000)
    limit: int = Field(default=100, ge=1, le=1_000)
    refresh: bool = False

    @model_validator(mode="after")
    def categories_are_unique(self) -> SiteSelectionPOIPreviewRequest:
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("POI 类别不能重复")
        return self

    def to_query(self) -> POIQuery:
        payload = self.model_dump(
            mode="json",
            exclude={"project_type", "refresh"},
        )
        payload["categories"] = sorted(payload["categories"])
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        query_id = sha256(canonical.encode("utf-8")).hexdigest()[:24]
        return POIQuery(
            query_id=f"preview-{query_id}",
            parcel_id="poi-preview",
            group_key="poi-preview",
            longitude=self.longitude,
            latitude=self.latitude,
            categories=self.categories,
            radius_m=self.radius_m,
            limit=self.limit,
        )


class SiteSelectionPOIPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cached: bool
    feature_set: POIFeatureSet


AnalysisErrorCode = Literal[
    "analysis_blocked",
    "analysis_internal_error",
    "idempotency_conflict",
    "runtime_unavailable",
    "supervisor_confirmation_blocked",
    "supervisor_conflict",
    "supervisor_internal_error",
    "supervisor_unavailable",
]


class SiteSelectionAnalysisErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: AnalysisErrorCode
    message: NonEmptyString
    request_id: NonEmptyString | None = None
    errors: list[NonEmptyString] = Field(default_factory=list)


class SiteSelectionAnalysisErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: SiteSelectionAnalysisErrorDetail
