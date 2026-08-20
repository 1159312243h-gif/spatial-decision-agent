from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from practice.site_selection import (
    FixturePOIAdapter,
    FixturePOIDataset,
    POIMetric,
    POIProvider,
    POIQuery,
    ProjectType,
    get_project_profile,
)


NOW = datetime(2026, 8, 18, 13, 0, tzinfo=timezone.utc)
FIXTURE_PATH = (
    Path(__file__).parents[1] / "data" / "fixtures" / "poi.json"
)


def query(
    *,
    categories: list[str] | None = None,
    radius_m: int = 5_000,
    limit: int = 100,
) -> POIQuery:
    return POIQuery(
        query_id="Q-fixture",
        parcel_id="A01",
        group_key="fixture-group",
        longitude=121.47,
        latitude=31.23,
        categories=categories or ["地铁站"],
        radius_m=radius_m,
        limit=limit,
    )


def adapter() -> FixturePOIAdapter:
    return FixturePOIAdapter.from_json(FIXTURE_PATH, clock=lambda: NOW)


def test_fixture_has_minimum_records_and_covers_both_profiles() -> None:
    dataset = adapter().dataset
    fixture_categories = {record.category for record in dataset.records}
    required_categories = {
        category
        for project_type in ProjectType
        for group in get_project_profile(project_type).poi_groups
        for category in group.categories
    }

    assert len(dataset.records) == 1_157
    assert required_categories <= fixture_categories
    assert dataset.is_synthetic is True
    assert dataset.generation_method == "deterministic-radial-v1"
    assert "不代表真实城市覆盖率" in dataset.quality_notice


def test_search_filters_category_and_radius_and_sorts_by_distance() -> None:
    result = adapter().search(
        query(categories=["地铁站", "公交站"], radius_m=1_500)
    )

    assert result.records
    assert {record.category for record in result.records} <= {
        "地铁站",
        "公交站",
    }
    assert all(record.distance_m <= 1_500 for record in result.records)
    assert [record.distance_m for record in result.records] == sorted(
        record.distance_m for record in result.records
    )


def test_search_applies_limit_after_deterministic_distance_order() -> None:
    active_adapter = adapter()

    first = active_adapter.search(
        query(categories=["地铁站", "公交站"], limit=1)
    )
    second = active_adapter.search(
        query(categories=["地铁站", "公交站"], limit=1)
    )

    assert len(first.records) == 1
    assert first.records == second.records
    assert first.records[0].poi_id == "F0001"
    assert first.source.available_record_count > len(first.records)
    assert first.source.is_truncated is True


def test_search_returns_empty_feature_set_for_no_match() -> None:
    result = adapter().search(query(categories=["港口"], radius_m=100))

    assert result.records == []
    assert result.source.record_count == 0
    assert result.metrics[POIMetric.COUNT] == 0
    assert result.metrics[POIMetric.DENSITY_PER_SQ_KM] == 0


def test_source_metadata_preserves_fixture_lineage() -> None:
    result = adapter().search(query())

    assert result.source.provider is POIProvider.MOCK
    assert result.source.dataset_id == "poi-fixture-synthetic-multicandidate"
    assert result.source.dataset_version == "fixture-rich-v1"
    assert result.source.dataset_updated_at == datetime(
        2026, 8, 20, 0, 0, tzinfo=timezone.utc
    )
    assert result.source.queried_at == NOW
    assert result.source.crs == "EPSG:4326"
    assert result.source.record_count == len(result.records)
    assert result.source.dataset_record_count == 1_157
    assert result.source.is_synthetic is True
    assert "不代表真实城市覆盖率" in result.source.quality_notice


def test_search_result_and_dataset_property_are_defensive_copies() -> None:
    active_adapter = adapter()
    original_query = query()

    result = active_adapter.search(original_query)
    result.query.categories.append("公交站")
    result.records[0].attributes["changed"] = True
    exposed_dataset = active_adapter.dataset
    exposed_dataset.records[0].name = "changed"

    repeated = active_adapter.search(original_query)
    assert original_query.categories == ["地铁站"]
    assert repeated.query.categories == ["地铁站"]
    assert "changed" not in repeated.records[0].attributes
    assert active_adapter.dataset.records[0].name != "changed"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("provider", "amap", "mock provider"),
        ("crs", "EPSG:3857", "EPSG:4326"),
        ("updated_at", NOW.replace(tzinfo=None), "时区"),
    ],
)
def test_fixture_rejects_unsupported_source_contract(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = adapter().dataset.model_dump()
    payload[field] = value

    with pytest.raises(ValidationError, match=message):
        FixturePOIDataset.model_validate(payload)


def test_adapter_rejects_naive_query_clock() -> None:
    active_adapter = FixturePOIAdapter(
        adapter().dataset,
        clock=lambda: NOW.replace(tzinfo=None),
    )

    with pytest.raises(ValidationError, match="时区"):
        active_adapter.search(query())
