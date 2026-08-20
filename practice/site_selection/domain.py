from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class ProjectType(StrEnum):
    SHOPPING_MALL = "shopping_mall"
    LOGISTICS_PARK = "logistics_park"
    COFFEE_SHOP = "coffee_shop"
    CONVENIENCE_STORE = "convenience_store"


class DatasetSource(StrEnum):
    API = "api"
    POSTGIS = "postgis"
    FILE = "file"


class CandidateParcel(BaseModel):
    """A candidate parcel represented by a stable ID and query center."""

    model_config = ConfigDict(extra="forbid")

    parcel_id: NonEmptyString
    name: NonEmptyString | None = None
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    area_hectares: float | None = Field(default=None, gt=0)
    geometry_dataset_id: NonEmptyString | None = None


class ProjectRequest(BaseModel):
    """Validated entry contract for one site-selection analysis request."""

    model_config = ConfigDict(extra="forbid")

    request_id: NonEmptyString
    project_type: ProjectType
    candidate_parcels: Annotated[
        list[CandidateParcel],
        Field(min_length=1),
    ]
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def requested_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("请求时间必须包含时区")
        return value

    @model_validator(mode="after")
    def candidate_ids_are_unique(self) -> ProjectRequest:
        parcel_ids = [parcel.parcel_id for parcel in self.candidate_parcels]
        if len(parcel_ids) != len(set(parcel_ids)):
            raise ValueError("候选地块编号不能重复")
        return self


class DatasetManifest(BaseModel):
    """Versioned metadata for a dataset; credentials are never stored here."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: NonEmptyString
    name: NonEmptyString
    source: DatasetSource
    location: NonEmptyString = Field(
        description="表名、文件路径或不含密钥的 API 资源标识",
    )
    version: NonEmptyString
    crs: NonEmptyString | None = None
    required_fields: Annotated[
        list[NonEmptyString],
        Field(min_length=1),
    ]
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def updated_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("数据更新时间必须包含时区")
        return value

    @field_validator("required_fields")
    @classmethod
    def required_fields_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("必需字段不能重复")
        return values
