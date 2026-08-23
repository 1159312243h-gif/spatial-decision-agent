from datetime import datetime, timezone

import pytest

from app.services.site_selection_land_use_provider import (
    build_configured_land_use_provider,
)
from practice.site_selection import (
    CachedLandUseProvider,
    DatasetEvidenceLevel,
    LandUseAvailabilityError,
    LandUseQuery,
    OverpassLandUseProvider,
    ProjectType,
)
from practice.site_selection.storage import RedisSiteSelectionRuntimeStore
from tests.storage_fakes import FakeRedis


NOW = datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload, status_code=200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeHTTPClient:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def post(self, url, *, data, timeout):
        self.calls.append((url, data, timeout))
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self) -> None:
        self.closed = True


def query() -> LandUseQuery:
    return LandUseQuery(
        project_type=ProjectType.COFFEE_SHOP,
        west=121.30,
        south=31.14,
        east=121.36,
        north=31.19,
    )


def way(element_id, longitude, latitude, *, landuse="commercial"):
    delta = 0.001
    return {
        "type": "way",
        "id": element_id,
        "tags": {"name": f"商业单元 {element_id}", "landuse": landuse},
        "geometry": [
            {"lon": longitude, "lat": latitude},
            {"lon": longitude + delta, "lat": latitude},
            {"lon": longitude + delta, "lat": latitude + delta},
            {"lon": longitude, "lat": latitude + delta},
            {"lon": longitude, "lat": latitude},
        ],
    }


def test_overpass_land_use_parses_real_polygons_and_metadata() -> None:
    client = FakeHTTPClient(
        [FakeResponse({"elements": [way(101, 121.31, 31.15)]})]
    )
    provider = OverpassLandUseProvider(
        client,
        timeout_seconds=9,
        clock=lambda: NOW,
    )

    result = provider.search(query())

    assert len(result.features) == 1
    assert result.features[0].source_feature_id == "osm:way:101"
    assert result.features[0].land_use_class == "OSM 商业用地"
    assert result.features[0].area_hectares > 0
    assert result.source.evidence_level is DatasetEvidenceLevel.PUBLIC_OBSERVATION
    assert result.source.license == "OpenStreetMap ODbL 1.0"
    assert result.source.cache_hit is False
    assert client.calls[0][2] == 9
    assert 'way["landuse"~"^(commercial|retail)$"]' in client.calls[0][1]["data"]


def test_land_use_provider_reuses_redis_cache_by_bounds() -> None:
    client = FakeHTTPClient(
        [FakeResponse({"elements": [way(102, 121.32, 31.16)]})]
    )
    store = RedisSiteSelectionRuntimeStore(
        FakeRedis(),
        land_use_cache_ttl_seconds=120,
    )
    provider = CachedLandUseProvider(
        OverpassLandUseProvider(client, clock=lambda: NOW),
        store,
        cache_scope="osm-land-test-v1",
    )

    first = provider.search(query())
    second = provider.search(query())

    assert first.source.cache_hit is False
    assert second.source.cache_hit is True
    assert len(client.calls) == 1
    assert store.land_use_cache_ttl(
        query(), cache_scope="osm-land-test-v1"
    ) == 120


def test_overpass_land_use_exposes_availability_failure_for_strict_fallback() -> None:
    provider = OverpassLandUseProvider(
        FakeHTTPClient([TimeoutError("offline")])
    )

    with pytest.raises(LandUseAvailabilityError, match="网络请求失败"):
        provider.search(query())


def test_configured_land_use_provider_uses_shared_proxy_and_closes_client() -> None:
    client = FakeHTTPClient([])
    options = []
    configured = build_configured_land_use_provider(
        {
            "SITE_SELECTION_LAND_USE_PROVIDER": "auto",
            "SITE_SELECTION_POI_PROXY_URL": "http://proxy:7897",
        },
        http_client_factory=lambda **kwargs: options.append(kwargs) or client,
    )

    assert configured.provider is not None
    assert options[0]["proxy"] == "http://proxy:7897"
    configured.close()
    assert client.closed is True


def test_configured_land_use_provider_can_be_disabled() -> None:
    configured = build_configured_land_use_provider(
        {"SITE_SELECTION_LAND_USE_PROVIDER": "disabled"},
    )

    assert configured.provider is None
    assert configured.http_client is None
