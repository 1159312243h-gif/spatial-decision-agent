from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain import CandidateParcel, DatasetManifest, NonEmptyString, ProjectType
from .intake import ProfileRegistry, UnsupportedProjectTypeError
from .profiles import ProjectProfile


class PreflightStatus(StrEnum):
    READY = "ready"
    NEEDS_INPUT = "needs_input"
    UNSUPPORTED = "unsupported"


class SiteSelectionDraft(BaseModel):
    """Potentially incomplete input used before strict ProjectRequest creation."""

    model_config = ConfigDict(extra="forbid")

    project_type: NonEmptyString | None = None
    candidate_parcels: list[CandidateParcel] = Field(default_factory=list)
    datasets: list[DatasetManifest] = Field(default_factory=list)


class PreflightDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PreflightStatus
    project_type: ProjectType | None = None
    profile: ProjectProfile | None = None
    missing_fields: list[NonEmptyString] = Field(default_factory=list)
    unsupported_value: NonEmptyString | None = None

    @model_validator(mode="after")
    def status_payload_is_consistent(self) -> PreflightDecision:
        if len(self.missing_fields) != len(set(self.missing_fields)):
            raise ValueError("前置检查缺失字段不能重复")
        if self.status is PreflightStatus.READY:
            if self.project_type is None or self.profile is None:
                raise ValueError("ready 决策必须包含项目类型和 Profile")
            if self.missing_fields or self.unsupported_value is not None:
                raise ValueError("ready 决策不能包含缺失或不支持信息")
        elif self.status is PreflightStatus.NEEDS_INPUT:
            if not self.missing_fields:
                raise ValueError("needs_input 决策必须包含缺失字段")
            if self.unsupported_value is not None:
                raise ValueError("needs_input 决策不能包含不支持值")
        else:
            if self.unsupported_value is None:
                raise ValueError("unsupported 决策必须包含原始项目类型")
            if self.project_type is not None or self.profile is not None:
                raise ValueError("unsupported 决策不能包含已路由 Profile")
            if self.missing_fields:
                raise ValueError("unsupported 决策不能同时声明缺失字段")
        return self


def evaluate_site_selection_draft(
    draft: SiteSelectionDraft,
    registry: ProfileRegistry | None = None,
) -> PreflightDecision:
    """Route supported projects and stop incomplete input before analysis."""

    if draft.project_type is None:
        return PreflightDecision(
            status=PreflightStatus.NEEDS_INPUT,
            missing_fields=_collect_missing_fields(draft, include_project_type=True),
        )

    active_registry = registry or ProfileRegistry()
    try:
        profile = active_registry.get(draft.project_type)
    except UnsupportedProjectTypeError:
        return PreflightDecision(
            status=PreflightStatus.UNSUPPORTED,
            unsupported_value=draft.project_type,
        )

    missing_fields = _collect_missing_fields(draft, include_project_type=False)
    if missing_fields:
        return PreflightDecision(
            status=PreflightStatus.NEEDS_INPUT,
            project_type=profile.project_type,
            profile=profile,
            missing_fields=missing_fields,
        )
    return PreflightDecision(
        status=PreflightStatus.READY,
        project_type=profile.project_type,
        profile=profile,
    )


def _collect_missing_fields(
    draft: SiteSelectionDraft,
    *,
    include_project_type: bool,
) -> list[str]:
    missing = []
    if include_project_type:
        missing.append("project_type")
    if not draft.candidate_parcels:
        missing.append("candidate_parcels")
    for index, parcel in enumerate(draft.candidate_parcels):
        prefix = f"candidate_parcels[{index}]"
        if parcel.area_hectares is None:
            missing.append(f"{prefix}.area_hectares")
        if parcel.geometry_dataset_id is None:
            missing.append(f"{prefix}.geometry_dataset_id")

    if not draft.datasets:
        missing.append("datasets")
    else:
        dataset_ids = {dataset.dataset_id for dataset in draft.datasets}
        for parcel in draft.candidate_parcels:
            dataset_id = parcel.geometry_dataset_id
            if dataset_id is not None and dataset_id not in dataset_ids:
                missing.append(f"datasets[{dataset_id}]")
    return list(dict.fromkeys(missing))
