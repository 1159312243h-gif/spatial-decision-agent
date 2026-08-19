from __future__ import annotations

from collections.abc import Callable
from typing import Any

from practice.llm_api.tool_registry import ToolRegistry


MCPServerFactory = Callable[[str], Any]


def create_site_selection_mcp_server(
    registry: ToolRegistry,
    *,
    fastmcp_factory: MCPServerFactory | None = None,
) -> Any:
    """Expose the reviewed tool registry through an MCP stdio server."""

    if fastmcp_factory is None:
        try:
            from mcp.server import MCPServer
        except ImportError as exc:
            raise RuntimeError(
                "缺少 MCP SDK，请先安装 requirements.txt"
            ) from exc
        fastmcp_factory = MCPServer

    server = fastmcp_factory("site-selection")

    def gis_feature_area(
        layer_id: str,
        source_feature_id: str,
        analysis_srid: int = 32651,
    ) -> dict[str, Any]:
        return registry.execute(
            "gis_feature_area",
            {
                "layer_id": layer_id,
                "source_feature_id": source_feature_id,
                "analysis_srid": analysis_srid,
            },
        )

    def gis_intersection_count(
        layer_id: str,
        source_feature_id: str,
        context_layer_id: str,
        analysis_srid: int = 32651,
    ) -> dict[str, Any]:
        return registry.execute(
            "gis_intersection_count",
            {
                "layer_id": layer_id,
                "source_feature_id": source_feature_id,
                "context_layer_id": context_layer_id,
                "analysis_srid": analysis_srid,
            },
        )

    def gis_nearest_distance(
        layer_id: str,
        source_feature_id: str,
        context_layer_id: str,
        analysis_srid: int = 32651,
    ) -> dict[str, Any]:
        return registry.execute(
            "gis_nearest_distance",
            {
                "layer_id": layer_id,
                "source_feature_id": source_feature_id,
                "context_layer_id": context_layer_id,
                "analysis_srid": analysis_srid,
            },
        )

    def poi_nearby(
        longitude: float,
        latitude: float,
        radius_m: int,
        categories: list[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return registry.execute(
            "poi_nearby",
            {
                "longitude": longitude,
                "latitude": latitude,
                "radius_m": radius_m,
                "categories": categories,
                "limit": limit,
            },
        )

    def poi_metrics(
        longitude: float,
        latitude: float,
        radius_m: int,
        distance_bands_m: list[int],
        categories: list[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return registry.execute(
            "poi_metrics",
            {
                "longitude": longitude,
                "latitude": latitude,
                "radius_m": radius_m,
                "distance_bands_m": distance_bands_m,
                "categories": categories,
                "limit": limit,
            },
        )

    def policy_search(
        query: str,
        project_type: str,
        jurisdiction: str | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        return registry.execute(
            "policy_search",
            {
                "query": query,
                "project_type": project_type,
                "jurisdiction": jurisdiction,
                "top_k": top_k,
            },
        )

    functions = {
        "gis_feature_area": gis_feature_area,
        "gis_intersection_count": gis_intersection_count,
        "gis_nearest_distance": gis_nearest_distance,
        "poi_nearby": poi_nearby,
        "poi_metrics": poi_metrics,
    }
    if "policy_search" in registry.names:
        functions["policy_search"] = policy_search
    for name, function in functions.items():
        definition = registry.get(name)
        server.tool(
            name=name,
            description=definition.description,
        )(function)
    return server
