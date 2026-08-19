from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import sleep
from typing import Any

import pytest
from pydantic import ValidationError

from practice.llm_api.tool_registry import ToolTimeoutError
from practice.site_selection.mcp_server import create_site_selection_mcp_server
from practice.site_selection.mcp_tools import create_site_selection_tool_registry
from practice.site_selection.spatial.query_engine import SpatialQueryMetrics
from practice.site_selection.storage.poi_repository import NearbyPOI


NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


class FakeSpatialBackend:
    def __init__(self, *, delay_seconds: float = 0) -> None:
        self.delay_seconds = delay_seconds

    def analyze(self, **_: Any) -> SpatialQueryMetrics:
        if self.delay_seconds:
            sleep(self.delay_seconds)
        return SpatialQueryMetrics(
            analysis_crs="EPSG:32651",
            area_hectares=1,
            intersecting_feature_count=2,
            nearest_feature_distance_m=25,
        )


class FakePOIReader:
    def search_nearby(self, **_: Any) -> list[NearbyPOI]:
        return [nearby_poi("P1", 100), nearby_poi("P2", 600)]


class FakeMCP:
    def __init__(self, name: str) -> None:
        self.name = name
        self.tools: dict[str, Any] = {}
        self.descriptions: dict[str, str] = {}

    def tool(self, *, name: str, description: str):
        def register(function: Any) -> Any:
            self.tools[name] = function
            self.descriptions[name] = description
            return function

        return register


def nearby_poi(source_id: str, distance_m: float) -> NearbyPOI:
    return NearbyPOI(
        poi_id=1 if source_id == "P1" else 2,
        source="fixture",
        source_id=source_id,
        name=source_id,
        category="公交站",
        longitude=121.47,
        latitude=31.23,
        source_crs="WGS84",
        fetched_at=NOW,
        distance_m=distance_m,
        created_at=NOW,
        updated_at=NOW,
    )


def registry(*, timeout_seconds: float = 1):
    return create_site_selection_tool_registry(
        FakeSpatialBackend(),
        FakePOIReader(),
        timeout_seconds=timeout_seconds,
    )


def test_registry_exposes_exactly_five_reviewed_tools() -> None:
    assert registry().names == (
        "gis_feature_area",
        "gis_intersection_count",
        "gis_nearest_distance",
        "poi_nearby",
        "poi_metrics",
    )


def test_spatial_and_poi_tools_return_structured_results() -> None:
    tools = registry()

    area = tools.execute(
        "gis_feature_area",
        {"layer_id": "candidate", "source_feature_id": "A01"},
    )
    intersections = tools.execute(
        "gis_intersection_count",
        {
            "layer_id": "candidate",
            "source_feature_id": "A01",
            "context_layer_id": "constraints",
        },
    )
    nearest = tools.execute(
        "gis_nearest_distance",
        {
            "layer_id": "candidate",
            "source_feature_id": "A01",
            "context_layer_id": "constraints",
        },
    )
    nearby = tools.execute(
        "poi_nearby",
        {"longitude": 121.47, "latitude": 31.23, "radius_m": 1_000},
    )
    metrics = tools.execute(
        "poi_metrics",
        {
            "longitude": 121.47,
            "latitude": 31.23,
            "radius_m": 1_000,
            "distance_bands_m": [500, 1_000],
        },
    )

    assert area["area_hectares"] == 1
    assert intersections["intersecting_feature_count"] == 2
    assert nearest["nearest_feature_distance_m"] == 25
    assert nearby["record_count"] == 2
    assert [band["count"] for band in metrics["distance_bands"]] == [1, 2]


@pytest.mark.parametrize(
    "overrides",
    [
        {"radius_m": 50, "unexpected": True},
        {"radius_m": 1_000, "categories": []},
    ],
)
def test_invalid_arguments_are_rejected_before_handler_execution(
    overrides: dict[str, Any],
) -> None:
    arguments = {
        "longitude": 121.47,
        "latitude": 31.23,
        **overrides,
    }
    with pytest.raises(ValidationError):
        registry().execute("poi_nearby", arguments)


def test_tool_timeout_is_mapped_by_the_shared_registry() -> None:
    tools = create_site_selection_tool_registry(
        FakeSpatialBackend(delay_seconds=0.05),
        FakePOIReader(),
        timeout_seconds=0.01,
    )

    with pytest.raises(ToolTimeoutError, match="gis_feature_area"):
        tools.execute(
            "gis_feature_area",
            {"layer_id": "candidate", "source_feature_id": "A01"},
        )


def test_mcp_server_registers_typed_wrappers_for_all_tools() -> None:
    server = create_site_selection_mcp_server(
        registry(),
        fastmcp_factory=FakeMCP,
    )

    assert set(server.tools) == set(registry().names)
    result = server.tools["gis_feature_area"]("candidate", "A01")
    assert result["analysis_crs"] == "EPSG:32651"
    assert all(server.descriptions.values())


def test_real_mcp_sdk_lists_and_calls_registered_tool() -> None:
    from mcp import Client

    async def scenario() -> None:
        server = create_site_selection_mcp_server(registry())
        async with Client(server) as client:
            listed = await client.list_tools()
            assert {tool.name for tool in listed.tools} == set(registry().names)

            result = await client.call_tool(
                "gis_feature_area",
                {"layer_id": "candidate", "source_feature_id": "A01"},
            )
            assert result.structured_content == {
                "layer_id": "candidate",
                "source_feature_id": "A01",
                "analysis_crs": "EPSG:32651",
                "area_hectares": 1.0,
            }

    asyncio.run(scenario())
