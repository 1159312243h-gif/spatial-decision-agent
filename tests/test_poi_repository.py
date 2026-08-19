from datetime import datetime, timezone

import pytest

from practice.site_selection.poi_normalizer import NormalizedPOI
from practice.site_selection.storage.poi_repository import PostgresPOIRepository
from tests.storage_fakes import FakeConnection, FakeResult


NOW = datetime(2026, 8, 19, 16, 0, tzinfo=timezone.utc)


def normalized_poi(**updates: object) -> NormalizedPOI:
    payload = {
        "source": "fixture",
        "source_id": "poi-001",
        "name": "测试站点",
        "category": "公交站",
        "longitude": 121.47,
        "latitude": 31.23,
        "source_crs": "WGS84",
        "address": "测试路 1 号",
        "fetched_at": NOW,
        "raw_payload": {"fixture": True},
    }
    payload.update(updates)
    return NormalizedPOI.model_validate(payload)


def stored_row(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "poi_id": 1,
        **normalized_poi().model_dump(),
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(updates)
    return payload


def test_duplicate_source_identity_is_collapsed_before_upsert() -> None:
    connection = FakeConnection()
    repository = PostgresPOIRepository(connection)

    count = repository.upsert_many(
        [normalized_poi(name="旧名称"), normalized_poi(name="新名称")]
    )

    assert count == 1
    sql, parameters = connection.calls[0]
    assert "ON CONFLICT (source, source_id)" in sql
    assert len(parameters) == 1
    assert parameters[0]["name"] == "新名称"
    assert "poi-001" not in sql


def test_poi_can_be_read_by_source_identity() -> None:
    connection = FakeConnection([FakeResult([stored_row()])])

    result = PostgresPOIRepository(connection).get(" FIXTURE ", "poi-001")

    assert result is not None
    assert result.source == "fixture"
    assert result.poi_id == 1
    assert connection.calls[0][1] == {
        "source": "fixture",
        "source_id": "poi-001",
    }


def test_nearby_query_is_parameterized_and_returns_distance() -> None:
    connection = FakeConnection(
        [FakeResult([stored_row(distance_m=125.5)])]
    )

    results = PostgresPOIRepository(connection).search_nearby(
        longitude=121.47,
        latitude=31.23,
        radius_m=1_000,
        categories=["公交站"],
        limit=20,
    )

    sql, parameters = connection.calls[0]
    assert "ST_DWithin" in sql
    assert "ANY(:categories)" in sql
    assert "公交站" not in sql
    assert parameters["categories"] == ["公交站"]
    assert results[0].distance_m == 125.5


def test_nearby_query_rejects_invalid_radius_and_limit() -> None:
    repository = PostgresPOIRepository(FakeConnection())
    with pytest.raises(ValueError, match="半径"):
        repository.search_nearby(
            longitude=121.47,
            latitude=31.23,
            radius_m=0,
        )
    with pytest.raises(ValueError, match="数量限制"):
        repository.search_nearby(
            longitude=121.47,
            latitude=31.23,
            radius_m=100,
            limit=0,
        )
