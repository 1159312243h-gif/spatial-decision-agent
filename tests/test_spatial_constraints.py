from datetime import datetime, timezone

import geopandas as gpd
import pytest
from pydantic import ValidationError
from shapely.geometry import Point, Polygon

from practice.site_selection import (
    AgentState,
    CandidateParcel,
    ConstraintLayerSpec,
    ConstraintLayerType,
    DatasetManifest,
    DatasetSource,
    EvidenceStatus,
    GISEvidence,
    ProjectRequest,
    ProjectType,
    SpatialConstraintRelation,
    get_project_profile,
)
from practice.site_selection.spatial import (
    ConstraintAnalysisBlockedError,
    MockSpatialDatasetGateway,
    run_spatial_constraint_analysis,
)


NOW = datetime(2026, 8, 18, 23, 30, tzinfo=timezone.utc)
PARCEL_DATASET_ID = "parcel-2026-08"
CONSTRAINT_DATASET_ID = "ecology-2026-08"


def target_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"parcel_id": ["A01"], "land_use": ["commercial"]},
        geometry=[Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])],
        crs="EPSG:32651",
    )


def constraint_frame(point: Point = Point(50, 50)) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"constraint_id": ["E1"], "level": ["test"]},
        geometry=[point],
        crs="EPSG:32651",
    )


def dataset_manifest(
    dataset_id: str,
    required_fields: list[str],
) -> DatasetManifest:
    return DatasetManifest(
        dataset_id=dataset_id,
        name=dataset_id,
        source=DatasetSource.POSTGIS,
        location=dataset_id,
        version="2026.08",
        crs="EPSG:32651",
        required_fields=required_fields,
        updated_at=NOW,
    )


def ready_state(status: EvidenceStatus = EvidenceStatus.READY) -> AgentState:
    request = ProjectRequest(
        request_id="REQ-constraint",
        project_type=ProjectType.SHOPPING_MALL,
        candidate_parcels=[
            CandidateParcel(
                parcel_id="A01",
                longitude=121.47,
                latitude=31.23,
                geometry_dataset_id=PARCEL_DATASET_ID,
            )
        ],
        requested_at=NOW,
    )
    return AgentState(
        request=request,
        profile=get_project_profile(ProjectType.SHOPPING_MALL),
        datasets=[
            dataset_manifest(PARCEL_DATASET_ID, ["parcel_id", "land_use"]),
            dataset_manifest(CONSTRAINT_DATASET_ID, ["constraint_id", "level"]),
        ],
        gis_evidence=[
            GISEvidence(
                parcel_id="A01",
                status=status,
                dataset_ids=[PARCEL_DATASET_ID],
                crs="EPSG:32651" if status is EvidenceStatus.READY else None,
                geometry_valid=True if status is EvidenceStatus.READY else None,
            )
        ],
    )


def spec(
    *,
    relation: SpatialConstraintRelation = SpatialConstraintRelation.INTERSECTS,
    threshold: float | None = None,
    project_types: list[ProjectType] | None = None,
) -> ConstraintLayerSpec:
    return ConstraintLayerSpec(
        constraint_id="ecology-observation",
        display_name="生态保护空间观察",
        layer_type=ConstraintLayerType.ECOLOGICAL_PROTECTION,
        dataset_id=CONSTRAINT_DATASET_ID,
        relation=relation,
        applicable_project_types=project_types or [ProjectType.SHOPPING_MALL],
        required_fields=["constraint_id", "level"],
        distance_threshold_m=threshold,
    )


def gateway(context: gpd.GeoDataFrame | None = None) -> MockSpatialDatasetGateway:
    return MockSpatialDatasetGateway(
        {
            PARCEL_DATASET_ID: target_frame(),
            CONSTRAINT_DATASET_ID: context if context is not None else constraint_frame(),
        }
    )


def test_within_distance_requires_threshold() -> None:
    with pytest.raises(ValidationError, match="distance_threshold_m"):
        spec(relation=SpatialConstraintRelation.WITHIN_DISTANCE)


def test_intersects_forbids_distance_threshold() -> None:
    with pytest.raises(ValidationError, match="不能声明"):
        spec(threshold=100)


def test_intersection_condition_is_triggered() -> None:
    result = run_spatial_constraint_analysis(
        ready_state(),
        gateway(),
        [spec()],
    )

    observation = result.gis_evidence[0].constraint_observations[0]
    assert observation.triggered is True
    assert observation.intersecting_feature_count == 1
    assert observation.nearest_distance_m == 0
    assert observation.dataset_version == "2026.08"


def test_non_intersection_condition_is_not_triggered() -> None:
    result = run_spatial_constraint_analysis(
        ready_state(),
        gateway(constraint_frame(Point(150, 50))),
        [spec()],
    )

    observation = result.gis_evidence[0].constraint_observations[0]
    assert observation.triggered is False
    assert observation.nearest_distance_m == pytest.approx(50)


@pytest.mark.parametrize(
    ("threshold", "expected"),
    [(60, True), (40, False)],
)
def test_distance_condition_uses_configured_threshold(
    threshold: float,
    expected: bool,
) -> None:
    result = run_spatial_constraint_analysis(
        ready_state(),
        gateway(constraint_frame(Point(150, 50))),
        [
            spec(
                relation=SpatialConstraintRelation.WITHIN_DISTANCE,
                threshold=threshold,
            )
        ],
    )

    observation = result.gis_evidence[0].constraint_observations[0]
    assert observation.triggered is expected
    assert observation.distance_threshold_m == threshold


def test_non_applicable_project_constraint_is_skipped() -> None:
    result = run_spatial_constraint_analysis(
        ready_state(),
        gateway(),
        [spec(project_types=[ProjectType.LOGISTICS_PARK])],
    )

    assert result.gis_evidence[0].constraint_observations == []


@pytest.mark.parametrize(
    "status",
    [EvidenceStatus.MISSING, EvidenceStatus.INVALID],
)
def test_non_ready_target_evidence_blocks_constraints(
    status: EvidenceStatus,
) -> None:
    with pytest.raises(ConstraintAnalysisBlockedError, match=status.value):
        run_spatial_constraint_analysis(
            ready_state(status),
            gateway(),
            [spec()],
        )


def test_missing_constraint_manifest_blocks_analysis() -> None:
    current_state = ready_state()
    current_state.datasets = [current_state.datasets[0]]

    with pytest.raises(ConstraintAnalysisBlockedError, match="DatasetManifest"):
        run_spatial_constraint_analysis(current_state, gateway(), [spec()])


def test_invalid_constraint_geometry_blocks_analysis() -> None:
    invalid = constraint_frame()
    invalid.geometry = [None]

    with pytest.raises(ConstraintAnalysisBlockedError, match="数据不可用"):
        run_spatial_constraint_analysis(
            ready_state(),
            gateway(invalid),
            [spec()],
        )


def test_rerun_replaces_same_observation_instead_of_duplicating() -> None:
    first = run_spatial_constraint_analysis(ready_state(), gateway(), [spec()])
    second = run_spatial_constraint_analysis(first, gateway(), [spec()])

    assert len(second.gis_evidence[0].constraint_observations) == 1


def test_constraint_analysis_does_not_mutate_input_state() -> None:
    initial_state = ready_state()

    result = run_spatial_constraint_analysis(
        initial_state,
        gateway(),
        [spec()],
    )

    assert initial_state.gis_evidence[0].constraint_observations == []
    assert len(result.gis_evidence[0].constraint_observations) == 1
