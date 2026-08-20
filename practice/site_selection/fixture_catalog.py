from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain import CandidateParcel, NonEmptyString, ProjectType


class FixtureCandidateScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parcel_id: NonEmptyString
    name: NonEmptyString
    scenario_profile: NonEmptyString
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    area_hectares: float = Field(gt=0)
    geometry_dataset_id: NonEmptyString

    def to_candidate(self) -> CandidateParcel:
        return CandidateParcel.model_validate(
            self.model_dump(exclude={"scenario_profile"})
        )


class FixtureCandidateCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_fixture: bool
    version: NonEmptyString
    updated_at: datetime
    quality_notice: NonEmptyString
    project_candidates: dict[ProjectType, list[FixtureCandidateScenario]]

    @field_validator("updated_at")
    @classmethod
    def updated_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Fixture 候选目录更新时间必须包含时区")
        return value

    @model_validator(mode="after")
    def catalog_is_complete(self) -> FixtureCandidateCatalog:
        if not self.is_fixture:
            raise ValueError("Fixture 候选目录必须显式标记 is_fixture")
        if set(self.project_candidates) != set(ProjectType):
            raise ValueError("Fixture 候选目录必须覆盖全部项目类型")
        all_ids = []
        for project_type, candidates in self.project_candidates.items():
            if len(candidates) < 5:
                raise ValueError(f"{project_type.value} 至少需要 5 个候选地块")
            all_ids.extend(candidate.parcel_id for candidate in candidates)
            profiles = [candidate.scenario_profile for candidate in candidates]
            if len(profiles) != len(set(profiles)):
                raise ValueError(f"{project_type.value} 候选画像不能重复")
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("Fixture 候选地块编号不能重复")
        return self

    def payload_for(self, project_type: ProjectType) -> dict:
        return {
            "project_type": project_type.value,
            "candidate_parcels": [
                candidate.to_candidate().model_dump(mode="json", exclude_none=True)
                for candidate in self.project_candidates[project_type]
            ],
        }


def load_fixture_candidate_catalog(path: str | Path) -> FixtureCandidateCatalog:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return FixtureCandidateCatalog.model_validate(payload)
