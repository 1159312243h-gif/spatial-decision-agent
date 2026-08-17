from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain import NonEmptyString, ProjectType
from .poi import POIMetric


class POICategoryConfig(BaseModel):
    """Profile rule for one logical POI category group."""

    model_config = ConfigDict(extra="forbid")

    group_key: NonEmptyString
    display_name: NonEmptyString
    categories: Annotated[list[NonEmptyString], Field(min_length=1)]
    query_radius_m: int = Field(ge=100, le=50_000)
    metrics: Annotated[list[POIMetric], Field(min_length=1)]
    soft_score_weight: float = Field(gt=0, le=1)

    @field_validator("categories", "metrics")
    @classmethod
    def list_values_are_unique(cls, values: list[object]) -> list[object]:
        if len(values) != len(set(values)):
            raise ValueError("Profile 列表项不能重复")
        return values


class ProjectProfile(BaseModel):
    """Project-specific POI query and soft-scoring configuration."""

    model_config = ConfigDict(extra="forbid")

    project_type: ProjectType
    display_name: NonEmptyString
    poi_groups: Annotated[list[POICategoryConfig], Field(min_length=5)]

    @model_validator(mode="after")
    def groups_are_valid(self) -> ProjectProfile:
        keys = [group.group_key for group in self.poi_groups]
        if len(keys) != len(set(keys)):
            raise ValueError("POI 分组标识不能重复")

        weight_sum = sum(group.soft_score_weight for group in self.poi_groups)
        if abs(weight_sum - 1.0) > 1e-9:
            raise ValueError("POI 软评分权重之和必须为 1")
        return self


SHOPPING_MALL_PROFILE = ProjectProfile(
    project_type=ProjectType.SHOPPING_MALL,
    display_name="商场",
    poi_groups=[
        POICategoryConfig(
            group_key="public_transit",
            display_name="公共交通",
            categories=["地铁站", "公交站"],
            query_radius_m=1_500,
            metrics=[POIMetric.COUNT, POIMetric.NEAREST_DISTANCE_M],
            soft_score_weight=0.25,
        ),
        POICategoryConfig(
            group_key="residential",
            display_name="居住人口载体",
            categories=["住宅小区", "公寓"],
            query_radius_m=3_000,
            metrics=[POIMetric.COUNT, POIMetric.DENSITY_PER_SQ_KM],
            soft_score_weight=0.20,
        ),
        POICategoryConfig(
            group_key="office",
            display_name="办公客群",
            categories=["写字楼", "产业园"],
            query_radius_m=3_000,
            metrics=[POIMetric.COUNT, POIMetric.DENSITY_PER_SQ_KM],
            soft_score_weight=0.15,
        ),
        POICategoryConfig(
            group_key="catering",
            display_name="餐饮配套",
            categories=["餐厅", "咖啡馆"],
            query_radius_m=1_500,
            metrics=[POIMetric.COUNT, POIMetric.AVERAGE_DISTANCE_M],
            soft_score_weight=0.15,
        ),
        POICategoryConfig(
            group_key="public_service",
            display_name="公共服务",
            categories=["医院", "学校", "文化场馆"],
            query_radius_m=3_000,
            metrics=[POIMetric.COUNT, POIMetric.NEAREST_DISTANCE_M],
            soft_score_weight=0.10,
        ),
        POICategoryConfig(
            group_key="competitor",
            display_name="同类商业设施",
            categories=["购物中心", "百货商场"],
            query_radius_m=5_000,
            metrics=[POIMetric.COUNT, POIMetric.NEAREST_DISTANCE_M],
            soft_score_weight=0.15,
        ),
    ],
)


LOGISTICS_PARK_PROFILE = ProjectProfile(
    project_type=ProjectType.LOGISTICS_PARK,
    display_name="物流园",
    poi_groups=[
        POICategoryConfig(
            group_key="highway_access",
            display_name="高速公路入口",
            categories=["高速收费站", "高速出入口"],
            query_radius_m=15_000,
            metrics=[POIMetric.COUNT, POIMetric.NEAREST_DISTANCE_M],
            soft_score_weight=0.25,
        ),
        POICategoryConfig(
            group_key="freight_hub",
            display_name="货运枢纽",
            categories=["铁路货运站", "港口", "货运机场"],
            query_radius_m=50_000,
            metrics=[POIMetric.COUNT, POIMetric.NEAREST_DISTANCE_M],
            soft_score_weight=0.25,
        ),
        POICategoryConfig(
            group_key="logistics_service",
            display_name="物流服务",
            categories=["物流公司", "快递网点"],
            query_radius_m=10_000,
            metrics=[POIMetric.COUNT, POIMetric.DENSITY_PER_SQ_KM],
            soft_score_weight=0.15,
        ),
        POICategoryConfig(
            group_key="industrial_support",
            display_name="产业与仓储配套",
            categories=["工业园", "仓储基地"],
            query_radius_m=20_000,
            metrics=[POIMetric.COUNT, POIMetric.NEAREST_DISTANCE_M],
            soft_score_weight=0.15,
        ),
        POICategoryConfig(
            group_key="vehicle_service",
            display_name="车辆服务",
            categories=["加油站", "充电站", "货车维修"],
            query_radius_m=8_000,
            metrics=[POIMetric.COUNT, POIMetric.NEAREST_DISTANCE_M],
            soft_score_weight=0.10,
        ),
        POICategoryConfig(
            group_key="sensitive_receptor",
            display_name="敏感目标",
            categories=["住宅小区", "学校", "医院"],
            query_radius_m=3_000,
            metrics=[POIMetric.COUNT, POIMetric.NEAREST_DISTANCE_M],
            soft_score_weight=0.10,
        ),
    ],
)


PROJECT_PROFILES: dict[ProjectType, ProjectProfile] = {
    ProjectType.SHOPPING_MALL: SHOPPING_MALL_PROFILE,
    ProjectType.LOGISTICS_PARK: LOGISTICS_PARK_PROFILE,
}


def get_project_profile(project_type: ProjectType) -> ProjectProfile:
    return PROJECT_PROFILES[project_type].model_copy(deep=True)
