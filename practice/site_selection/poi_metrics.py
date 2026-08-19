from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from .poi import POIMetric, POIQuery, POIRecord
from .poi_service import calculate_poi_metrics


class POIDistanceBandCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upper_bound_m: int = Field(gt=0)
    count: int = Field(ge=0)


class POIMetricsReport(BaseModel):
    """Auditable POI summary with cumulative distance-band counts."""

    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=0)
    density_per_sq_km: float = Field(ge=0)
    nearest_distance_m: float | None = Field(default=None, ge=0)
    average_distance_m: float | None = Field(default=None, ge=0)
    distance_bands: list[POIDistanceBandCount] = Field(min_length=1)


def build_poi_metrics_report(
    query: POIQuery,
    records: Iterable[POIRecord],
    *,
    distance_bands_m: Iterable[int],
) -> POIMetricsReport:
    record_list = list(records)
    bands = list(distance_bands_m)
    if not bands:
        raise ValueError("POI 距离分级不能为空")
    if bands != sorted(set(bands)):
        raise ValueError("POI 距离分级必须严格递增且不能重复")
    if bands[0] <= 0 or bands[-1] > query.radius_m:
        raise ValueError("POI 距离分级必须大于 0 且不能超过查询半径")

    metrics = calculate_poi_metrics(query, record_list)
    distances = [
        record.distance_m
        for record in record_list
        if record.distance_m is not None
    ]
    return POIMetricsReport(
        count=int(metrics[POIMetric.COUNT]),
        density_per_sq_km=metrics[POIMetric.DENSITY_PER_SQ_KM],
        nearest_distance_m=metrics.get(POIMetric.NEAREST_DISTANCE_M),
        average_distance_m=metrics.get(POIMetric.AVERAGE_DISTANCE_M),
        distance_bands=[
            POIDistanceBandCount(
                upper_bound_m=upper_bound,
                count=sum(distance <= upper_bound for distance in distances),
            )
            for upper_bound in bands
        ],
    )
