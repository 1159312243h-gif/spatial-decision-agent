from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pytest

from practice.site_selection import (
    FixturePOIAdapter,
    POIProvider,
    POIQuery,
)
from practice.site_selection.online_poi_adapters import (
    AmapPOIAdapter,
    FallbackPOIAdapter,
    FixedIntervalRateLimiter,
    GCJ02CoordinateTransformer,
    OverpassPOIAdapter,
    OverpassTagFilter,
    POIRateLimitError,
    POIResponseError,
    POICircuitOpenError,
    RetryingCircuitBreakerPOIAdapter,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
FIXTURE_PATH = Path(__file__).parents[1] / "data" / "fixtures" / "poi.json"


class FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeHTTPClient:
    def __init__(self, responses) -> None:
        self.responses = deque(responses)
        self.get_calls = []
        self.post_calls = []

    def get(self, url, *, params, timeout):
        self.get_calls.append((url, params, timeout))
        return self.responses.popleft()

    def post(self, url, *, data, timeout):
        self.post_calls.append((url, data, timeout))
        return self.responses.popleft()


class OffsetTransformer:
    def wgs84_to_gcj02(self, longitude, latitude):
        return longitude + 0.01, latitude + 0.01

    def gcj02_to_wgs84(self, longitude, latitude):
        return longitude - 0.01, latitude - 0.01


class RecordingLimiter:
    def __init__(self) -> None:
        self.calls = 0

    def acquire(self) -> None:
        self.calls += 1


def query(
    *,
    categories: list[str] | None = None,
    limit: int = 3,
    radius_m: int = 2_000,
) -> POIQuery:
    return POIQuery(
        query_id="online-query",
        parcel_id="A01",
        group_key="transit",
        longitude=121.47,
        latitude=31.23,
        categories=categories or ["地铁站"],
        radius_m=radius_m,
        limit=limit,
    )


def amap_payload(items) -> dict:
    return {"status": "1", "infocode": "10000", "pois": items}


def amap_item(index: int, longitude: float) -> dict:
    return {
        "id": f"A{index}",
        "name": f"测试地铁站{index}",
        "location": f"{longitude:.6f},31.240000",
        "type": "交通设施服务;地铁站",
        "typecode": "150500",
        "address": "测试地址",
    }


def test_amap_paginates_rate_limits_and_converts_gcj02() -> None:
    client = FakeHTTPClient(
        [
            FakeResponse(
                200,
                amap_payload([amap_item(1, 121.481), amap_item(2, 121.482)]),
            ),
            FakeResponse(200, amap_payload([amap_item(3, 121.483)])),
        ]
    )
    limiter = RecordingLimiter()
    adapter = AmapPOIAdapter(
        "test-api-key",
        client,
        OffsetTransformer(),
        page_size=2,
        rate_limiter=limiter,
        clock=lambda: NOW,
    )

    result = adapter.search(query())

    assert [record.poi_id for record in result.records] == [
        "amap:A1",
        "amap:A2",
        "amap:A3",
    ]
    assert result.records[0].longitude == pytest.approx(121.471)
    assert result.records[0].attributes["source_crs"] == "GCJ-02"
    assert result.source.crs == "EPSG:4326"
    assert result.source.provider is POIProvider.AMAP
    assert [call[1]["page"] for call in client.get_calls] == [1, 2]
    assert client.get_calls[0][1]["location"] == "121.48000000,31.24000000"
    assert limiter.calls == 2


def test_amap_empty_result_is_valid_and_does_not_invent_records() -> None:
    adapter = AmapPOIAdapter(
        "test-api-key",
        FakeHTTPClient([FakeResponse(200, amap_payload([]))]),
        OffsetTransformer(),
        clock=lambda: NOW,
    )

    result = adapter.search(query())

    assert result.records == []
    assert result.source.record_count == 0


def test_amap_maps_http_and_business_quota_to_rate_limit() -> None:
    http_limited = AmapPOIAdapter(
        "test-api-key",
        FakeHTTPClient([FakeResponse(429, {})]),
        OffsetTransformer(),
    )
    quota_limited = AmapPOIAdapter(
        "test-api-key",
        FakeHTTPClient(
            [FakeResponse(200, {"status": "0", "infocode": "10003"})]
        ),
        OffsetTransformer(),
    )

    with pytest.raises(POIRateLimitError, match="429"):
        http_limited.search(query())
    with pytest.raises(POIRateLimitError, match="10003"):
        quota_limited.search(query())


def test_fallback_is_explicit_for_availability_error() -> None:
    primary = AmapPOIAdapter(
        "test-api-key",
        FakeHTTPClient([FakeResponse(429, {})]),
        OffsetTransformer(),
    )
    fixture = FixturePOIAdapter.from_json(FIXTURE_PATH, clock=lambda: NOW)
    adapter = FallbackPOIAdapter(primary, fixture)

    result = adapter.search(query(limit=20))

    assert result.records
    assert result.source.provider is POIProvider.MOCK
    assert result.source.fallback_from is POIProvider.AMAP
    assert result.source.fallback_reason == "POIRateLimitError"


def test_fallback_does_not_hide_malformed_payload() -> None:
    primary = AmapPOIAdapter(
        "test-api-key",
        FakeHTTPClient([FakeResponse(200, {"status": "1"})]),
        OffsetTransformer(),
    )
    fixture = FixturePOIAdapter.from_json(FIXTURE_PATH)

    with pytest.raises(POIResponseError, match="pois"):
        FallbackPOIAdapter(primary, fixture).search(query())


def test_reliable_adapter_retries_transient_rate_limit_then_succeeds() -> None:
    client = FakeHTTPClient(
        [
            FakeResponse(429, {}),
            FakeResponse(200, amap_payload([amap_item(1, 121.481)])),
        ]
    )
    sleeps = []
    primary = AmapPOIAdapter(
        "test-api-key",
        client,
        OffsetTransformer(),
        clock=lambda: NOW,
    )
    reliable = RetryingCircuitBreakerPOIAdapter(
        primary,
        max_attempts=2,
        base_backoff_seconds=0.25,
        sleep=sleeps.append,
    )

    result = reliable.search(query(limit=1))

    assert result.source.provider is POIProvider.AMAP
    assert len(client.get_calls) == 2
    assert sleeps == [0.25]
    assert reliable.circuit_open is False


def test_open_circuit_uses_explicit_fixture_fallback_without_more_http() -> None:
    client = FakeHTTPClient([FakeResponse(429, {})])
    primary = AmapPOIAdapter(
        "test-api-key",
        client,
        OffsetTransformer(),
    )
    reliable = RetryingCircuitBreakerPOIAdapter(
        primary,
        max_attempts=1,
        failure_threshold=1,
        recovery_timeout_seconds=60,
    )
    fixture = FixturePOIAdapter.from_json(FIXTURE_PATH, clock=lambda: NOW)
    adapter = FallbackPOIAdapter(reliable, fixture)

    first = adapter.search(query(limit=20))
    second = adapter.search(query(limit=20))

    assert first.source.fallback_reason == "POIRateLimitError"
    assert second.source.fallback_reason == "POICircuitOpenError"
    assert len(client.get_calls) == 1
    assert reliable.circuit_open is True


def test_reliable_adapter_does_not_retry_malformed_response() -> None:
    client = FakeHTTPClient(
        [
            FakeResponse(200, {"status": "1"}),
            FakeResponse(200, amap_payload([amap_item(1, 121.481)])),
        ]
    )
    reliable = RetryingCircuitBreakerPOIAdapter(
        AmapPOIAdapter("test-api-key", client, OffsetTransformer()),
        max_attempts=2,
        failure_threshold=1,
    )

    with pytest.raises(POIResponseError, match="pois"):
        reliable.search(query())

    assert len(client.get_calls) == 1
    assert reliable.circuit_open is False


def test_open_circuit_allows_probe_after_recovery_timeout() -> None:
    current = [10.0]
    client = FakeHTTPClient(
        [
            FakeResponse(429, {}),
            FakeResponse(200, amap_payload([amap_item(1, 121.481)])),
        ]
    )
    reliable = RetryingCircuitBreakerPOIAdapter(
        AmapPOIAdapter("test-api-key", client, OffsetTransformer()),
        max_attempts=1,
        failure_threshold=1,
        recovery_timeout_seconds=5,
        monotonic=lambda: current[0],
    )

    with pytest.raises(POIRateLimitError):
        reliable.search(query())
    with pytest.raises(POICircuitOpenError):
        reliable.search(query())

    current[0] = 15.0
    result = reliable.search(query(limit=1))

    assert result.records
    assert len(client.get_calls) == 2
    assert reliable.circuit_open is False


def overpass_filters() -> dict[str, OverpassTagFilter]:
    return {
        "地铁站": OverpassTagFilter(key="railway", value="station"),
        "医院": OverpassTagFilter(key="amenity", value="hospital"),
    }


def test_overpass_builds_controlled_query_and_parses_node_and_way() -> None:
    client = FakeHTTPClient(
        [
            FakeResponse(
                200,
                {
                    "elements": [
                        {
                            "type": "node",
                            "id": 1,
                            "lat": 31.231,
                            "lon": 121.471,
                            "tags": {"name": "OSM地铁站", "railway": "station"},
                        },
                        {
                            "type": "way",
                            "id": 2,
                            "center": {"lat": 31.232, "lon": 121.472},
                            "tags": {"name": "OSM医院", "amenity": "hospital"},
                        },
                    ]
                },
            )
        ]
    )
    limiter = RecordingLimiter()
    adapter = OverpassPOIAdapter(
        client,
        overpass_filters(),
        rate_limiter=limiter,
        clock=lambda: NOW,
    )

    result = adapter.search(query(categories=["地铁站", "医院"], limit=10))

    assert {record.poi_id for record in result.records} == {
        "osm:node:1",
        "osm:way:2",
    }
    assert {record.category for record in result.records} == {"地铁站", "医院"}
    assert result.source.provider is POIProvider.OSM
    statement = client.post_calls[0][1]["data"]
    assert '["railway"="station"]' in statement
    assert '["amenity"="hospital"]' in statement
    assert "121.47000000" in statement
    assert limiter.calls == 1


def test_overpass_rejects_unknown_category_before_http() -> None:
    client = FakeHTTPClient([])
    adapter = OverpassPOIAdapter(client, overpass_filters())

    with pytest.raises(ValueError, match="缺少类别"):
        adapter.search(query(categories=["未知类别"]))

    assert client.post_calls == []


def test_overpass_maps_429_to_rate_limit() -> None:
    adapter = OverpassPOIAdapter(
        FakeHTTPClient([FakeResponse(429, {})]),
        overpass_filters(),
    )

    with pytest.raises(POIRateLimitError, match="429"):
        adapter.search(query())


def test_gcj02_transformer_round_trip_and_outside_china_identity() -> None:
    transformer = GCJ02CoordinateTransformer()
    longitude, latitude = 121.47, 31.23

    gcj_longitude, gcj_latitude = transformer.wgs84_to_gcj02(
        longitude,
        latitude,
    )
    restored = transformer.gcj02_to_wgs84(gcj_longitude, gcj_latitude)

    assert gcj_longitude != pytest.approx(longitude, abs=1e-4)
    assert restored == pytest.approx((longitude, latitude), abs=1e-7)
    assert transformer.wgs84_to_gcj02(-73.98, 40.75) == (-73.98, 40.75)


def test_fixed_interval_rate_limiter_waits_between_calls() -> None:
    current = [10.0]
    sleeps = []

    def monotonic() -> float:
        return current[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        current[0] += seconds

    limiter = FixedIntervalRateLimiter(
        2,
        monotonic=monotonic,
        sleep=sleep,
    )

    limiter.acquire()
    limiter.acquire()

    assert sleeps == [pytest.approx(0.5)]
