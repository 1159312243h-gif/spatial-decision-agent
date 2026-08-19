from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import Engine, create_engine

from practice.site_selection.mcp_server import create_site_selection_mcp_server
from practice.site_selection.mcp_tools import create_site_selection_tool_registry
from practice.site_selection.spatial.query_engine import (
    PostGISSpatialQueryEngine,
    SpatialQueryMetrics,
)
from practice.site_selection.storage.poi_repository import (
    NearbyPOI,
    PostgresPOIRepository,
)
from scripts.apply_postgis_migrations import (
    build_host_database_url,
    load_environment,
)


class EngineSpatialQueryBackend:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def analyze(
        self,
        *,
        layer_id: str,
        source_feature_id: str,
        analysis_srid: int,
        context_layer_id: str | None = None,
    ) -> SpatialQueryMetrics | None:
        with self._engine.connect() as connection:
            return PostGISSpatialQueryEngine(connection).analyze(
                layer_id=layer_id,
                source_feature_id=source_feature_id,
                analysis_srid=analysis_srid,
                context_layer_id=context_layer_id,
            )


class EnginePOIReader:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def search_nearby(
        self,
        *,
        longitude: float,
        latitude: float,
        radius_m: float,
        categories: list[str] | None = None,
        limit: int = 100,
    ) -> list[NearbyPOI]:
        with self._engine.connect() as connection:
            return PostgresPOIRepository(connection).search_nearby(
                longitude=longitude,
                latitude=latitude,
                radius_m=radius_m,
                categories=categories,
                limit=limit,
            )


def main() -> int:
    load_environment()
    engine = create_engine(
        build_host_database_url(),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    registry = create_site_selection_tool_registry(
        EngineSpatialQueryBackend(engine),
        EnginePOIReader(engine),
    )
    server = create_site_selection_mcp_server(registry)
    try:
        server.run()
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
