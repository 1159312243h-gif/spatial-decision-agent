from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import geopandas as gpd
from pyproj import CRS
from sqlalchemy import create_engine

from practice.site_selection import DatasetSource
from practice.site_selection.storage.postgres import (
    PostgresSpatialRepository,
    SpatialLayerWrite,
)
from scripts.apply_postgis_migrations import (
    apply_migration,
    build_host_database_url,
    load_environment,
)


SUITABILITY_VALUES = frozenset({"allowed", "review_required", "excluded"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import a reviewed authoritative land-use layer into PostGIS.",
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--layer-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-uri", required=True)
    parser.add_argument("--license", required=True)
    parser.add_argument("--analysis-crs", required=True)
    parser.add_argument("--id-field", default="parcel_id")
    parser.add_argument("--name-field", default="name")
    parser.add_argument("--land-use-field", default="land_use_class")
    parser.add_argument("--suitability-field", default="suitability")
    parser.add_argument("--area-field", default="area_hectares")
    return parser.parse_args()


def standardized_frame(args: argparse.Namespace) -> gpd.GeoDataFrame:
    source_path = args.path.resolve()
    if not source_path.is_file():
        raise RuntimeError(f"用地文件不存在：{source_path}")
    frame = gpd.read_file(source_path)
    if frame.empty:
        raise RuntimeError("权威用地图层不能为空")
    if frame.crs is None:
        raise RuntimeError("权威用地图层必须声明 CRS")
    field_map = {
        args.id_field: "parcel_id",
        args.name_field: "name",
        args.land_use_field: "land_use_class",
        args.suitability_field: "suitability",
    }
    missing = sorted(set(field_map) - set(frame.columns))
    if missing:
        raise RuntimeError("权威用地图层缺少源字段：" + ", ".join(missing))
    standardized = frame.rename(columns=field_map).copy()
    for field in ("parcel_id", "name", "land_use_class", "suitability"):
        standardized[field] = standardized[field].astype(str).str.strip()
        if (standardized[field] == "").any():
            raise RuntimeError(f"权威用地图层字段不能为空：{field}")
    invalid = sorted(set(standardized["suitability"]) - SUITABILITY_VALUES)
    if invalid:
        raise RuntimeError(
            "suitability 只能是 allowed、review_required 或 excluded："
            + ", ".join(invalid)
        )
    if standardized["parcel_id"].duplicated().any():
        raise RuntimeError("权威用地图层 parcel_id 不能重复")

    analysis_crs = CRS.from_user_input(args.analysis_crs)
    if analysis_crs.is_geographic:
        raise RuntimeError("analysis_crs 必须是米制投影 CRS")
    projected = standardized.to_crs(analysis_crs)
    if args.area_field in standardized.columns:
        standardized["area_hectares"] = standardized[args.area_field].astype(float)
    else:
        standardized["area_hectares"] = projected.geometry.area / 10_000
    if (standardized["area_hectares"] <= 0).any():
        raise RuntimeError("权威用地图层面积必须大于 0")
    return standardized[
        [
            "parcel_id",
            "name",
            "land_use_class",
            "suitability",
            "area_hectares",
            standardized.geometry.name,
        ]
    ]


def main() -> int:
    args = parse_args()
    load_environment()
    frame = standardized_frame(args)
    engine = create_engine(build_host_database_url(), pool_pre_ping=True)
    try:
        apply_migration(engine)
        with engine.begin() as connection:
            stored = PostgresSpatialRepository(connection).replace_layer(
                SpatialLayerWrite(
                    layer_id=args.layer_id,
                    name=args.name,
                    layer_type="authoritative_land_use",
                    source=DatasetSource.FILE,
                    version=args.version,
                    required_fields=[
                        "parcel_id",
                        "name",
                        "land_use_class",
                        "suitability",
                        "area_hectares",
                    ],
                    updated_at=datetime.now(timezone.utc),
                    metadata={
                        "evidence_level": "authoritative",
                        "is_fixture": False,
                        "source_uri": args.source_uri,
                        "license": args.license,
                        "analysis_crs": args.analysis_crs,
                        "source_path": str(args.path.resolve()),
                    },
                ),
                frame,
                source_id_field="parcel_id",
            )
        print(
            "imported "
            f"layer_id={stored.layer_id} features={len(frame)} "
            f"version={stored.version} hash={stored.data_hash}"
        )
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
