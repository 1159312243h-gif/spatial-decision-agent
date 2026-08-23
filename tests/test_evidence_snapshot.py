import json
from datetime import datetime, timezone
from hashlib import sha256

import pytest
from pydantic import ValidationError

from practice.site_selection import (
    CandidateDiscoveryPOISnapshot,
    CandidateDiscoverySnapshotMismatchError,
    CandidateParcel,
    POIFeatureSet,
    POIProvider,
    POIQuery,
    POIRecord,
    POISourceMeta,
    ProjectType,
    SnapshotReusingPOIGateway,
    build_candidate_discovery_poi_snapshot,
    validate_snapshot_selection,
)
from practice.site_selection.poi_service import calculate_poi_metrics


NOW = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)


def candidate() -> CandidateParcel:
    return CandidateParcel(
        parcel_id="retail-candidate-001",
        name="测试商业候选",
        longitude=121.47,
        latitude=31.23,
        area_hectares=0.08,
        geometry_dataset_id="retail-opportunity-2026-08",
    )


def broad_feature_set(*, truncated: bool = False) -> POIFeatureSet:
    query = POIQuery(
        query_id="discover-001:scope:transit_access",
        parcel_id="candidate-discovery-scope",
        group_key="transit_access",
        longitude=121.47,
        latitude=31.23,
        categories=["地铁站", "公交站"],
        radius_m=5_000,
        limit=1_000,
    )
    records = [
        POIRecord(
            poi_id="bus-near",
            name="近距离公交站",
            category="公交站",
            longitude=121.4705,
            latitude=31.23,
            distance_m=48,
        ),
        POIRecord(
            poi_id="metro-far",
            name="较远地铁站",
            category="地铁站",
            longitude=121.474,
            latitude=31.23,
            distance_m=381,
        ),
        POIRecord(
            poi_id="bus-far",
            name="较远公交站",
            category="公交站",
            longitude=121.476,
            latitude=31.23,
            distance_m=572,
        ),
    ]
    source = POISourceMeta(
        provider=POIProvider.OSM,
        dataset_id="overpass-live",
        dataset_version="2026-08-21T10:00:00+00:00",
        queried_at=NOW,
        record_count=len(records),
        available_record_count=len(records) + int(truncated),
        is_truncated=truncated,
        dataset_record_count=10_000,
    )
    return POIFeatureSet(
        query=query,
        records=records,
        source=source,
        metrics=calculate_poi_metrics(query, records),
    )


def snapshot(*, truncated: bool = False) -> CandidateDiscoveryPOISnapshot:
    return build_candidate_discovery_poi_snapshot(
        discovery_request_id="discover-001",
        project_type=ProjectType.COFFEE_SHOP,
        created_at=NOW,
        candidates=[candidate()],
        feature_sets=[broad_feature_set(truncated=truncated)],
        snapshot_id="poi-snapshot-test-001",
    )


def formal_query(
    *,
    group_key: str = "transit_access",
    categories: list[str] | None = None,
    radius_m: int = 200,
    limit: int = 10,
) -> POIQuery:
    return POIQuery(
        query_id="analysis-001:retail-candidate-001:transit_access",
        parcel_id="retail-candidate-001",
        group_key=group_key,
        longitude=121.47,
        latitude=31.23,
        categories=categories or ["公交站"],
        radius_m=radius_m,
        limit=limit,
    )


def test_snapshot_round_trips_and_detects_content_tampering() -> None:
    frozen = snapshot()
    reloaded = CandidateDiscoveryPOISnapshot.model_validate_json(
        frozen.model_dump_json()
    )
    tampered = frozen.model_dump(mode="json")
    tampered["candidates"][0]["longitude"] = 122.0

    assert reloaded == frozen
    assert frozen.unique_record_count == 3
    with pytest.raises(ValidationError, match="校验和"):
        CandidateDiscoveryPOISnapshot.model_validate(tampered)
    with pytest.raises(ValidationError, match="frozen"):
        frozen.snapshot_id = "changed"


def test_snapshot_gateway_filters_category_radius_and_recomputes_metrics() -> None:
    result = SnapshotReusingPOIGateway(snapshot()).search(formal_query())

    assert [record.poi_id for record in result.records] == ["bus-near"]
    assert result.records[0].distance_m == pytest.approx(47.6, abs=1)
    assert result.source.evidence_snapshot_id == "poi-snapshot-test-001"
    assert result.source.evidence_reused is True
    assert result.source.record_count == 1
    assert result.source.available_record_count == 1
    assert result.source.is_truncated is False
    assert result.metrics["count"] == 1


def test_snapshot_gateway_preserves_unknown_completeness() -> None:
    result = SnapshotReusingPOIGateway(snapshot(truncated=True)).search(
        formal_query()
    )

    assert len(result.records) == 1
    assert result.source.available_record_count == 2
    assert result.source.is_truncated is True
    assert result.source.evidence_reused is True
    assert result.source.evidence_supplemented is False
    assert result.source.evidence_supplement_reason == "snapshot_truncated"
    assert "未配置候选点 POI 补采网关" in result.source.evidence_supplement_error


def test_snapshot_gateway_enforces_formal_query_limit() -> None:
    result = SnapshotReusingPOIGateway(snapshot()).search(
        formal_query(radius_m=1_000, limit=1)
    )

    assert len(result.records) == 1
    assert result.source.available_record_count == 2
    assert result.source.is_truncated is True


def test_snapshot_gateway_supplements_missing_scoring_group() -> None:
    class RecordingFallback:
        def __init__(self) -> None:
            self.queries = []

        def search(self, query: POIQuery) -> POIFeatureSet:
            self.queries.append(query)
            source = POISourceMeta(
                provider=POIProvider.OSM,
                dataset_id="fallback-live",
                queried_at=NOW,
                record_count=0,
                available_record_count=0,
            )
            return POIFeatureSet(query=query, source=source)

    fallback = RecordingFallback()
    gateway = SnapshotReusingPOIGateway(snapshot(), fallback=fallback)
    query = formal_query(
        group_key="future_profile_group",
        categories=["公园"],
    )

    result = gateway.search(query)

    assert fallback.queries == [query]
    assert result.source.evidence_reused is False
    assert result.source.evidence_supplemented is True
    assert result.source.evidence_snapshot_id == "poi-snapshot-test-001"
    assert result.source.evidence_supplement_reason == "snapshot_missing_group"
    assert result.source.evidence_supplement_error is None


def test_truncated_snapshot_uses_candidate_centered_formal_query() -> None:
    class RecordingFallback:
        def __init__(self) -> None:
            self.queries = []

        def search(self, query: POIQuery) -> POIFeatureSet:
            self.queries.append(query)
            record = POIRecord(
                poi_id="candidate-local-bus",
                name="候选点附近公交站",
                category=query.categories[0],
                longitude=query.longitude,
                latitude=query.latitude,
                distance_m=0,
            )
            source = POISourceMeta(
                provider=POIProvider.OSM,
                dataset_id="candidate-local-live",
                queried_at=NOW,
                record_count=1,
                available_record_count=1,
                cache_hit=True,
            )
            return POIFeatureSet(
                query=query,
                records=[record],
                source=source,
                metrics=calculate_poi_metrics(query, [record]),
            )

    fallback = RecordingFallback()
    query = formal_query(radius_m=800, limit=25)

    result = SnapshotReusingPOIGateway(
        snapshot(truncated=True),
        fallback=fallback,
    ).search(query)

    assert fallback.queries == [query]
    assert result.query == query
    assert [record.poi_id for record in result.records] == [
        "candidate-local-bus"
    ]
    assert result.source.cache_hit is True
    assert result.source.evidence_snapshot_id == "poi-snapshot-test-001"
    assert result.source.evidence_reused is False
    assert result.source.evidence_supplemented is True
    assert result.source.evidence_supplement_reason == "snapshot_truncated"


def test_snapshot_gateway_supplements_missing_categories() -> None:
    class EmptyFallback:
        def __init__(self) -> None:
            self.queries = []

        def search(self, query: POIQuery) -> POIFeatureSet:
            self.queries.append(query)
            return POIFeatureSet(
                query=query,
                source=POISourceMeta(
                    provider=POIProvider.OSM,
                    dataset_id="candidate-local-live",
                    queried_at=NOW,
                    record_count=0,
                    available_record_count=0,
                ),
            )

    fallback = EmptyFallback()
    query = formal_query(categories=["公交站", "公园"])

    result = SnapshotReusingPOIGateway(
        snapshot(),
        fallback=fallback,
    ).search(query)

    assert fallback.queries == [query]
    assert result.source.evidence_supplemented is True
    assert result.source.evidence_supplement_reason == (
        "snapshot_missing_categories"
    )


def test_synthetic_snapshot_triggers_candidate_local_live_supplement() -> None:
    synthetic_broad = broad_feature_set().model_copy(
        deep=True,
        update={
            "source": broad_feature_set().source.model_copy(
                update={
                    "provider": POIProvider.MOCK,
                    "dataset_id": "fixture-fallback",
                    "is_synthetic": True,
                    "quality_notice": "仅用于测试，不代表真实城市覆盖",
                    "fallback_from": POIProvider.OSM,
                    "fallback_reason": "POIUpstreamError",
                }
            )
        },
    )
    frozen = build_candidate_discovery_poi_snapshot(
        discovery_request_id="discover-001",
        project_type=ProjectType.COFFEE_SHOP,
        created_at=NOW,
        candidates=[candidate()],
        feature_sets=[synthetic_broad],
        snapshot_id="poi-snapshot-synthetic-001",
    )

    class LiveFallback:
        def search(self, query: POIQuery) -> POIFeatureSet:
            record = POIRecord(
                poi_id="live-bus",
                name="真实公交站",
                category="公交站",
                longitude=query.longitude,
                latitude=query.latitude,
                distance_m=0,
            )
            return POIFeatureSet(
                query=query,
                records=[record],
                source=POISourceMeta(
                    provider=POIProvider.OSM,
                    dataset_id="candidate-local-live",
                    queried_at=NOW,
                    record_count=1,
                    available_record_count=1,
                ),
                metrics=calculate_poi_metrics(query, [record]),
            )

    result = SnapshotReusingPOIGateway(
        frozen,
        fallback=LiveFallback(),
    ).search(formal_query())

    assert [record.poi_id for record in result.records] == ["live-bus"]
    assert result.source.provider is POIProvider.OSM
    assert result.source.evidence_supplemented is True
    assert result.source.evidence_supplement_reason == (
        "snapshot_synthetic_fallback"
    )


def test_fixture_supplement_does_not_replace_available_snapshot_slice() -> None:
    class FixtureFallback:
        def search(self, query: POIQuery) -> POIFeatureSet:
            return POIFeatureSet(
                query=query,
                source=POISourceMeta(
                    provider=POIProvider.MOCK,
                    dataset_id="fixture-fallback",
                    queried_at=NOW,
                    record_count=0,
                    available_record_count=0,
                    is_synthetic=True,
                    quality_notice="仅用于测试，不代表真实城市覆盖",
                    fallback_from=POIProvider.OSM,
                    fallback_reason="POIRateLimitError",
                ),
            )

    result = SnapshotReusingPOIGateway(
        snapshot(truncated=True),
        fallback=FixtureFallback(),
    ).search(formal_query())

    assert [record.poi_id for record in result.records] == ["bus-near"]
    assert result.source.provider is POIProvider.OSM
    assert result.source.evidence_reused is True
    assert result.source.evidence_supplemented is False
    assert result.source.evidence_supplement_reason == "snapshot_truncated"
    assert result.source.evidence_supplement_error == (
        "候选点在线补查降级为 Fixture：POIRateLimitError"
    )


def test_supplement_failure_keeps_available_snapshot_slice() -> None:
    class FailingFallback:
        def search(self, query: POIQuery) -> POIFeatureSet:
            raise TimeoutError("upstream timed out")

    result = SnapshotReusingPOIGateway(
        snapshot(truncated=True),
        fallback=FailingFallback(),
    ).search(formal_query())

    assert [record.poi_id for record in result.records] == ["bus-near"]
    assert result.source.evidence_reused is True
    assert result.source.evidence_supplemented is False
    assert result.source.evidence_supplement_reason == "snapshot_truncated"
    assert result.source.evidence_supplement_error == (
        "TimeoutError: upstream timed out"
    )
    assert result.source.is_truncated is True


def test_missing_group_and_failed_supplement_still_raises() -> None:
    class FailingFallback:
        def search(self, query: POIQuery) -> POIFeatureSet:
            raise TimeoutError("upstream timed out")

    gateway = SnapshotReusingPOIGateway(
        snapshot(),
        fallback=FailingFallback(),
    )

    with pytest.raises(TimeoutError, match="upstream timed out"):
        gateway.search(
            formal_query(
                group_key="future_profile_group",
                categories=["公园"],
            )
        )


def test_poi_source_meta_accepts_payload_without_supplement_fields() -> None:
    old_payload = POISourceMeta(
        provider=POIProvider.OSM,
        dataset_id="legacy-source",
        queried_at=NOW,
        record_count=0,
        available_record_count=0,
    ).model_dump(mode="json")
    old_payload.pop("evidence_supplemented")
    old_payload.pop("evidence_supplement_reason")
    old_payload.pop("evidence_supplement_error")

    restored = POISourceMeta.model_validate(old_payload)

    assert restored.evidence_supplemented is False
    assert restored.evidence_supplement_reason is None
    assert restored.evidence_supplement_error is None


def test_snapshot_accepts_legacy_checksum_without_supplement_fields() -> None:
    legacy_payload = snapshot().model_dump(mode="json")
    for feature_set in legacy_payload["feature_sets"]:
        source = feature_set["source"]
        source.pop("evidence_supplemented")
        source.pop("evidence_supplement_reason")
        source.pop("evidence_supplement_error")
    checksum_payload = {
        key: value
        for key, value in legacy_payload.items()
        if key != "content_sha256"
    }
    canonical = json.dumps(
        checksum_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    legacy_payload["content_sha256"] = sha256(
        canonical.encode("utf-8")
    ).hexdigest()

    restored = CandidateDiscoveryPOISnapshot.model_validate(legacy_payload)

    assert restored.snapshot_id == "poi-snapshot-test-001"
    assert restored.feature_sets[0].source.evidence_supplemented is False


def test_snapshot_selection_rejects_type_candidate_and_location_mismatch() -> None:
    frozen = snapshot()

    with pytest.raises(CandidateDiscoverySnapshotMismatchError, match="类型"):
        validate_snapshot_selection(
            frozen,
            ProjectType.CONVENIENCE_STORE,
            [candidate()],
        )
    with pytest.raises(CandidateDiscoverySnapshotMismatchError, match="不属于"):
        validate_snapshot_selection(
            frozen,
            ProjectType.COFFEE_SHOP,
            [candidate().model_copy(update={"parcel_id": "unknown"})],
        )
    with pytest.raises(CandidateDiscoverySnapshotMismatchError, match="偏离"):
        validate_snapshot_selection(
            frozen,
            ProjectType.COFFEE_SHOP,
            [candidate().model_copy(update={"longitude": 121.5})],
        )
