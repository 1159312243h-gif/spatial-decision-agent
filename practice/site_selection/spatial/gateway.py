from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

import geopandas as gpd

from ..domain import DatasetManifest
from ..evidence import AgentState, EvidenceStatus, GISEvidence
from .validate import (
    SpatialValidationCode,
    SpatialValidationError,
    validate_spatial_dataset,
)


class SpatialDatasetNotFoundError(LookupError):
    """Raised when a registered dataset cannot be loaded by the gateway."""


class SpatialDatasetAccessError(RuntimeError):
    """Raised when a manifested dataset cannot be accessed safely."""


class SpatialDatasetGateway(Protocol):
    """Provider-neutral boundary for loading one manifested spatial dataset."""

    def load(self, manifest: DatasetManifest) -> gpd.GeoDataFrame: ...


class MockSpatialDatasetGateway:
    """Deterministic in-memory spatial dataset provider for workflow tests."""

    def __init__(
        self,
        datasets: Mapping[str, gpd.GeoDataFrame] | None = None,
    ) -> None:
        self._datasets = {
            dataset_id: frame.copy(deep=True)
            for dataset_id, frame in (datasets or {}).items()
        }

    def load(self, manifest: DatasetManifest) -> gpd.GeoDataFrame:
        try:
            frame = self._datasets[manifest.dataset_id]
        except KeyError as exc:
            raise SpatialDatasetNotFoundError(
                f"空间数据集不存在：{manifest.dataset_id}"
            ) from exc
        return frame.copy(deep=True)


def collect_gis_evidence(
    state: AgentState,
    gateway: SpatialDatasetGateway,
    *,
    require_projected: bool = True,
) -> AgentState:
    """Load and validate parcel datasets, then return updated GIS evidence."""

    manifests = {
        manifest.dataset_id: manifest
        for manifest in state.datasets
    }
    evidence = [
        _collect_parcel_evidence(
            parcel_id=parcel.parcel_id,
            dataset_id=parcel.geometry_dataset_id,
            manifests=manifests,
            gateway=gateway,
            require_projected=require_projected,
        )
        for parcel in state.request.candidate_parcels
    ]

    state_data = state.model_dump()
    state_data["gis_evidence"] = evidence
    return AgentState.model_validate(state_data)


def _collect_parcel_evidence(
    *,
    parcel_id: str,
    dataset_id: str | None,
    manifests: Mapping[str, DatasetManifest],
    gateway: SpatialDatasetGateway,
    require_projected: bool,
) -> GISEvidence:
    if dataset_id is None:
        return GISEvidence(
            parcel_id=parcel_id,
            status=EvidenceStatus.MISSING,
            notes=["候选地块未声明 geometry_dataset_id"],
        )

    manifest = manifests.get(dataset_id)
    if manifest is None:
        return GISEvidence(
            parcel_id=parcel_id,
            status=EvidenceStatus.MISSING,
            dataset_ids=[dataset_id],
            notes=[f"未找到 DatasetManifest：{dataset_id}"],
        )

    try:
        frame = gateway.load(manifest)
    except SpatialDatasetNotFoundError as exc:
        return GISEvidence(
            parcel_id=parcel_id,
            status=EvidenceStatus.MISSING,
            dataset_ids=[dataset_id],
            notes=[str(exc)],
        )
    except SpatialDatasetAccessError as exc:
        return GISEvidence(
            parcel_id=parcel_id,
            status=EvidenceStatus.INVALID,
            dataset_ids=[dataset_id],
            notes=[str(exc)],
        )

    try:
        validation = validate_spatial_dataset(
            frame,
            required_fields=[*manifest.required_fields, "parcel_id"],
            require_projected=require_projected,
            expected_crs=manifest.crs,
        )
    except SpatialValidationError as exc:
        geometry_invalid = exc.code in {
            SpatialValidationCode.NULL_GEOMETRY,
            SpatialValidationCode.EMPTY_GEOMETRY,
            SpatialValidationCode.INVALID_GEOMETRY,
        }
        return GISEvidence(
            parcel_id=parcel_id,
            status=EvidenceStatus.INVALID,
            dataset_ids=[dataset_id],
            crs=str(frame.crs) if frame.crs is not None else None,
            geometry_valid=False if geometry_invalid else None,
            notes=[f"{exc.code.value}: {exc}"],
        )

    parcel_rows = frame[frame["parcel_id"] == parcel_id]
    if parcel_rows.empty:
        return GISEvidence(
            parcel_id=parcel_id,
            status=EvidenceStatus.MISSING,
            dataset_ids=[dataset_id],
            crs=validation.crs,
            geometry_valid=True,
            notes=[f"数据集中不存在候选地块：{parcel_id}"],
        )

    return GISEvidence(
        parcel_id=parcel_id,
        status=EvidenceStatus.READY,
        dataset_ids=[dataset_id],
        crs=validation.crs,
        geometry_valid=True,
        metrics={"feature_count": float(len(parcel_rows))},
    )
