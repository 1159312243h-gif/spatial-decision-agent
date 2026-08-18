from datetime import datetime, timezone

import geopandas as gpd
from shapely.geometry import Polygon

from practice.site_selection import (
    AgentState,
    CandidateParcel,
    DatasetManifest,
    DatasetSource,
    EvidenceStatus,
    ProjectRequest,
    ProjectType,
    get_project_profile,
)
from practice.site_selection.spatial import (
    MockSpatialDatasetGateway,
    collect_gis_evidence,
)


NOW = datetime(2026, 8, 18, 22, 30, tzinfo=timezone.utc)
DATASET_ID = "parcel-geometry-2026-08"


def polygon() -> Polygon:
    return Polygon(
        [
            (300000, 3450000),
            (300100, 3450000),
            (300100, 3450100),
            (300000, 3450000),
        ]
    )


def frame(
    *,
    parcel_id: str = "A01",
    crs: str | None = "EPSG:32651",
    geometry: Polygon | None = None,
) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "parcel_id": [parcel_id],
            "land_use": ["commercial"],
        },
        geometry=[polygon() if geometry is None else geometry],
        crs=crs,
    )


def manifest(
    *,
    crs: str | None = "EPSG:32651",
    required_fields: list[str] | None = None,
) -> DatasetManifest:
    return DatasetManifest(
        dataset_id=DATASET_ID,
        name="候选地块几何",
        source=DatasetSource.POSTGIS,
        location="candidate_parcels",
        version="2026.08",
        crs=crs,
        required_fields=required_fields or ["parcel_id", "land_use"],
        updated_at=NOW,
    )


def state(
    *,
    geometry_dataset_id: str | None = DATASET_ID,
    manifests: list[DatasetManifest] | None = None,
) -> AgentState:
    request = ProjectRequest(
        request_id="REQ-gis",
        project_type=ProjectType.SHOPPING_MALL,
        candidate_parcels=[
            CandidateParcel(
                parcel_id="A01",
                longitude=121.47,
                latitude=31.23,
                geometry_dataset_id=geometry_dataset_id,
            )
        ],
        requested_at=NOW,
    )
    return AgentState(
        request=request,
        profile=get_project_profile(ProjectType.SHOPPING_MALL),
        datasets=[manifest()] if manifests is None else manifests,
    )


def test_valid_dataset_becomes_ready_gis_evidence() -> None:
    result = collect_gis_evidence(
        state(),
        MockSpatialDatasetGateway({DATASET_ID: frame()}),
    )

    evidence = result.gis_evidence[0]
    assert evidence.status is EvidenceStatus.READY
    assert evidence.dataset_ids == [DATASET_ID]
    assert evidence.crs == "EPSG:32651"
    assert evidence.geometry_valid is True
    assert evidence.metrics == {"feature_count": 1.0}


def test_missing_geometry_dataset_reference_becomes_missing() -> None:
    result = collect_gis_evidence(
        state(geometry_dataset_id=None),
        MockSpatialDatasetGateway(),
    )

    assert result.gis_evidence[0].status is EvidenceStatus.MISSING
    assert "geometry_dataset_id" in result.gis_evidence[0].notes[0]


def test_missing_manifest_becomes_missing() -> None:
    result = collect_gis_evidence(
        state(manifests=[]),
        MockSpatialDatasetGateway(),
    )

    assert result.gis_evidence[0].status is EvidenceStatus.MISSING
    assert "DatasetManifest" in result.gis_evidence[0].notes[0]


def test_gateway_missing_dataset_becomes_missing() -> None:
    result = collect_gis_evidence(state(), MockSpatialDatasetGateway())

    assert result.gis_evidence[0].status is EvidenceStatus.MISSING
    assert DATASET_ID in result.gis_evidence[0].notes[0]


def test_missing_crs_becomes_invalid() -> None:
    result = collect_gis_evidence(
        state(),
        MockSpatialDatasetGateway({DATASET_ID: frame(crs=None)}),
    )

    assert result.gis_evidence[0].status is EvidenceStatus.INVALID
    assert result.gis_evidence[0].notes[0].startswith("missing_crs:")


def test_manifest_crs_mismatch_becomes_invalid() -> None:
    result = collect_gis_evidence(
        state(),
        MockSpatialDatasetGateway(
            {DATASET_ID: frame(crs=None).set_crs("EPSG:3857")}
        ),
    )

    assert result.gis_evidence[0].status is EvidenceStatus.INVALID
    assert result.gis_evidence[0].notes[0].startswith("crs_mismatch:")


def test_missing_required_field_becomes_invalid() -> None:
    missing_field_frame = frame().drop(columns=["land_use"])

    result = collect_gis_evidence(
        state(),
        MockSpatialDatasetGateway({DATASET_ID: missing_field_frame}),
    )

    assert result.gis_evidence[0].status is EvidenceStatus.INVALID
    assert result.gis_evidence[0].notes[0].startswith("missing_fields:")


def test_invalid_geometry_becomes_invalid() -> None:
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])

    result = collect_gis_evidence(
        state(),
        MockSpatialDatasetGateway(
            {DATASET_ID: frame(geometry=bowtie)}
        ),
    )

    evidence = result.gis_evidence[0]
    assert evidence.status is EvidenceStatus.INVALID
    assert evidence.geometry_valid is False
    assert evidence.notes[0].startswith("invalid_geometry:")


def test_dataset_without_requested_parcel_becomes_missing() -> None:
    result = collect_gis_evidence(
        state(),
        MockSpatialDatasetGateway(
            {DATASET_ID: frame(parcel_id="B99")}
        ),
    )

    assert result.gis_evidence[0].status is EvidenceStatus.MISSING
    assert "A01" in result.gis_evidence[0].notes[0]


def test_gateway_and_collection_do_not_mutate_inputs() -> None:
    initial_state = state()
    source_frame = frame()
    original_frame = source_frame.copy(deep=True)

    result = collect_gis_evidence(
        initial_state,
        MockSpatialDatasetGateway({DATASET_ID: source_frame}),
    )

    assert initial_state.gis_evidence == []
    assert result.gis_evidence[0].status is EvidenceStatus.READY
    assert source_frame.equals(original_frame)
