from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, text

from practice.site_selection import DatasetManifest, DatasetSource
from practice.site_selection.spatial import (
    PostGISSpatialDatasetGateway,
    validate_spatial_dataset,
)


TABLE_NAME = "codex_site_selection_gateway_smoke"


def required_environment(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"缺少环境变量：{name}")
    return value


def build_host_database_url() -> URL:
    try:
        port = int(os.getenv("POSTGRES_PORT", "5432"))
    except ValueError as exc:
        raise RuntimeError("POSTGRES_PORT 必须是整数") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("POSTGRES_PORT 超出有效范围")

    return URL.create(
        drivername="postgresql+psycopg",
        username=os.getenv("POSTGRES_USER", "agent"),
        password=required_environment("POSTGRES_PASSWORD"),
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=port,
        database=os.getenv("POSTGRES_DB", "site_selection"),
    )


def run_smoke() -> None:
    load_dotenv()
    engine = create_engine(
        build_host_database_url(),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.begin() as connection:
            connection.execute(text("SELECT PostGIS_Version()"))
            connection.execute(
                text(
                    f"""
                    CREATE TEMP TABLE {TABLE_NAME} (
                        parcel_id text PRIMARY KEY,
                        land_use text NOT NULL,
                        geometry geometry(Polygon, 32651) NOT NULL
                    ) ON COMMIT DROP
                    """
                )
            )
            connection.execute(
                text(
                    f"""
                    INSERT INTO {TABLE_NAME} (
                        parcel_id,
                        land_use,
                        geometry
                    ) VALUES (
                        :parcel_id,
                        :land_use,
                        ST_GeomFromText(:wkt, 32651)
                    )
                    """
                ),
                {
                    "parcel_id": "A01",
                    "land_use": "fixture-commercial",
                    "wkt": (
                        "POLYGON((300000 3450000, 300100 3450000, "
                        "300100 3450100, 300000 3450000))"
                    ),
                },
            )

            manifest = DatasetManifest(
                dataset_id="postgis-smoke-parcels",
                name="PostGIS smoke 临时地块",
                source=DatasetSource.POSTGIS,
                location=f"pg_temp.{TABLE_NAME}",
                version="smoke-1",
                crs="EPSG:32651",
                required_fields=["parcel_id", "land_use"],
                updated_at=datetime.now(timezone.utc),
            )
            gateway = PostGISSpatialDatasetGateway(
                connection,
                allowed_schemas=["pg_temp"],
                default_schema="pg_temp",
            )
            frame = gateway.load(manifest)
            validation = validate_spatial_dataset(
                frame,
                required_fields=manifest.required_fields,
                expected_crs=manifest.crs,
            )
            if frame["parcel_id"].tolist() != ["A01"]:
                raise RuntimeError("PostGIS smoke 返回了意外地块")
    finally:
        engine.dispose()

    print(
        "PostGIS smoke OK: "
        f"rows={validation.feature_count}, "
        f"crs={validation.crs}, "
        f"geometry={','.join(validation.geometry_types)}"
    )


def main() -> int:
    try:
        run_smoke()
    except Exception as exc:
        print(f"PostGIS smoke FAILED: error_type={type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
