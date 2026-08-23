from pathlib import Path

import geopandas as gpd
from fastapi.testclient import TestClient
from shapely.geometry import shape

from app.main import create_app
from app.site_selection_bootstrap import (
    build_fixture_runtime_registry,
    load_fixture_spatial_seed,
)
from practice.site_selection.spatial import MockSpatialDatasetGateway


FIXTURE_ROOT = Path(__file__).parents[1] / "data" / "fixtures"


def payload(project_type: str = "coffee_shop") -> dict:
    return {
        "request_id": "api-discovery-001",
        "project_type": project_type,
        "bounds": {
            "west": 121.29,
            "south": 31.14,
            "east": 121.37,
            "north": 31.19,
        },
        "max_candidates": 6,
        "minimum_separation_m": 600,
    }


def configured_client() -> TestClient:
    seed = load_fixture_spatial_seed(FIXTURE_ROOT / "spatial_layers.json")
    frames = {
        layer.layer_id: gpd.GeoDataFrame(
            [feature.properties for feature in layer.features],
            geometry=[shape(feature.geometry) for feature in layer.features],
            crs=seed.crs,
        )
        for layer in seed.layers
    }
    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=MockSpatialDatasetGateway(frames),
    )
    return TestClient(create_app(registry))


def test_candidate_discovery_api_returns_analysis_ready_candidates() -> None:
    response = configured_client().post(
        "/site-selection/candidates/discover", json=payload()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["confirmation_required"] is True
    assert body["strategy"] == "registered_land"
    assert body["formal_analysis_allowed"] is True
    assert body["range_poi_observed_count"] == len(body["range_pois"])
    assert body["range_pois"]
    assert {item["purpose"] for item in body["sources"]} == {
        "scoring",
        "range_context",
    }
    assert len(body["candidates"]) == 6
    assert all(
        item["candidate"]["geometry_dataset_id"]
        == "demo-coffee-discovery-pool"
        for item in body["candidates"]
    )


def test_candidate_discovery_api_maps_unconfigured_and_invalid_requests() -> None:
    unavailable = TestClient(create_app()).post(
        "/site-selection/candidates/discover", json=payload()
    )
    unsupported = configured_client().post(
        "/site-selection/candidates/discover",
        json=payload("shopping_mall"),
    )

    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "runtime_unavailable"
    assert unsupported.status_code == 422
