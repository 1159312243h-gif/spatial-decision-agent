from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from practice.llm_api.tool_registry import ToolDefinition, ToolRegistry

from .domain import NonEmptyString, ProjectType
from .policy_rag import PolicyHybridRetriever
from .poi import POIQuery, POIRecord
from .poi_metrics import build_poi_metrics_report
from .spatial.query_engine import StoredSpatialQueryBackend
from .storage.poi_repository import NearbyPOI


class NearbyPOIReader(Protocol):
    def search_nearby(
        self,
        *,
        longitude: float,
        latitude: float,
        radius_m: float,
        categories: list[NonEmptyString] | None = None,
        limit: int = 100,
    ) -> list[NearbyPOI]: ...


class SpatialFeatureArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer_id: NonEmptyString
    source_feature_id: NonEmptyString
    analysis_srid: int = Field(default=32651, ge=1, le=998_999)


class SpatialRelationArguments(SpatialFeatureArguments):
    context_layer_id: NonEmptyString


class NearbyPOIArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    radius_m: int = Field(ge=100, le=50_000)
    categories: list[NonEmptyString] | None = None
    limit: int = Field(default=100, ge=1, le=1_000)

    @field_validator("categories")
    @classmethod
    def categories_are_unique(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        if values is not None:
            if not values:
                raise ValueError("POI 类别列表不能为空")
            if len(values) != len(set(values)):
                raise ValueError("POI 类别不能重复")
        return values


class POIMetricsArguments(NearbyPOIArguments):
    distance_bands_m: list[int] = Field(min_length=1)

    @field_validator("distance_bands_m")
    @classmethod
    def bands_are_strictly_increasing(cls, values: list[int]) -> list[int]:
        if values != sorted(set(values)) or values[0] <= 0:
            raise ValueError("POI 距离分级必须严格递增且大于 0")
        return values


class PolicySearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: NonEmptyString
    project_type: ProjectType
    jurisdiction: NonEmptyString | None = None
    top_k: int = Field(default=5, ge=1, le=20)


def create_site_selection_tool_registry(
    spatial_backend: StoredSpatialQueryBackend,
    poi_reader: NearbyPOIReader,
    *,
    policy_retriever: PolicyHybridRetriever | None = None,
    timeout_seconds: float = 5,
) -> ToolRegistry:
    if spatial_backend is None or poi_reader is None:
        raise ValueError("GIS 和 POI 工具必须配置数据后端")

    def gis_feature_area(
        layer_id: str,
        source_feature_id: str,
        analysis_srid: int = 32651,
    ) -> dict[str, Any]:
        result = _require_spatial_result(
            spatial_backend.analyze(
                layer_id=layer_id,
                source_feature_id=source_feature_id,
                analysis_srid=analysis_srid,
            ),
            layer_id=layer_id,
            source_feature_id=source_feature_id,
        )
        return {
            "layer_id": layer_id,
            "source_feature_id": source_feature_id,
            "analysis_crs": result.analysis_crs,
            "area_hectares": result.area_hectares,
        }

    def gis_intersection_count(
        layer_id: str,
        source_feature_id: str,
        context_layer_id: str,
        analysis_srid: int = 32651,
    ) -> dict[str, Any]:
        result = _require_spatial_result(
            spatial_backend.analyze(
                layer_id=layer_id,
                source_feature_id=source_feature_id,
                analysis_srid=analysis_srid,
                context_layer_id=context_layer_id,
            ),
            layer_id=layer_id,
            source_feature_id=source_feature_id,
        )
        return {
            "layer_id": layer_id,
            "source_feature_id": source_feature_id,
            "context_layer_id": context_layer_id,
            "intersecting_feature_count": result.intersecting_feature_count,
        }

    def gis_nearest_distance(
        layer_id: str,
        source_feature_id: str,
        context_layer_id: str,
        analysis_srid: int = 32651,
    ) -> dict[str, Any]:
        result = _require_spatial_result(
            spatial_backend.analyze(
                layer_id=layer_id,
                source_feature_id=source_feature_id,
                analysis_srid=analysis_srid,
                context_layer_id=context_layer_id,
            ),
            layer_id=layer_id,
            source_feature_id=source_feature_id,
        )
        return {
            "layer_id": layer_id,
            "source_feature_id": source_feature_id,
            "context_layer_id": context_layer_id,
            "analysis_crs": result.analysis_crs,
            "nearest_feature_distance_m": result.nearest_feature_distance_m,
        }

    def poi_nearby(
        longitude: float,
        latitude: float,
        radius_m: int,
        categories: list[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        rows = poi_reader.search_nearby(
            longitude=longitude,
            latitude=latitude,
            radius_m=radius_m,
            categories=categories,
            limit=limit,
        )
        return {
            "record_count": len(rows),
            "records": [row.model_dump(mode="json") for row in rows],
        }

    def poi_metrics(
        longitude: float,
        latitude: float,
        radius_m: int,
        distance_bands_m: list[int],
        categories: list[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        if distance_bands_m[-1] > radius_m:
            raise ValueError("POI 距离分级不能超过查询半径")
        rows = poi_reader.search_nearby(
            longitude=longitude,
            latitude=latitude,
            radius_m=radius_m,
            categories=categories,
            limit=limit,
        )
        query = POIQuery(
            query_id="mcp:poi_metrics",
            parcel_id="mcp-query",
            group_key="mcp-query",
            longitude=longitude,
            latitude=latitude,
            categories=categories or ["all"],
            radius_m=radius_m,
            limit=limit,
        )
        records = [
            POIRecord(
                poi_id=f"{row.source}:{row.source_id}",
                name=row.name,
                category=row.category,
                longitude=row.longitude,
                latitude=row.latitude,
                distance_m=row.distance_m,
                attributes={
                    "source": row.source,
                    "source_id": row.source_id,
                    "fetched_at": row.fetched_at.isoformat(),
                },
            )
            for row in rows
        ]
        report = build_poi_metrics_report(
            query,
            records,
            distance_bands_m=distance_bands_m,
        )
        return report.model_dump(mode="json")

    definitions = [
        ToolDefinition(
            name="gis_feature_area",
            description="计算已入库候选地块的面积（公顷）。",
            arguments_model=SpatialFeatureArguments,
            handler=gis_feature_area,
            timeout_seconds=timeout_seconds,
        ),
        ToolDefinition(
            name="gis_intersection_count",
            description="统计候选地块与指定上下文图层相交的要素数量。",
            arguments_model=SpatialRelationArguments,
            handler=gis_intersection_count,
            timeout_seconds=timeout_seconds,
        ),
        ToolDefinition(
            name="gis_nearest_distance",
            description="计算候选地块到指定上下文图层的最近距离（米）。",
            arguments_model=SpatialRelationArguments,
            handler=gis_nearest_distance,
            timeout_seconds=timeout_seconds,
        ),
        ToolDefinition(
            name="poi_nearby",
            description="按中心点、半径和可选类别查询标准化 POI。",
            arguments_model=NearbyPOIArguments,
            handler=poi_nearby,
            timeout_seconds=timeout_seconds,
        ),
        ToolDefinition(
            name="poi_metrics",
            description="汇总 POI 最近距离、密度和累计距离分级数量。",
            arguments_model=POIMetricsArguments,
            handler=poi_metrics,
            timeout_seconds=timeout_seconds,
        ),
    ]
    if policy_retriever is not None:
        def policy_search(
            query: str,
            project_type: ProjectType,
            jurisdiction: str | None = None,
            top_k: int = 5,
        ) -> dict[str, Any]:
            results = policy_retriever.search(
                query,
                project_type=project_type,
                jurisdiction=jurisdiction,
                top_k=top_k,
            )
            return {
                "result_count": len(results),
                "results": [
                    result.model_dump(mode="json")
                    for result in results
                ],
            }

        definitions.append(
            ToolDefinition(
                name="policy_search",
                description="按项目类型检索政策切块并返回可定位引用。",
                arguments_model=PolicySearchArguments,
                handler=policy_search,
                timeout_seconds=timeout_seconds,
            )
        )
    return ToolRegistry(definitions)


def _require_spatial_result(
    result: Any,
    *,
    layer_id: str,
    source_feature_id: str,
) -> Any:
    if result is None:
        raise LookupError(
            "空间要素不存在："
            f"layer_id={layer_id}, source_feature_id={source_feature_id}"
        )
    return result
