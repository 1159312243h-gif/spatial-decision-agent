from datetime import datetime, timezone

import geopandas as gpd
from shapely.geometry import Polygon

from practice.site_selection import DatasetSource, ProjectType
from practice.site_selection.storage.postgres import (
    PostgresSpatialRepository,
    ProjectStorageRecord,
    SpatialLayerWrite,
)
from tests.storage_fakes import FakeConnection, FakeResult


NOW = datetime(2026, 8, 19, 15, 30, tzinfo=timezone.utc)


def test_project_write_uses_bound_parameters() -> None:
    connection = FakeConnection()
    repository = PostgresSpatialRepository(connection)
    project = ProjectStorageRecord(
        project_id="project-001",
        project_type=ProjectType.SHOPPING_MALL,
        name="参数化测试项目",
        created_at=NOW,
        updated_at=NOW,
    )

    repository.upsert_project(project)

    sql, parameters = connection.calls[0]
    assert ":project_id" in sql
    assert "project-001" not in sql
    assert parameters["project_id"] == "project-001"
    assert parameters["project_type"] == "shopping_mall"


def test_project_can_be_read_by_id() -> None:
    connection = FakeConnection(
        [
            FakeResult(
                [
                    {
                        "project_id": "project-001",
                        "project_type": "shopping_mall",
                        "name": "测试项目",
                        "created_at": NOW,
                        "updated_at": NOW,
                    }
                ]
            )
        ]
    )

    result = PostgresSpatialRepository(connection).get_project("project-001")

    assert result is not None
    assert result.project_type is ProjectType.SHOPPING_MALL
    assert connection.calls[0][1] == {"project_id": "project-001"}


def test_layer_replacement_hashes_reprojects_and_bulk_writes() -> None:
    frame = gpd.GeoDataFrame(
        {
            "parcel_id": ["A01", "A02"],
            "land_use": ["commercial", "industrial"],
        },
        geometry=[
            Polygon([(300000, 3450000), (300100, 3450000), (300100, 3450100), (300000, 3450000)]),
            Polygon([(300200, 3450200), (300300, 3450200), (300300, 3450300), (300200, 3450200)]),
        ],
        crs="EPSG:32651",
    )
    layer = SpatialLayerWrite(
        layer_id="candidate-parcels",
        project_id="project-001",
        name="候选地块",
        layer_type="candidate_parcel",
        source=DatasetSource.FILE,
        version="2026.08.19",
        required_fields=["parcel_id", "land_use"],
        updated_at=NOW,
    )
    connection = FakeConnection()

    stored = PostgresSpatialRepository(connection).replace_layer(
        layer,
        frame,
        source_id_field="parcel_id",
    )

    assert stored.source_crs == "EPSG:32651"
    assert stored.normalized_crs == "EPSG:4326"
    assert len(stored.data_hash) == 64
    assert len(connection.calls) == 3
    insert_sql, feature_parameters = connection.calls[2]
    assert "ST_GeomFromText(:geometry_wkt, 4326)" in insert_sql
    assert len(feature_parameters) == 2
    assert {item["source_feature_id"] for item in feature_parameters} == {
        "A01",
        "A02",
    }
    assert all("300000" not in item["geometry_wkt"] for item in feature_parameters)


def test_spatial_feature_can_be_read_by_layer_and_source_id() -> None:
    connection = FakeConnection(
        [
            FakeResult(
                [
                    {
                        "feature_id": 7,
                        "layer_id": "candidate-parcels",
                        "source_feature_id": "A01",
                        "geometry_wkt": "POLYGON ((121 31, 122 31, 121 31))",
                        "properties": {"parcel_id": "A01"},
                    }
                ]
            )
        ]
    )

    result = PostgresSpatialRepository(connection).get_feature(
        "candidate-parcels",
        "A01",
    )

    assert result is not None
    assert result.feature_id == 7
    assert connection.calls[0][1] == {
        "layer_id": "candidate-parcels",
        "source_feature_id": "A01",
    }
