from __future__ import annotations

import sys
from datetime import datetime, timezone
from math import isclose
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import geopandas as gpd
from shapely.geometry import Point, Polygon
from sqlalchemy import create_engine, text

from practice.site_selection import DatasetSource, ProjectType
from practice.site_selection.spatial.query_engine import (
    GeoPandasSpatialQueryEngine,
    PostGISSpatialQueryEngine,
)
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


PROJECT_ID = "spatial-parity-smoke-project"
CANDIDATE_LAYER_ID = "spatial-parity-candidate"
OVERLAY_LAYER_ID = "spatial-parity-overlay"
DISTANCE_LAYER_ID = "spatial-parity-distance"
ANALYSIS_SRID = 32651
NOW = datetime.now(timezone.utc)


def candidate_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"parcel_id": ["A01"], "land_use": ["fixture-commercial"]},
        geometry=[
            Polygon(
                [
                    (350_000, 3_450_000),
                    (350_100, 3_450_000),
                    (350_100, 3_450_100),
                    (350_000, 3_450_100),
                    (350_000, 3_450_000),
                ]
            )
        ],
        crs=f"EPSG:{ANALYSIS_SRID}",
    )


def overlay_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"context_id": ["inside", "outside"], "kind": ["inside", "outside"]},
        geometry=[
            Point(350_050, 3_450_050),
            Point(350_150, 3_450_050),
        ],
        crs=f"EPSG:{ANALYSIS_SRID}",
    )


def distance_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"context_id": ["nearest"], "kind": ["outside"]},
        geometry=[Point(350_150, 3_450_050)],
        crs=f"EPSG:{ANALYSIS_SRID}",
    )


def layer_write(
    layer_id: str,
    *,
    name: str,
    layer_type: str,
    required_fields: list[str],
) -> SpatialLayerWrite:
    return SpatialLayerWrite(
        layer_id=layer_id,
        project_id=PROJECT_ID,
        name=name,
        layer_type=layer_type,
        source=DatasetSource.API,
        version="smoke-1",
        required_fields=required_fields,
        updated_at=NOW,
        metadata={"fixture": True},
    )


def run_smoke() -> None:
    load_environment()
    engine = create_engine(
        build_host_database_url(),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    candidate = candidate_frame()
    overlay = overlay_frame()
    distance = distance_frame()
    memory = GeoPandasSpatialQueryEngine()
    memory_overlay = memory.analyze(candidate, context_rows=overlay)
    memory_distance = memory.analyze(candidate, context_rows=distance)

    try:
        apply_migration(engine)
        with engine.begin() as connection:
            storage = PostgresSpatialRepository(connection)
            storage.upsert_project(
                ProjectStorageRecord(
                    project_id=PROJECT_ID,
                    project_type=ProjectType.SHOPPING_MALL,
                    name="Spatial parity smoke project",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            storage.replace_layer(
                layer_write(
                    CANDIDATE_LAYER_ID,
                    name="Candidate fixture",
                    layer_type="candidate_parcel",
                    required_fields=["parcel_id", "land_use"],
                ),
                candidate,
                source_id_field="parcel_id",
            )
            storage.replace_layer(
                layer_write(
                    OVERLAY_LAYER_ID,
                    name="Overlay fixture",
                    layer_type="constraint",
                    required_fields=["context_id", "kind"],
                ),
                overlay,
                source_id_field="context_id",
            )
            storage.replace_layer(
                layer_write(
                    DISTANCE_LAYER_ID,
                    name="Distance fixture",
                    layer_type="context",
                    required_fields=["context_id", "kind"],
                ),
                distance,
                source_id_field="context_id",
            )

            database = PostGISSpatialQueryEngine(connection)
            database_overlay = database.analyze(
                layer_id=CANDIDATE_LAYER_ID,
                source_feature_id="A01",
                analysis_srid=ANALYSIS_SRID,
                context_layer_id=OVERLAY_LAYER_ID,
            )
            database_distance = database.analyze(
                layer_id=CANDIDATE_LAYER_ID,
                source_feature_id="A01",
                analysis_srid=ANALYSIS_SRID,
                context_layer_id=DISTANCE_LAYER_ID,
            )
            if database_overlay is None or database_distance is None:
                raise RuntimeError("PostGIS 未返回候选地块空间指标")

            if not isclose(
                database_overlay.area_hectares,
                memory_overlay.area_hectares,
                rel_tol=1e-5,
                abs_tol=1e-5,
            ):
                raise RuntimeError("GeoPandas 与 PostGIS 面积结果不一致")
            if (
                database_overlay.intersecting_feature_count
                != memory_overlay.intersecting_feature_count
            ):
                raise RuntimeError("GeoPandas 与 PostGIS 相交数量不一致")
            database_nearest = database_distance.nearest_feature_distance_m
            memory_nearest = memory_distance.nearest_feature_distance_m
            if (
                database_nearest is None
                or memory_nearest is None
                or not isclose(
                    database_nearest,
                    memory_nearest,
                    rel_tol=1e-5,
                    abs_tol=0.01,
                )
            ):
                raise RuntimeError("GeoPandas 与 PostGIS 最近距离不一致")

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
        "Spatial parity smoke OK: "
        f"area={memory_overlay.area_hectares:.6f}ha, "
        f"intersections={memory_overlay.intersecting_feature_count}, "
        f"nearest={memory_distance.nearest_feature_distance_m:.3f}m"
    )


def main() -> int:
    try:
        run_smoke()
    except Exception as exc:
        print(f"Spatial parity smoke FAILED: error_type={type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
