from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError
from shapely.geometry import shape

from app.site_selection_bootstrap import load_fixture_spatial_seed
from practice.site_selection import ProjectType, load_fixture_candidate_catalog
from scripts.generate_rich_fixtures import (
    build_candidate_catalog,
    build_poi_dataset,
    build_spatial_seed,
)


FIXTURE_ROOT = Path(__file__).parents[1] / "data" / "fixtures"


def test_generated_fixture_files_match_deterministic_builders() -> None:
    expected = {
        "candidates.json": build_candidate_catalog(),
        "poi.json": build_poi_dataset(),
        "spatial_layers.json": build_spatial_seed(),
    }

    for filename, payload in expected.items():
        actual = json.loads((FIXTURE_ROOT / filename).read_text(encoding="utf-8"))
        assert actual == payload


def test_candidate_catalog_has_six_distinct_scenarios_per_project() -> None:
    catalog = load_fixture_candidate_catalog(FIXTURE_ROOT / "candidates.json")

    assert catalog.is_fixture is True
    assert set(catalog.project_candidates) == set(ProjectType)
    for project_type, candidates in catalog.project_candidates.items():
        assert len(candidates) == 6
        assert len({item.scenario_profile for item in candidates}) == 6
        payload = catalog.payload_for(project_type)
        assert len(payload["candidate_parcels"]) == 6
        assert all(
            "scenario_profile" not in item
            for item in payload["candidate_parcels"]
        )


def test_candidate_catalog_derives_explicit_retail_demo_discovery_bounds() -> None:
    catalog = load_fixture_candidate_catalog(FIXTURE_ROOT / "candidates.json")

    assert catalog.demo_discovery_bounds_for(ProjectType.COFFEE_SHOP) == {
        "west": pytest.approx(121.295),
        "south": pytest.approx(31.145),
        "east": pytest.approx(121.365),
        "north": pytest.approx(31.185),
    }
    assert catalog.demo_discovery_bounds_for(
        ProjectType.CONVENIENCE_STORE
    ) == {
        "west": pytest.approx(121.295),
        "south": pytest.approx(31.315),
        "east": pytest.approx(121.365),
        "north": pytest.approx(31.355),
    }
    with pytest.raises(ValueError, match="仅支持零售项目"):
        catalog.demo_discovery_bounds_for(ProjectType.SHOPPING_MALL)
    with pytest.raises(ValueError, match="边距必须大于 0"):
        catalog.demo_discovery_bounds_for(
            ProjectType.COFFEE_SHOP,
            padding_degrees=0,
        )


def test_rich_poi_fixture_has_broad_category_and_scenario_coverage() -> None:
    payload = build_poi_dataset()
    records = payload["records"]
    categories = Counter(item["category"] for item in records)

    assert len(records) == 1_157
    assert len(categories) == 30
    assert min(categories.values()) >= 2
    assert {item["attributes"]["candidate_id"] for item in records} == {
        f"MALL-A{index:02d}" for index in range(1, 7)
    } | {f"LOG-A{index:02d}" for index in range(1, 7)} | {
        f"COF-A{index:02d}" for index in range(1, 7)
    } | {f"CVS-A{index:02d}" for index in range(1, 7)}
    assert all(item["attributes"]["synthetic"] is True for item in records)


def test_spatial_seed_matches_catalog_and_preserves_declared_areas() -> None:
    catalog = load_fixture_candidate_catalog(FIXTURE_ROOT / "candidates.json")
    seed = load_fixture_spatial_seed(FIXTURE_ROOT / "spatial_layers.json")
    layers = {layer.layer_id: layer for layer in seed.layers}

    for project_type, layer_id in (
        (ProjectType.SHOPPING_MALL, "demo-mall-candidates"),
        (ProjectType.LOGISTICS_PARK, "demo-logistics-candidates"),
        (ProjectType.COFFEE_SHOP, "demo-coffee-candidates"),
        (ProjectType.CONVENIENCE_STORE, "demo-convenience-candidates"),
    ):
        candidates = catalog.project_candidates[project_type]
        features = layers[layer_id].features
        assert {item.parcel_id for item in candidates} == {
            item.source_feature_id for item in features
        }
        declared = {item.parcel_id: item.area_hectares for item in candidates}
        for feature in features:
            area_hectares = shape(feature.geometry).area / 10_000
            assert area_hectares == pytest.approx(
                declared[feature.source_feature_id],
                rel=1e-5,
            )

    assert len(layers["demo-mall-constraints"].features) == 2
    assert len(layers["demo-logistics-constraints"].features) == 2
    assert len(layers["demo-coffee-constraints"].features) == 1
    assert len(layers["demo-convenience-constraints"].features) == 1
    for layer_id in (
        "demo-coffee-discovery-pool",
        "demo-convenience-discovery-pool",
    ):
        features = layers[layer_id].features
        assert len(features) == 25
        assert {
            item.properties["suitability"] for item in features
        } == {"allowed", "review_required", "excluded"}
        assert all(
            item.properties["land_use_class"] for item in features
        )


def test_catalog_rejects_too_few_candidates() -> None:
    payload = build_candidate_catalog()
    payload["project_candidates"]["shopping_mall"] = payload[
        "project_candidates"
    ]["shopping_mall"][:2]

    with pytest.raises(ValidationError, match="至少需要 5 个候选"):
        load_fixture_candidate_catalog_from_payload(payload)


def load_fixture_candidate_catalog_from_payload(payload):
    from practice.site_selection.fixture_catalog import FixtureCandidateCatalog

    return FixtureCandidateCatalog.model_validate(payload)
