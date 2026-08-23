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
    poi_query_limit: int = Field(default=100, ge=1, le=1_000)
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


COFFEE_SHOP_PROFILE = ProjectProfile(
    project_type=ProjectType.COFFEE_SHOP,
    display_name="咖啡店",
    poi_query_limit=1_000,
    poi_groups=[
        POICategoryConfig(
            group_key="transit_access",
            display_name="交通便利度",
            categories=["地铁站", "公交站"],
            query_radius_m=1_200,
            metrics=[POIMetric.COUNT, POIMetric.NEAREST_DISTANCE_M],
            soft_score_weight=0.20,
        ),
        POICategoryConfig(
            group_key="office_demand_proxy",
            display_name="办公需求代理指标",
            categories=["写字楼", "产业园"],
            query_radius_m=1_500,
            metrics=[POIMetric.COUNT, POIMetric.DENSITY_PER_SQ_KM],
            soft_score_weight=0.20,
        ),
        POICategoryConfig(
            group_key="residential_demand_proxy",
            display_name="居住需求代理指标",
            categories=["住宅小区", "公寓"],
            query_radius_m=1_500,
            metrics=[POIMetric.COUNT, POIMetric.DENSITY_PER_SQ_KM],
            soft_score_weight=0.15,
        ),
        POICategoryConfig(
            group_key="complementary_commerce",
            display_name="互补业态",
            categories=["餐厅", "书店", "购物中心"],
            query_radius_m=1_200,
            metrics=[POIMetric.COUNT, POIMetric.AVERAGE_DISTANCE_M],
            soft_score_weight=0.15,
        ),
        POICategoryConfig(
            group_key="coffee_competition",
            display_name="咖啡同业竞争密度",
            categories=["咖啡馆"],
            query_radius_m=1_000,
            metrics=[POIMetric.COUNT, POIMetric.NEAREST_DISTANCE_M],
            soft_score_weight=0.20,
        ),
        POICategoryConfig(
            group_key="stay_environment",
            display_name="停留环境代理指标",
            categories=["公园", "文化场馆"],
            query_radius_m=1_500,
            metrics=[POIMetric.COUNT, POIMetric.NEAREST_DISTANCE_M],
            soft_score_weight=0.10,
        ),
    ],
)


CONVENIENCE_STORE_PROFILE = ProjectProfile(
    project_type=ProjectType.CONVENIENCE_STORE,
    display_name="便利店",
    poi_query_limit=1_000,
    poi_groups=[
        POICategoryConfig(
            group_key="residential_demand_proxy",
            display_name="居住需求代理指标",
            categories=["住宅小区", "公寓"],
            query_radius_m=1_000,
            metrics=[POIMetric.COUNT, POIMetric.DENSITY_PER_SQ_KM],
            soft_score_weight=0.25,
        ),
        POICategoryConfig(
            group_key="office_school_demand_proxy",
            display_name="办公与学校需求代理指标",
            categories=["写字楼", "学校"],
            query_radius_m=1_200,
            metrics=[POIMetric.COUNT, POIMetric.DENSITY_PER_SQ_KM],
            soft_score_weight=0.20,
        ),
        POICategoryConfig(
            group_key="transit_access",
            display_name="交通便利度",
            categories=["地铁站", "公交站"],
            query_radius_m=1_000,
            metrics=[POIMetric.COUNT, POIMetric.NEAREST_DISTANCE_M],
            soft_score_weight=0.15,
        ),
        POICategoryConfig(
            group_key="complementary_services",
            display_name="互补生活服务",
            categories=["餐厅", "医院", "快递网点"],
            query_radius_m=1_000,
            metrics=[POIMetric.COUNT, POIMetric.AVERAGE_DISTANCE_M],
            soft_score_weight=0.10,
        ),
        POICategoryConfig(
            group_key="convenience_competition",
            display_name="便利零售竞争密度",
            categories=["便利店", "超市"],
            query_radius_m=800,
            metrics=[POIMetric.COUNT, POIMetric.NEAREST_DISTANCE_M],
            soft_score_weight=0.20,
        ),
        POICategoryConfig(
            group_key="parking_access",
            display_name="停车与车辆服务便利度",
            categories=["停车场", "加油站"],
            query_radius_m=1_200,
            metrics=[POIMetric.COUNT, POIMetric.NEAREST_DISTANCE_M],
            soft_score_weight=0.10,
        ),
    ],
)


PROJECT_PROFILES: dict[ProjectType, ProjectProfile] = {
    ProjectType.SHOPPING_MALL: SHOPPING_MALL_PROFILE,
    ProjectType.LOGISTICS_PARK: LOGISTICS_PARK_PROFILE,
    ProjectType.COFFEE_SHOP: COFFEE_SHOP_PROFILE,
    ProjectType.CONVENIENCE_STORE: CONVENIENCE_STORE_PROFILE,
}


def get_project_profile(project_type: ProjectType) -> ProjectProfile:
    return PROJECT_PROFILES[project_type].model_copy(deep=True)


def get_supported_poi_categories() -> tuple[str, ...]:
    """Return the reviewed category catalog supported by all profiles."""

    return tuple(
        sorted(
            {
                category
                for profile in PROJECT_PROFILES.values()
                for group in profile.poi_groups
                for category in group.categories
            }
        )
    )
