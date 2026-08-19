from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import geopandas as gpd
from shapely.geometry import Polygon
from sqlalchemy import create_engine, text

from practice.site_selection import DatasetSource, ProjectType
from practice.site_selection.poi_normalizer import POINormalizer, RawPOI
from practice.site_selection.storage.poi_repository import PostgresPOIRepository
from practice.site_selection.storage.postgres import (
    PostgresSpatialRepository,
    ProjectStorageRecord,
    SpatialLayerWrite,
)
from scripts.apply_postgis_migrations import (
    apply_migration,
    build_host_database_url,
    load_environment,
)


PROJECT_ID = "storage-smoke-project"
LAYER_ID = "storage-smoke-candidates"
POI_SOURCE = "storage-smoke"
NOW = datetime.now(timezone.utc)


def candidate_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "parcel_id": ["SMOKE-A01"],
            "land_use": ["fixture-commercial"],
        },
        geometry=[
            Polygon(
                [
                    (121.4700, 31.2300),
                    (121.4710, 31.2300),
                    (121.4710, 31.2310),
                    (121.4700, 31.2300),
                ]
            )
        ],
        crs="EPSG:4326",
    )


def normalized_pois():
    normalizer = POINormalizer({"bus_stop": "公交站"})
    first = normalizer.normalize(
        RawPOI(
            source=POI_SOURCE,
            source_id="poi-001",
            name="旧名称",
            category="bus_stop",
            longitude=121.4705,
            latitude=31.2305,
            source_crs="WGS84",
            fetched_at=NOW,
            raw_payload={"revision": 1},
        )
    )
    second = first.model_copy(
        deep=True,
        update={"name": "更新名称", "raw_payload": {"revision": 2}},
    )
    return [first, second]


def run_smoke() -> None:
    load_environment()
    engine = create_engine(
        build_host_database_url(),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    try:
        apply_migration(engine)
        with engine.begin() as connection:
            spatial = PostgresSpatialRepository(connection)
            poi = PostgresPOIRepository(connection)
            spatial.upsert_project(
                ProjectStorageRecord(
                    project_id=PROJECT_ID,
                    project_type=ProjectType.SHOPPING_MALL,
                    name="Storage smoke project",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            layer = spatial.replace_layer(
                SpatialLayerWrite(
                    layer_id=LAYER_ID,
                    project_id=PROJECT_ID,
                    name="Storage smoke candidates",
                    layer_type="candidate_parcel",
                    source=DatasetSource.API,
                    version="smoke-1",
                    required_fields=["parcel_id", "land_use"],
                    updated_at=NOW,
                ),
                candidate_frame(),
                source_id_field="parcel_id",
            )
            project = spatial.get_project(PROJECT_ID)
            stored_layer = spatial.get_layer(LAYER_ID)
            feature = spatial.get_feature(LAYER_ID, "SMOKE-A01")
            if project is None or stored_layer is None or feature is None:
                raise RuntimeError("项目、图层或空间要素写入后无法读取")
            if stored_layer.data_hash != layer.data_hash:
                raise RuntimeError("空间图层哈希回读不一致")

            written = poi.upsert_many(normalized_pois())
            stored_poi = poi.get(POI_SOURCE, "poi-001")
            nearby = poi.search_nearby(
                longitude=121.4705,
                latitude=31.2305,
                radius_m=100,
                categories=["公交站"],
            )
            if written != 1 or stored_poi is None or stored_poi.name != "更新名称":
                raise RuntimeError("POI 去重写入或读取结果不一致")
            if len(nearby) != 1:
                raise RuntimeError("POI 参数化半径查询结果不一致")

            connection.execute(
                text("DELETE FROM site_selection.pois WHERE source = :source"),
                {"source": POI_SOURCE},
            )
            connection.execute(
                text(
                    "DELETE FROM site_selection.projects "
                    "WHERE project_id = :project_id"
                ),
                {"project_id": PROJECT_ID},
            )
    finally:
        engine.dispose()

    print(
        "Storage smoke OK: "
        f"project={PROJECT_ID}, layer_hash={layer.data_hash[:12]}, "
        "features=1, pois=1, deduplicated=true"
    )


def main() -> int:
    try:
        run_smoke()
    except Exception as exc:
        print(f"Storage smoke FAILED: error_type={type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
