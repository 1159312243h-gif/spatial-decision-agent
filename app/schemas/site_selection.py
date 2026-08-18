from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from practice.site_selection import (
    AnalysisResult,
    AnalysisStatus,
    CandidateComparisonReport,
    CandidateParcel,
    DatasetManifest,
    PreflightDecision,
    PreflightStatus,
    ProjectProfile,
    ProjectType,
    SiteSelectionDraft,
)


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
    candidate_parcels: list[CandidateParcelInput] = Field(min_length=1)

    @model_validator(mode="after")
    def candidate_ids_are_unique(self) -> SiteSelectionAnalysisCreate:
        parcel_ids = [parcel.parcel_id for parcel in self.candidate_parcels]
        if len(parcel_ids) != len(set(parcel_ids)):
            raise ValueError("候选地块编号不能重复")
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
    status: AnalysisStatus
    results: list[AnalysisResult] = Field(default_factory=list)
    comparison_report: CandidateComparisonReport | None = None
    errors: list[NonEmptyString] = Field(default_factory=list)


AnalysisErrorCode = Literal[
    "analysis_blocked",
    "analysis_internal_error",
    "runtime_unavailable",
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
