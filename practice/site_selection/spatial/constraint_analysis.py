from __future__ import annotations

from collections.abc import Iterable, Mapping

import geopandas as gpd

from ..constraints import (
    ConstraintLayerSpec,
    ConstraintObservation,
    SpatialConstraintRelation,
)
from ..domain import DatasetManifest
from ..evidence import AgentState, EvidenceStatus, GISEvidence
from .analysis import GISAnalysisBlockedError, calculate_spatial_metrics
from .gateway import SpatialDatasetGateway, SpatialDatasetNotFoundError
from .validate import SpatialValidationError, validate_spatial_dataset


class ConstraintAnalysisBlockedError(RuntimeError):
    """Raised when target or constraint evidence is not safe to analyze."""


def run_spatial_constraint_analysis(
    state: AgentState,
    gateway: SpatialDatasetGateway,
    specs: Iterable[ConstraintLayerSpec],
) -> AgentState:
    """Evaluate spatial conditions without producing compliance decisions."""

    spec_list = [
        spec
        for spec in specs
        if state.request.project_type in spec.applicable_project_types
    ]
    constraint_ids = [spec.constraint_id for spec in spec_list]
    if len(constraint_ids) != len(set(constraint_ids)):
        raise ValueError("约束 constraint_id 不能重复")

    manifests = {
        manifest.dataset_id: manifest
        for manifest in state.datasets
    }
    evidence_by_parcel = {
        evidence.parcel_id: evidence
        for evidence in state.gis_evidence
    }
    updated_evidence = [
        _evaluate_parcel_constraints(
            parcel_id=parcel.parcel_id,
            target_dataset_id=parcel.geometry_dataset_id,
            evidence=evidence_by_parcel.get(parcel.parcel_id),
            manifests=manifests,
            gateway=gateway,
            specs=spec_list,
        )
        for parcel in state.request.candidate_parcels
    ]

    state_data = state.model_dump()
    state_data["gis_evidence"] = updated_evidence
    return AgentState.model_validate(state_data)


def _evaluate_parcel_constraints(
    *,
    parcel_id: str,
    target_dataset_id: str | None,
    evidence: GISEvidence | None,
    manifests: Mapping[str, DatasetManifest],
    gateway: SpatialDatasetGateway,
    specs: list[ConstraintLayerSpec],
) -> GISEvidence:
    if evidence is None or evidence.status is not EvidenceStatus.READY:
        status = "missing" if evidence is None else evidence.status.value
        raise ConstraintAnalysisBlockedError(
            f"地块 GIS 证据未就绪：{parcel_id}, status={status}"
        )
    if target_dataset_id is None:
        raise ConstraintAnalysisBlockedError(
            f"地块缺少 geometry_dataset_id：{parcel_id}"
        )

    target_manifest = _require_manifest(target_dataset_id, manifests)
    target_frame = _load_valid_frame(
        target_manifest,
        gateway,
        extra_required_fields=["parcel_id"],
    )
    parcel_rows = target_frame[target_frame["parcel_id"] == parcel_id]
    if parcel_rows.empty:
        raise ConstraintAnalysisBlockedError(
            f"目标数据集中不存在候选地块：{parcel_id}"
        )

    observations = [
        _evaluate_spec(
            parcel_id=parcel_id,
            parcel_rows=parcel_rows,
            spec=spec,
            manifests=manifests,
            gateway=gateway,
        )
        for spec in specs
    ]

    evaluated_ids = {observation.constraint_id for observation in observations}
    preserved = [
        observation
        for observation in evidence.constraint_observations
        if observation.constraint_id not in evaluated_ids
    ]
    evidence_data = evidence.model_dump()
    evidence_data["constraint_observations"] = [*preserved, *observations]
    return GISEvidence.model_validate(evidence_data)


def _evaluate_spec(
    *,
    parcel_id: str,
    parcel_rows: gpd.GeoDataFrame,
    spec: ConstraintLayerSpec,
    manifests: Mapping[str, DatasetManifest],
    gateway: SpatialDatasetGateway,
) -> ConstraintObservation:
    manifest = _require_manifest(spec.dataset_id, manifests)
    context_rows = _load_valid_frame(
        manifest,
        gateway,
        extra_required_fields=spec.required_fields,
    )
    if not context_rows.crs.equals(parcel_rows.crs):
        context_rows = context_rows.to_crs(parcel_rows.crs)

    metrics = calculate_spatial_metrics(
        parcel_rows,
        buffer_distance_m=1,
        context_rows=context_rows,
    )
    intersecting_count = metrics.intersecting_feature_count or 0
    nearest_distance = metrics.nearest_feature_distance_m
    if nearest_distance is None:
        raise ConstraintAnalysisBlockedError(
            f"约束图层无法计算最近距离：{spec.constraint_id}"
        )

    if spec.relation is SpatialConstraintRelation.INTERSECTS:
        triggered = intersecting_count > 0
    else:
        threshold = spec.distance_threshold_m
        if threshold is None:
            raise ConstraintAnalysisBlockedError(
                f"邻近约束缺少距离阈值：{spec.constraint_id}"
            )
        triggered = nearest_distance <= threshold

    return ConstraintObservation(
        parcel_id=parcel_id,
        constraint_id=spec.constraint_id,
        layer_type=spec.layer_type,
        dataset_id=manifest.dataset_id,
        dataset_version=manifest.version,
        relation=spec.relation,
        analysis_crs=str(parcel_rows.crs),
        intersecting_feature_count=intersecting_count,
        nearest_distance_m=nearest_distance,
        distance_threshold_m=spec.distance_threshold_m,
        triggered=triggered,
    )


def _require_manifest(
    dataset_id: str,
    manifests: Mapping[str, DatasetManifest],
) -> DatasetManifest:
    manifest = manifests.get(dataset_id)
    if manifest is None:
        raise ConstraintAnalysisBlockedError(
            f"缺少约束分析 DatasetManifest：{dataset_id}"
        )
    return manifest


def _load_valid_frame(
    manifest: DatasetManifest,
    gateway: SpatialDatasetGateway,
    *,
    extra_required_fields: Iterable[str],
) -> gpd.GeoDataFrame:
    try:
        frame = gateway.load(manifest)
        validate_spatial_dataset(
            frame,
            required_fields=[
                *manifest.required_fields,
                *extra_required_fields,
            ],
            require_projected=True,
            expected_crs=manifest.crs,
        )
    except (
        SpatialDatasetNotFoundError,
        SpatialValidationError,
        GISAnalysisBlockedError,
    ) as exc:
        raise ConstraintAnalysisBlockedError(
            f"约束分析数据不可用：{manifest.dataset_id}"
        ) from exc
    return frame
