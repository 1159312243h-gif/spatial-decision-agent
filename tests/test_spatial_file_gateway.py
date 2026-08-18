from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pytest
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
    FileSpatialDatasetGateway,
    SpatialDatasetAccessError,
    SpatialDatasetNotFoundError,
    collect_gis_evidence,
)


NOW = datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)
DATASET_ID = "parcel-file-fixture"


def frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"parcel_id": ["A01"], "land_use": ["commercial"]},
        geometry=[
            Polygon(
                [
                    (300000, 3450000),
                    (300100, 3450000),
                    (300100, 3450100),
                    (300000, 3450000),
                ]
            )
        ],
        crs="EPSG:32651",
    )


def manifest(
    *,
    location: str = "parcel.geojson",
    source: DatasetSource = DatasetSource.FILE,
) -> DatasetManifest:
    return DatasetManifest(
        dataset_id=DATASET_ID,
        name="文件型候选地块",
        source=source,
        location=location,
        version="fixture-2026.08.1",
        crs="EPSG:32651",
        required_fields=["parcel_id", "land_use"],
        updated_at=NOW,
    )


def state(active_manifest: DatasetManifest) -> AgentState:
    request = ProjectRequest(
        request_id="REQ-file-gateway",
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
        datasets=[active_manifest],
    )


def write_geojson(root: Path, name: str = "parcel.geojson") -> Path:
    path = root / name
    frame().to_file(path, driver="GeoJSON")
    return path


def test_loads_geojson_inside_configured_root(tmp_path: Path) -> None:
    write_geojson(tmp_path)
    gateway = FileSpatialDatasetGateway(tmp_path)

    loaded = gateway.load(manifest())

    assert loaded.crs.to_epsg() == 32651
    assert loaded["parcel_id"].tolist() == ["A01"]
    assert gateway.root == tmp_path.resolve()


def test_each_load_returns_a_fresh_frame(tmp_path: Path) -> None:
    write_geojson(tmp_path)
    gateway = FileSpatialDatasetGateway(tmp_path)

    first = gateway.load(manifest())
    first.loc[0, "land_use"] = "changed"
    second = gateway.load(manifest())

    assert second.loc[0, "land_use"] == "commercial"


def test_missing_file_raises_not_found_without_exposing_root(
    tmp_path: Path,
) -> None:
    gateway = FileSpatialDatasetGateway(tmp_path)

    with pytest.raises(SpatialDatasetNotFoundError) as exc_info:
        gateway.load(manifest(location="missing.geojson"))

    assert DATASET_ID in str(exc_info.value)
    assert str(tmp_path) not in str(exc_info.value)


def test_rejects_non_file_manifest(tmp_path: Path) -> None:
    gateway = FileSpatialDatasetGateway(tmp_path)

    with pytest.raises(SpatialDatasetAccessError, match="unsupported_source"):
        gateway.load(manifest(source=DatasetSource.POSTGIS))


@pytest.mark.parametrize(
    "location",
    ["../outside.geojson", "nested/../../outside.geojson"],
)
def test_rejects_location_outside_root(
    tmp_path: Path,
    location: str,
) -> None:
    gateway = FileSpatialDatasetGateway(tmp_path)

    with pytest.raises(
        SpatialDatasetAccessError,
        match="location_outside_root",
    ):
        gateway.load(manifest(location=location))


def test_rejects_absolute_location(tmp_path: Path) -> None:
    gateway = FileSpatialDatasetGateway(tmp_path)
    absolute = str((tmp_path / "parcel.geojson").resolve())

    with pytest.raises(SpatialDatasetAccessError, match="absolute_location"):
        gateway.load(manifest(location=absolute))


def test_rejects_unsupported_file_format(tmp_path: Path) -> None:
    gateway = FileSpatialDatasetGateway(tmp_path)

    with pytest.raises(SpatialDatasetAccessError, match="unsupported_format"):
        gateway.load(manifest(location="parcel.csv"))


def test_read_error_is_sanitized(tmp_path: Path) -> None:
    path = tmp_path / "broken.geojson"
    path.write_text("secret-source-content", encoding="utf-8")
    gateway = FileSpatialDatasetGateway(tmp_path)

    with pytest.raises(SpatialDatasetAccessError) as exc_info:
        gateway.load(manifest(location=path.name))

    message = str(exc_info.value)
    assert message.startswith("read_failed:")
    assert "secret-source-content" not in message


def test_collection_maps_unsafe_manifest_to_invalid_evidence(
    tmp_path: Path,
) -> None:
    unsafe_manifest = manifest(source=DatasetSource.POSTGIS)

    result = collect_gis_evidence(
        state(unsafe_manifest),
        FileSpatialDatasetGateway(tmp_path),
    )

    evidence = result.gis_evidence[0]
    assert evidence.status is EvidenceStatus.INVALID
    assert evidence.notes[0].startswith("unsupported_source:")


def test_gateway_requires_existing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing-root"

    with pytest.raises(ValueError, match="根目录"):
        FileSpatialDatasetGateway(missing)
