from datetime import datetime, timezone
from math import pi

import geopandas as gpd
import pytest
from shapely.geometry import Point, Polygon

from practice.site_selection import (
    AgentState,
    CandidateParcel,
    DatasetManifest,
    DatasetSource,
    EvidenceStatus,
    GISEvidence,
    ProjectRequest,
    ProjectType,
    get_project_profile,
)
from practice.site_selection.spatial import (
    GISAnalysisBlockedError,
    MockSpatialDatasetGateway,
    calculate_spatial_metrics,
    run_gis_analysis,
)


NOW = datetime(2026, 8, 18, 23, 0, tzinfo=timezone.utc)
DATASET_ID = "parcel-analysis-2026-08"


def square() -> Polygon:
    return Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])


def parcel_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"parcel_id": ["A01"], "land_use": ["commercial"]},
        geometry=[square()],
        crs="EPSG:32651",
    )


def manifest() -> DatasetManifest:
    return DatasetManifest(
        dataset_id=DATASET_ID,
        name="地块分析数据",
        source=DatasetSource.POSTGIS,
        location="candidate_parcels",
        version="2026.08",
        crs="EPSG:32651",
        required_fields=["parcel_id", "land_use"],
        updated_at=NOW,
    )


def analysis_state(status: EvidenceStatus = EvidenceStatus.READY) -> AgentState:
    request = ProjectRequest(
        request_id="REQ-analysis",
        project_type=ProjectType.SHOPPING_MALL,
        candidate_parcels=[
            CandidateParcel(
                parcel_id="A01",
                longitude=121.47,
                latitude=31.23,
                geometry_dataset_id=DATASET_ID,
            )
        ],
        requested_at=NOW,
    )
    return AgentState(
        request=request,
        profile=get_project_profile(ProjectType.SHOPPING_MALL),
        datasets=[manifest()],
        gis_evidence=[
            GISEvidence(
                parcel_id="A01",
                status=status,
                dataset_ids=[DATASET_ID],
                crs="EPSG:32651" if status is EvidenceStatus.READY else None,
                geometry_valid=True if status is EvidenceStatus.READY else None,
                metrics={"feature_count": 1.0},
            )
        ],
    )


def test_calculates_area_perimeter_and_buffer() -> None:
    metrics = calculate_spatial_metrics(
        parcel_frame(),
        buffer_distance_m=10,
    )

    assert metrics.area_hectares == pytest.approx(1.0)
    assert metrics.perimeter_m == pytest.approx(400.0)
    assert metrics.buffer_distance_m == 10
    expected_buffer_area = (10_000 + 4_000 + pi * 100) / 10_000
    assert metrics.buffered_area_hectares == pytest.approx(
        expected_buffer_area,
        rel=1e-3,
    )


def test_calculates_intersection_count_and_zero_distance() -> None:
    context = gpd.GeoDataFrame(
        {"constraint_id": ["C1", "C2"]},
        geometry=[Point(50, 50), Point(200, 200)],
        crs="EPSG:32651",
    )

    metrics = calculate_spatial_metrics(
        parcel_frame(),
        buffer_distance_m=10,
        context_rows=context,
    )

    assert metrics.intersecting_feature_count == 1
    assert metrics.nearest_feature_distance_m == 0


def test_calculates_positive_nearest_distance() -> None:
    context = gpd.GeoDataFrame(
        {"constraint_id": ["C1"]},
        geometry=[Point(150, 50)],
        crs="EPSG:32651",
    )

    metrics = calculate_spatial_metrics(
        parcel_frame(),
        buffer_distance_m=10,
        context_rows=context,
    )

    assert metrics.intersecting_feature_count == 0
    assert metrics.nearest_feature_distance_m == pytest.approx(50)


def test_context_crs_mismatch_is_rejected() -> None:
    context = gpd.GeoDataFrame(
        {"constraint_id": ["C1"]},
        geometry=[Point(150, 50)],
        crs="EPSG:3857",
    )

    with pytest.raises(ValueError, match="CRS"):
        calculate_spatial_metrics(
            parcel_frame(),
            buffer_distance_m=10,
            context_rows=context,
        )


def test_non_polygon_target_is_blocked() -> None:
    points = gpd.GeoDataFrame(
        {"parcel_id": ["A01"]},
        geometry=[Point(0, 0)],
        crs="EPSG:32651",
    )

    with pytest.raises(GISAnalysisBlockedError, match="Polygon"):
        calculate_spatial_metrics(points, buffer_distance_m=10)


def test_non_positive_buffer_is_rejected() -> None:
    with pytest.raises(ValueError, match="缓冲距离"):
        calculate_spatial_metrics(parcel_frame(), buffer_distance_m=0)


@pytest.mark.parametrize(
    "status",
    [EvidenceStatus.MISSING, EvidenceStatus.INVALID],
)
def test_non_ready_evidence_blocks_analysis(status: EvidenceStatus) -> None:
    with pytest.raises(GISAnalysisBlockedError, match=status.value):
        run_gis_analysis(
            analysis_state(status),
            MockSpatialDatasetGateway({DATASET_ID: parcel_frame()}),
            buffer_distance_m=10,
        )


def test_ready_evidence_receives_deterministic_metrics() -> None:
    result = run_gis_analysis(
        analysis_state(),
        MockSpatialDatasetGateway({DATASET_ID: parcel_frame()}),
        buffer_distance_m=10,
    )

    metrics = result.gis_evidence[0].metrics
    assert result.gis_evidence[0].status is EvidenceStatus.READY
    assert metrics["feature_count"] == 1
    assert metrics["area_hectares"] == pytest.approx(1)
    assert metrics["perimeter_m"] == pytest.approx(400)
    assert metrics["buffer_distance_m"] == 10


def test_ready_state_is_blocked_if_gateway_data_disappears() -> None:
    with pytest.raises(GISAnalysisBlockedError, match="不可用"):
        run_gis_analysis(
            analysis_state(),
            MockSpatialDatasetGateway(),
            buffer_distance_m=10,
        )


def test_analysis_does_not_mutate_input_state_or_source_frame() -> None:
    initial_state = analysis_state()
    source = parcel_frame()
    original_source = source.copy(deep=True)

    result = run_gis_analysis(
        initial_state,
        MockSpatialDatasetGateway({DATASET_ID: source}),
        buffer_distance_m=10,
    )

    assert "area_hectares" not in initial_state.gis_evidence[0].metrics
    assert "area_hectares" in result.gis_evidence[0].metrics
    assert source.equals(original_source)
