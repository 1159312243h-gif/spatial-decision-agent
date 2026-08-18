from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain import NonEmptyString, ProjectType


class ConstraintLayerType(StrEnum):
    LAND_USE = "land_use"
    ECOLOGICAL_PROTECTION = "ecological_protection"
    FARMLAND_PROTECTION = "farmland_protection"
    DEVELOPMENT_BOUNDARY = "development_boundary"
    SENSITIVE_RECEPTOR = "sensitive_receptor"


class SpatialConstraintRelation(StrEnum):
    INTERSECTS = "intersects"
    WITHIN_DISTANCE = "within_distance"


class ConstraintLayerSpec(BaseModel):
    """Version-independent instructions for observing one constraint layer."""

    model_config = ConfigDict(extra="forbid")

    constraint_id: NonEmptyString
    display_name: NonEmptyString
    layer_type: ConstraintLayerType
    dataset_id: NonEmptyString
    relation: SpatialConstraintRelation
    applicable_project_types: Annotated[list[ProjectType], Field(min_length=1)]
    required_fields: Annotated[list[NonEmptyString], Field(min_length=1)]
    distance_threshold_m: float | None = Field(default=None, gt=0)

    @field_validator("applicable_project_types", "required_fields")
    @classmethod
    def values_are_unique(cls, values: list[object]) -> list[object]:
        if len(values) != len(set(values)):
            raise ValueError("约束配置列表项不能重复")
        return values

    @model_validator(mode="after")
    def relation_matches_threshold(self) -> ConstraintLayerSpec:
        if (
            self.relation is SpatialConstraintRelation.WITHIN_DISTANCE
            and self.distance_threshold_m is None
        ):
            raise ValueError("邻近约束必须声明 distance_threshold_m")
        if (
            self.relation is SpatialConstraintRelation.INTERSECTS
            and self.distance_threshold_m is not None
        ):
            raise ValueError("相交约束不能声明 distance_threshold_m")
        return self


class ConstraintObservation(BaseModel):
    """Auditable spatial fact; this is not a compliance conclusion."""

    model_config = ConfigDict(extra="forbid")

    parcel_id: NonEmptyString
    constraint_id: NonEmptyString
    layer_type: ConstraintLayerType
    dataset_id: NonEmptyString
    dataset_version: NonEmptyString
    relation: SpatialConstraintRelation
    analysis_crs: NonEmptyString
    intersecting_feature_count: int = Field(ge=0)
    nearest_distance_m: float = Field(ge=0)
    distance_threshold_m: float | None = Field(default=None, gt=0)
    triggered: bool
