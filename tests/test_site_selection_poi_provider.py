from pathlib import Path

import pytest

from app.services.site_selection_poi_provider import (
    OVERPASS_CATEGORY_FILTERS,
    SiteSelectionPOIProviderConfigurationError,
    build_configured_poi_provider,
)
from practice.site_selection import (
    POIProvider,
    POIQuery,
    get_supported_poi_categories,
)
from practice.site_selection.poi_adapters import FixturePOIAdapter
from practice.site_selection.storage import RedisSiteSelectionRuntimeStore
from tests.storage_fakes import FakeConnection, FakeRedis


FIXTURE_PATH = Path(__file__).parents[1] / "data" / "fixtures" / "poi.json"


def test_online_provider_covers_every_reviewed_profile_category() -> None:
    assert len(get_supported_poi_categories()) == 30
    assert set(OVERPASS_CATEGORY_FILTERS) == set(get_supported_poi_categories())


class FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeHTTPClient:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.get_calls = []
        self.post_calls = []
        self.closed = False

    def get(self, url, *, params, timeout):
        self.get_calls.append((url, params, timeout))
        return self.responses.pop(0)

    def post(self, url, *, data, timeout):
        self.post_calls.append((url, data, timeout))
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


class FailingHTTPClient(FakeHTTPClient):
    def __init__(self) -> None:
        super().__init__([])

    def post(self, url, *, data, timeout):
        self.post_calls.append((url, data, timeout))
        raise TimeoutError("simulated upstream timeout")


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def begin(self):
        connection = self.connection

        class Transaction:
            def __enter__(self):
                return connection

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        return Transaction()


def query(query_id: str = "online-001") -> POIQuery:
    return POIQuery(
        query_id=query_id,
        parcel_id="MALL-A01",
        group_key="public_transit",
        longitude=121.47,
        latitude=31.23,
        categories=["地铁站"],
        radius_m=1_500,
        limit=10,
    )


def cache_store() -> RedisSiteSelectionRuntimeStore:
    return RedisSiteSelectionRuntimeStore(
        FakeRedis(),
        namespace="site_selection:provider-test",
        poi_cache_ttl_seconds=300,
    )


def fixture_adapter() -> FixturePOIAdapter:
    return FixturePOIAdapter.from_json(FIXTURE_PATH)


def test_auto_provider_uses_overpass_and_reuses_redis_cache() -> None:
    client = FakeHTTPClient(
        [
            FakeResponse(
                {
                    "elements": [
                        {
                            "type": "node",
                            "id": 101,
                            "lat": 31.231,
                            "lon": 121.471,
                            "tags": {
                                "name": "自动加载地铁站",
                                "railway": "station",
                            },
                        }
                    ]
                }
            )
        ]
    )
    configured = build_configured_poi_provider(
        {
            "SITE_SELECTION_POI_PROVIDER": "auto",
            "SITE_SELECTION_POI_FALLBACK_ENABLED": "false",
            "SITE_SELECTION_POI_PERSIST_ENABLED": "false",
        },
        fixture_adapter(),
        cache_store=cache_store(),
        engine=object(),
        http_client_factory=lambda **kwargs: client,
    )

    first = configured.adapter.search(query())
    second_query = query("online-002")
    second = configured.adapter.search(second_query)

    assert configured.resolved_mode == "overpass"
    assert first.source.provider is POIProvider.OSM
    assert first.source.is_synthetic is False
    assert second.query == second_query
    assert first.source.cache_hit is False
    assert second.source.cache_hit is True
    assert len(client.post_calls) == 1
    assert client.post_calls[0][2] == 15

    configured.close()
    assert client.closed is True


def test_auto_provider_fails_fast_and_opens_circuit_before_fixture_fallback() -> None:
    client = FailingHTTPClient()
    configured = build_configured_poi_provider(
        {
            "SITE_SELECTION_POI_PROVIDER": "auto",
            "SITE_SELECTION_POI_PERSIST_ENABLED": "false",
            "SITE_SELECTION_POI_FAILURE_THRESHOLD": "1",
        },
        fixture_adapter(),
        cache_store=cache_store(),
        engine=object(),
        http_client_factory=lambda **kwargs: client,
    )

    first = configured.adapter.search(query())
    second = configured.adapter.search(query("online-002"))

    assert first.source.provider is POIProvider.MOCK
    assert first.source.fallback_from is POIProvider.OSM
    assert second.source.provider is POIProvider.MOCK
    assert second.source.fallback_from is POIProvider.OSM
    assert first.source.cache_hit is False
    assert second.source.cache_hit is False
    assert len(client.post_calls) == 2
    assert all(call[2] == 15 for call in client.post_calls)


def test_default_circuit_budget_does_not_block_next_scoring_group() -> None:
    client = FailingHTTPClient()
    configured = build_configured_poi_provider(
        {
            "SITE_SELECTION_POI_PROVIDER": "auto",
            "SITE_SELECTION_POI_PERSIST_ENABLED": "false",
        },
        fixture_adapter(),
        cache_store=cache_store(),
        engine=object(),
        http_client_factory=lambda **kwargs: client,
    )

    first = configured.adapter.search(query())
    second = configured.adapter.search(query("online-002"))

    assert first.source.fallback_reason == "POIUpstreamError"
    assert second.source.fallback_reason == "POIUpstreamError"
    assert len(client.post_calls) == 4
    assert all(call[2] == 15 for call in client.post_calls)


def test_online_provider_passes_explicit_container_proxy() -> None:
    client = FakeHTTPClient(
        [FakeResponse({"elements": []})]
    )
    captured_options = {}

    def factory(**options):
        captured_options.update(options)
        return client

    configured = build_configured_poi_provider(
        {
            "SITE_SELECTION_POI_PROVIDER": "overpass",
            "SITE_SELECTION_POI_PROXY_URL": (
                "http://host.docker.internal:7897"
            ),
            "SITE_SELECTION_POI_FALLBACK_ENABLED": "false",
            "SITE_SELECTION_POI_PERSIST_ENABLED": "false",
        },
        fixture_adapter(),
        cache_store=cache_store(),
        engine=object(),
        http_client_factory=factory,
    )

    configured.adapter.search(query())

    assert captured_options["proxy"] == "http://host.docker.internal:7897"
    assert configured.adapter.max_categories_per_query == 3


def test_auto_provider_prefers_amap_when_key_is_configured() -> None:
    client = FakeHTTPClient(
        [
            FakeResponse(
                {
                    "status": "1",
                    "infocode": "10000",
                    "pois": [
                        {
                            "id": "AMAP-101",
                            "name": "自动加载地铁站",
                            "location": "121.476000,31.228000",
                            "type": "交通设施服务;地铁站",
                            "typecode": "150500",
                            "address": "测试地址",
                        }
                    ],
                }
            )
        ]
    )
    configured = build_configured_poi_provider(
        {
            "SITE_SELECTION_POI_PROVIDER": "auto",
            "AMAP_API_KEY": "test-key",
            "SITE_SELECTION_POI_FALLBACK_ENABLED": "false",
            "SITE_SELECTION_POI_PERSIST_ENABLED": "false",
        },
        fixture_adapter(),
        cache_store=cache_store(),
        engine=object(),
        http_client_factory=lambda **kwargs: client,
    )

    result = configured.adapter.search(query())

    assert configured.resolved_mode == "amap"
    assert configured.adapter.max_categories_per_query == 3
    assert "pages=2" in configured.adapter.cache_token
    assert result.source.provider is POIProvider.AMAP
    assert result.records[0].attributes["source_crs"] == "GCJ-02"
    assert "source_longitude" in result.records[0].attributes
    assert len(client.get_calls) == 1


def test_online_results_are_upserted_into_postgis() -> None:
    client = FakeHTTPClient(
        [
            FakeResponse(
                {
                    "elements": [
                        {
                            "type": "node",
                            "id": 202,
                            "lat": 31.232,
                            "lon": 121.472,
                            "tags": {
                                "name": "入库地铁站",
                                "railway": "station",
                            },
                        }
                    ]
                }
            )
        ]
    )
    engine = FakeEngine()
    configured = build_configured_poi_provider(
        {
            "SITE_SELECTION_POI_PROVIDER": "overpass",
            "SITE_SELECTION_POI_FALLBACK_ENABLED": "false",
        },
        fixture_adapter(),
        cache_store=cache_store(),
        engine=engine,
        http_client_factory=lambda **kwargs: client,
    )

    configured.adapter.search(query())

    statements = "\n".join(
        statement for statement, _ in engine.connection.calls
    )
    assert "INSERT INTO site_selection.pois" in statements
    parameters = engine.connection.calls[-1][1][0]
    assert parameters["source"] == "osm"
    assert parameters["source_id"] == "node/202"
    assert parameters["source_crs"] == "EPSG:4326"


def test_explicit_amap_requires_key_and_provider_name_is_validated() -> None:
    with pytest.raises(
        SiteSelectionPOIProviderConfigurationError,
        match="AMAP_API_KEY",
    ):
        build_configured_poi_provider(
            {"SITE_SELECTION_POI_PROVIDER": "amap"},
            fixture_adapter(),
            cache_store=cache_store(),
            engine=object(),
        )
    with pytest.raises(
        SiteSelectionPOIProviderConfigurationError,
        match="只能是",
    ):
        build_configured_poi_provider(
            {"SITE_SELECTION_POI_PROVIDER": "unknown"},
            fixture_adapter(),
            cache_store=cache_store(),
            engine=object(),
        )
