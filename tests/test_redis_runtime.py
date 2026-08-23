from datetime import datetime, timezone

import pytest

from practice.site_selection import POIFeatureSet, POIQuery
from practice.site_selection import (
    DatasetEvidenceLevel,
    LandUseFeatureSet,
    LandUseQuery,
    LandUseSourceMeta,
    ProjectType,
)
from practice.site_selection.storage import (
    IdempotencyConflictError,
    RedisSiteSelectionRuntimeStore,
    RunEvent,
    RunEventType,
)
from tests.storage_fakes import FakeRedis
from tests.test_evidence_snapshot import snapshot
from tests.test_site_selection_workflow import poi_gateway


NOW = datetime(2026, 8, 21, 13, 0, tzinfo=timezone.utc)


def query(*, query_id: str = "preview-001") -> POIQuery:
    return POIQuery(
        query_id=query_id,
        parcel_id="preview",
        group_key="preview",
        longitude=121.47,
        latitude=31.23,
        categories=["地铁站"],
        radius_m=1_000,
        limit=20,
    )


def feature_set() -> POIFeatureSet:
    return poi_gateway().search(query())


def test_idempotency_claim_is_atomic_and_namespaced() -> None:
    client = FakeRedis()
    store = RedisSiteSelectionRuntimeStore(
        client,
        namespace="site_selection:test",
        idempotency_ttl_seconds=600,
    )

    fingerprint = "a" * 64
    first = store.claim_idempotency(
        "client-request-001",
        "run-001",
        request_fingerprint=fingerprint,
    )
    second = store.claim_idempotency(
        "client-request-001",
        "run-002",
        request_fingerprint=fingerprint,
    )

    assert first.created is True
    assert first.run_id == "run-001"
    assert second.created is False
    assert second.run_id == "run-001"
    assert store.idempotency_ttl("client-request-001") == 600
    assert any(":idempotency:" in key for key in client.values)

    with pytest.raises(IdempotencyConflictError, match="不同"):
        store.claim_idempotency(
            "client-request-001",
            "run-003",
            request_fingerprint="b" * 64,
        )


def test_poi_cache_ignores_query_identity_but_separates_scope() -> None:
    store = RedisSiteSelectionRuntimeStore(
        FakeRedis(),
        poi_cache_ttl_seconds=90,
    )
    result = feature_set()
    store.save_cached_poi(result, cache_scope="shopping_mall:v1")

    cached = store.get_cached_poi(
        query(query_id="another-id"),
        cache_scope="shopping_mall:v1",
    )

    assert cached == result
    assert store.get_cached_poi(
        query(query_id="another-id"),
        cache_scope="shopping_mall:v2",
    ) is None
    assert store.poi_cache_ttl(
        query(),
        cache_scope="shopping_mall:v1",
    ) == 90
    assert store.invalidate_cached_poi(
        query(),
        cache_scope="shopping_mall:v1",
    ) is True
    assert store.get_cached_poi(
        query(),
        cache_scope="shopping_mall:v1",
    ) is None


def test_events_round_trip_in_append_order_with_ttl() -> None:
    store = RedisSiteSelectionRuntimeStore(
        FakeRedis(),
        event_ttl_seconds=300,
    )
    store.append_event(
        RunEvent(
            run_id="run-003",
            event_type=RunEventType.CREATED,
            occurred_at=NOW,
        )
    )
    store.append_event(
        RunEvent(
            run_id="run-003",
            event_type=RunEventType.STARTED,
            occurred_at=NOW,
        )
    )

    events = store.list_events("run-003")

    assert [event.event_type for event in events] == [
        RunEventType.CREATED,
        RunEventType.STARTED,
    ]
    assert store.events_ttl("run-003") == 300


def test_candidate_discovery_snapshot_round_trips_with_bounded_ttl() -> None:
    client = FakeRedis()
    store = RedisSiteSelectionRuntimeStore(
        client,
        run_ttl_seconds=600,
        idempotency_ttl_seconds=600,
        discovery_snapshot_ttl_seconds=300,
        event_ttl_seconds=600,
    )
    frozen = snapshot()

    store.save_candidate_discovery_snapshot(frozen)

    assert store.get_candidate_discovery_snapshot(frozen.snapshot_id) == frozen
    assert store.candidate_discovery_snapshot_ttl(frozen.snapshot_id) == 300
    assert any(":discovery_snapshot:" in key for key in client.values)


def test_land_use_cache_round_trips_with_separate_ttl() -> None:
    client = FakeRedis()
    store = RedisSiteSelectionRuntimeStore(
        client,
        land_use_cache_ttl_seconds=180,
    )
    land_query = LandUseQuery(
        project_type=ProjectType.COFFEE_SHOP,
        west=121.3,
        south=31.1,
        east=121.4,
        north=31.2,
    )
    result = LandUseFeatureSet(
        query=land_query,
        features=[],
        source=LandUseSourceMeta(
            dataset_id="osm-land",
            dataset_version="v1",
            evidence_level=DatasetEvidenceLevel.PUBLIC_OBSERVATION,
            queried_at=NOW,
            source_uri="https://overpass-api.de/api/interpreter",
            license="ODbL 1.0",
            record_count=0,
            available_record_count=0,
        ),
    )

    store.save_cached_land_use(result, cache_scope="land-v1")

    assert store.get_cached_land_use(land_query, cache_scope="land-v1") == result
    assert store.land_use_cache_ttl(land_query, cache_scope="land-v1") == 180
    assert any(":land_use_cache:" in key for key in client.values)


def test_runtime_store_rejects_invalid_keys_and_ttls() -> None:
    with pytest.raises(ValueError, match="TTL"):
        RedisSiteSelectionRuntimeStore(FakeRedis(), poi_cache_ttl_seconds=0)
    with pytest.raises(ValueError, match="幂等键 TTL"):
        RedisSiteSelectionRuntimeStore(
            FakeRedis(),
            run_ttl_seconds=60,
            idempotency_ttl_seconds=61,
            event_ttl_seconds=60,
        )
    with pytest.raises(ValueError, match="证据快照 TTL"):
        RedisSiteSelectionRuntimeStore(
            FakeRedis(),
            run_ttl_seconds=60,
            idempotency_ttl_seconds=60,
            discovery_snapshot_ttl_seconds=61,
            event_ttl_seconds=60,
        )
    store = RedisSiteSelectionRuntimeStore(FakeRedis())
    with pytest.raises(ValueError, match="幂等键"):
        store.claim_idempotency(
            " ",
            "run-001",
            request_fingerprint="a" * 64,
        )
    with pytest.raises(ValueError, match="run_id"):
        store.list_events("../run")
