from datetime import datetime, timezone

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from practice.site_selection import DatasetManifest, DatasetSource
from practice.site_selection.spatial import (
    PostGISSpatialDatasetGateway,
    SpatialDatasetAccessError,
)


NOW = datetime(2026, 8, 18, 16, 0, tzinfo=timezone.utc)
DATASET_ID = "postgis-parcels"


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
    location: str = "candidate_parcels",
    source: DatasetSource = DatasetSource.POSTGIS,
) -> DatasetManifest:
    return DatasetManifest(
        dataset_id=DATASET_ID,
        name="PostGIS 候选地块",
        source=source,
        location=location,
        version="2026.08.1",
        crs="EPSG:32651",
        required_fields=["parcel_id", "land_use"],
        updated_at=NOW,
    )


class RecordingReader:
    def __init__(self, result: object | None = None) -> None:
        self.result = frame() if result is None else result
        self.calls: list[tuple[str, object, str]] = []

    def __call__(self, sql, connection, *, geom_col):
        self.calls.append((sql, connection, geom_col))
        return self.result


def test_loads_default_schema_with_quoted_identifiers() -> None:
    connection = object()
    reader = RecordingReader()
    gateway = PostGISSpatialDatasetGateway(connection, reader=reader)

    result = gateway.load(manifest())

    assert result["parcel_id"].tolist() == ["A01"]
    assert reader.calls == [
        (
            'SELECT * FROM "public"."candidate_parcels"',
            connection,
            "geometry",
        )
    ]


def test_loads_explicit_allowlisted_schema() -> None:
    reader = RecordingReader()
    gateway = PostGISSpatialDatasetGateway(
        object(),
        allowed_schemas=["public", "planning"],
        reader=reader,
    )

    gateway.load(manifest(location="planning.candidate_parcels"))

    assert reader.calls[0][0] == (
        'SELECT * FROM "planning"."candidate_parcels"'
    )
    assert gateway.allowed_schemas == frozenset({"public", "planning"})


@pytest.mark.parametrize(
    "location",
    [
        "public.parcels;DROP_TABLE",
        'public.parcels"',
        "public.parcels where true",
        "public.extra.parcels",
        "public.parcel-name",
    ],
)
def test_rejects_arbitrary_sql_in_manifest_location(location: str) -> None:
    gateway = PostGISSpatialDatasetGateway(object(), reader=RecordingReader())

    with pytest.raises(SpatialDatasetAccessError, match="invalid_relation"):
        gateway.load(manifest(location=location))


def test_rejects_schema_outside_allowlist() -> None:
    gateway = PostGISSpatialDatasetGateway(object(), reader=RecordingReader())

    with pytest.raises(SpatialDatasetAccessError, match="schema_not_allowed"):
        gateway.load(manifest(location="private.candidate_parcels"))


def test_rejects_non_postgis_manifest() -> None:
    gateway = PostGISSpatialDatasetGateway(object(), reader=RecordingReader())

    with pytest.raises(SpatialDatasetAccessError, match="unsupported_source"):
        gateway.load(manifest(source=DatasetSource.FILE))


def test_database_error_is_sanitized() -> None:
    def exploding_reader(*args, **kwargs):
        raise RuntimeError("password=secret database detail")

    gateway = PostGISSpatialDatasetGateway(
        object(),
        reader=exploding_reader,
    )

    with pytest.raises(SpatialDatasetAccessError) as exc_info:
        gateway.load(manifest())

    message = str(exc_info.value)
    assert message == (
        "postgis_read_failed: "
        "dataset_id=postgis-parcels, error_type=RuntimeError"
    )
    assert "password" not in message
    assert "secret" not in message


def test_rejects_reader_result_that_is_not_geodataframe() -> None:
    gateway = PostGISSpatialDatasetGateway(
        object(),
        reader=RecordingReader(result={"parcel_id": ["A01"]}),
    )

    with pytest.raises(
        SpatialDatasetAccessError,
        match="postgis_invalid_result",
    ):
        gateway.load(manifest())


def test_load_returns_defensive_copy() -> None:
    source = frame()
    gateway = PostGISSpatialDatasetGateway(
        object(),
        reader=RecordingReader(result=source),
    )

    loaded = gateway.load(manifest())
    loaded.loc[0, "land_use"] = "changed"

    assert source.loc[0, "land_use"] == "commercial"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"connection": None}, "数据库连接"),
        ({"connection": object(), "allowed_schemas": []}, "白名单"),
        (
            {
                "connection": object(),
                "allowed_schemas": ["planning"],
                "default_schema": "public",
            },
            "默认 schema",
        ),
        (
            {"connection": object(), "geometry_column": "geom;DROP"},
            "安全 SQL 标识符",
        ),
    ],
)
def test_constructor_rejects_unsafe_configuration(
    kwargs: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        PostGISSpatialDatasetGateway(**kwargs)
