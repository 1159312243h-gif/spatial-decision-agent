from datetime import datetime, timezone

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from practice.site_selection import DatasetManifest, DatasetSource
from practice.site_selection.spatial import (
    SpatialDatasetAccessError,
    StoredPostGISSpatialDatasetGateway,
)


NOW = datetime(2026, 8, 24, tzinfo=timezone.utc)


def manifest(*, source: DatasetSource = DatasetSource.POSTGIS) -> DatasetManifest:
    return DatasetManifest(
        dataset_id="fixture-candidate-layer",
        name="合成候选地块",
        source=source,
        location="fixture-candidate-layer",
        version="fixture-2026.08.24",
        crs="EPSG:32651",
        required_fields=["parcel_id", "land_use"],
        updated_at=NOW,
    )


def stored_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "source_feature_id": ["A01"],
            "properties": [
                {"parcel_id": "A01", "land_use": "commercial"}
            ],
            "normalized_crs": ["EPSG:4326"],
        },
        geometry=[
            Polygon(
                [
                    (121.47, 31.22),
                    (121.471, 31.22),
                    (121.471, 31.221),
                    (121.47, 31.22),
                ]
            )
        ],
        crs="EPSG:4326",
    )


class RecordingReader:
    def __init__(self, result=None) -> None:
        self.result = stored_frame() if result is None else result
        self.calls = []

    def __call__(self, sql, connection, *, geom_col, params):
        self.calls.append((str(sql), connection, geom_col, params))
        return self.result


def test_loads_normalized_layer_by_bound_layer_id_and_reprojects() -> None:
    connection = object()
    reader = RecordingReader()
    gateway = StoredPostGISSpatialDatasetGateway(connection, reader=reader)

    result = gateway.load(manifest())

    assert result.crs.to_string() == "EPSG:32651"
    assert result["parcel_id"].tolist() == ["A01"]
    assert result["land_use"].tolist() == ["commercial"]
    assert result["source_feature_id"].tolist() == ["A01"]
    sql, called_connection, geom_col, params = reader.calls[0]
    assert called_connection is connection
    assert geom_col == "geometry"
    assert params == {"layer_id": "fixture-candidate-layer"}
    assert ":layer_id" in sql
    assert "fixture-candidate-layer" not in sql
    assert "site_selection.spatial_features" in sql


def test_returns_defensive_copy_without_mutating_reader_frame() -> None:
    source = stored_frame()
    result = StoredPostGISSpatialDatasetGateway(
        object(), reader=RecordingReader(source)
    ).load(manifest())

    result.loc[0, "land_use"] = "changed"

    assert source.loc[0, "properties"]["land_use"] == "commercial"


def test_rejects_empty_or_malformed_stored_layers() -> None:
    empty = stored_frame().iloc[0:0]
    with pytest.raises(SpatialDatasetAccessError, match="layer_empty"):
        StoredPostGISSpatialDatasetGateway(
            object(), reader=RecordingReader(empty)
        ).load(manifest())

    malformed = stored_frame().drop(columns="properties")
    with pytest.raises(SpatialDatasetAccessError, match="invalid_result"):
        StoredPostGISSpatialDatasetGateway(
            object(), reader=RecordingReader(malformed)
        ).load(manifest())


def test_rejects_non_postgis_manifest_and_sanitizes_database_errors() -> None:
    gateway = StoredPostGISSpatialDatasetGateway(object(), reader=RecordingReader())
    with pytest.raises(SpatialDatasetAccessError, match="unsupported_source"):
        gateway.load(manifest(source=DatasetSource.FILE))

    def exploding_reader(*args, **kwargs):
        raise RuntimeError("password=secret")

    with pytest.raises(SpatialDatasetAccessError) as exc_info:
        StoredPostGISSpatialDatasetGateway(
            object(), reader=exploding_reader
        ).load(manifest())
    assert "password" not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)
    assert "error_type=RuntimeError" in str(exc_info.value)


def test_constructor_requires_connection() -> None:
    with pytest.raises(ValueError, match="数据库连接"):
        StoredPostGISSpatialDatasetGateway(None)
