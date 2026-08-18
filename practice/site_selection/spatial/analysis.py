from __future__ import annotations

from collections.abc import Mapping

import geopandas as gpd
from pydantic import BaseModel, ConfigDict, Field

from ..domain import DatasetManifest
from ..evidence import AgentState, EvidenceStatus, GISEvidence
from .gateway import SpatialDatasetGateway, SpatialDatasetNotFoundError
from .validate import SpatialValidationError, validate_spatial_dataset


class GISAnalysisBlockedError(RuntimeError):
    """Raised when mandatory evidence does not permit GIS analysis."""


class SpatialMetrics(BaseModel):
    """Deterministic metric output; values use the projected CRS units."""

    model_config = ConfigDict(extra="forbid")

    area_hectares: float = Field(ge=0)
    perimeter_m: float = Field(ge=0)
    buffer_distance_m: float = Field(gt=0)
    buffered_area_hectares: float = Field(ge=0)
    intersecting_feature_count: int | None = Field(default=None, ge=0)
    nearest_feature_distance_m: float | None = Field(default=None, ge=0)


def calculate_spatial_metrics(
    parcel_rows: gpd.GeoDataFrame,
    *,
    buffer_distance_m: float,
    context_rows: gpd.GeoDataFrame | None = None,
) -> SpatialMetrics:
    """Calculate parcel metrics and optional relations to a context layer."""

    if buffer_distance_m <= 0:
        raise ValueError("缓冲距离必须大于 0")

    parcel_validation = validate_spatial_dataset(
        parcel_rows,
        required_fields=[],
        require_projected=True,
    )
    allowed_types = {"Polygon", "MultiPolygon"}
    if not set(parcel_validation.geometry_types).issubset(allowed_types):
        raise GISAnalysisBlockedError("地块分析只接受 Polygon 或 MultiPolygon")

    parcel_geometry = parcel_rows.geometry.union_all()
    buffered_geometry = parcel_geometry.buffer(buffer_distance_m)
    metrics: dict[str, float | int | None] = {
        "area_hectares": parcel_geometry.area / 10_000,
        "perimeter_m": parcel_geometry.length,
        "buffer_distance_m": buffer_distance_m,
        "buffered_area_hectares": buffered_geometry.area / 10_000,
        "intersecting_feature_count": None,
        "nearest_feature_distance_m": None,
    }

    if context_rows is not None:
        validate_spatial_dataset(
            context_rows,
            required_fields=[],
            require_projected=True,
            expected_crs=parcel_rows.crs,
        )
        metrics["intersecting_feature_count"] = int(
            context_rows.geometry.intersects(parcel_geometry).sum()
        )
        metrics["nearest_feature_distance_m"] = float(
            context_rows.geometry.distance(parcel_geometry).min()
        )

    return SpatialMetrics.model_validate(metrics)


def run_gis_analysis(
    state: AgentState,
    gateway: SpatialDatasetGateway,
    *,
    buffer_distance_m: float = 500,
) -> AgentState:
    """Calculate parcel metrics only when every parcel has READY evidence."""

    evidence_by_parcel = {
        evidence.parcel_id: evidence
        for evidence in state.gis_evidence
    }
    manifests = {
        manifest.dataset_id: manifest
        for manifest in state.datasets
    }

    updated_evidence = [
        _analyze_parcel(
            parcel_id=parcel.parcel_id,
            dataset_id=parcel.geometry_dataset_id,
            evidence=evidence_by_parcel.get(parcel.parcel_id),
            manifests=manifests,
            gateway=gateway,
            buffer_distance_m=buffer_distance_m,
        )
        for parcel in state.request.candidate_parcels
    ]

    state_data = state.model_dump()
    state_data["gis_evidence"] = updated_evidence
    return AgentState.model_validate(state_data)


def _analyze_parcel(
    *,
    parcel_id: str,
    dataset_id: str | None,
    evidence: GISEvidence | None,
    manifests: Mapping[str, DatasetManifest],
    gateway: SpatialDatasetGateway,
    buffer_distance_m: float,
) -> GISEvidence:
    if evidence is None:
        raise GISAnalysisBlockedError(f"地块缺少 GIS 证据：{parcel_id}")
    if evidence.status is not EvidenceStatus.READY:
        raise GISAnalysisBlockedError(
            f"地块 GIS 证据未就绪：{parcel_id}, status={evidence.status.value}"
        )
    if dataset_id is None:
        raise GISAnalysisBlockedError(f"地块缺少 geometry_dataset_id：{parcel_id}")

    manifest = manifests.get(dataset_id)
    if manifest is None:
        raise GISAnalysisBlockedError(f"缺少 DatasetManifest：{dataset_id}")

    try:
        frame = gateway.load(manifest)
        validate_spatial_dataset(
            frame,
            required_fields=[*manifest.required_fields, "parcel_id"],
            require_projected=True,
            expected_crs=manifest.crs,
        )
    except (SpatialDatasetNotFoundError, SpatialValidationError) as exc:
        raise GISAnalysisBlockedError(
            f"READY 证据对应的数据已不可用：{dataset_id}"
        ) from exc

    parcel_rows = frame[frame["parcel_id"] == parcel_id]
    if parcel_rows.empty:
        raise GISAnalysisBlockedError(f"数据集中不存在候选地块：{parcel_id}")

    spatial_metrics = calculate_spatial_metrics(
        parcel_rows,
        buffer_distance_m=buffer_distance_m,
    )
    metrics = {
        **evidence.metrics,
        **spatial_metrics.model_dump(exclude_none=True),
    }
    evidence_data = evidence.model_dump()
    evidence_data["metrics"] = metrics
    return GISEvidence.model_validate(evidence_data)
