from datetime import datetime, timezone
from threading import Barrier

import pytest

from practice.site_selection import (
    CandidateParcel,
    EvidenceStatus,
    MockPOIGateway,
    POIMetric,
    POIProvider,
    POIQuery,
    POIRecord,
    ProjectIntakeSkill,
    ProjectRequest,
    ProjectType,
    calculate_poi_metrics,
    execute_poi_queries,
)


NOW = datetime(2026, 8, 18, 21, 30, tzinfo=timezone.utc)


def query(*, radius_m: int = 1_500, limit: int = 100) -> POIQuery:
    return POIQuery(
        query_id="REQ-001:A01:public_transit",
        parcel_id="A01",
        group_key="public_transit",
        longitude=121.47,
        latitude=31.23,
        categories=["地铁站", "公交站"],
        radius_m=radius_m,
        limit=limit,
    )


def record(
    poi_id: str,
    category: str,
    distance_m: float | None,
) -> POIRecord:
    return POIRecord(
        poi_id=poi_id,
        name=f"测试点 {poi_id}",
        category=category,
        longitude=121.47,
        latitude=31.23,
        distance_m=distance_m,
    )


def shopping_request() -> ProjectRequest:
    return ProjectRequest(
        request_id="REQ-shopping",
        project_type=ProjectType.SHOPPING_MALL,
        candidate_parcels=[
            CandidateParcel(
                parcel_id="A01",
                longitude=121.47,
                latitude=31.23,
            )
        ],
        requested_at=NOW,
    )


def test_mock_gateway_filters_category_and_radius() -> None:
    gateway = MockPOIGateway(
        {
            "A01": [
                record("P1", "地铁站", 500),
                record("P2", "餐厅", 300),
                record("P3", "公交站", 2_000),
            ]
        },
        clock=lambda: NOW,
    )

    result = gateway.search(query())

    assert [item.poi_id for item in result.records] == ["P1"]
    assert result.source.record_count == 1
    assert result.source.provider is POIProvider.MOCK
    assert result.source.queried_at == NOW


def test_mock_gateway_applies_limit_after_distance_sorting() -> None:
    gateway = MockPOIGateway(
        {
            "A01": [
                record("far", "地铁站", 900),
                record("near", "地铁站", 100),
            ]
        },
        clock=lambda: NOW,
    )

    result = gateway.search(query(limit=1))

    assert [item.poi_id for item in result.records] == ["near"]


def test_mock_gateway_returns_a_valid_empty_feature_set() -> None:
    result = MockPOIGateway(clock=lambda: NOW).search(query())

    assert result.records == []
    assert result.source.record_count == 0
    assert result.metrics[POIMetric.COUNT] == 0


def test_calculate_poi_metrics_uses_query_area_and_distances() -> None:
    metrics = calculate_poi_metrics(
        query(radius_m=1_000),
        [
            record("P1", "地铁站", 100),
            record("P2", "公交站", 300),
        ],
    )

    assert metrics[POIMetric.COUNT] == 2
    assert metrics[POIMetric.DENSITY_PER_SQ_KM] == pytest.approx(2 / 3.14159265)
    assert metrics[POIMetric.NEAREST_DISTANCE_M] == 100
    assert metrics[POIMetric.AVERAGE_DISTANCE_M] == 200


def test_metrics_omit_distance_values_when_provider_has_none() -> None:
    metrics = calculate_poi_metrics(
        query(),
        [record("P1", "地铁站", None)],
    )

    assert POIMetric.NEAREST_DISTANCE_M not in metrics
    assert POIMetric.AVERAGE_DISTANCE_M not in metrics


def test_execute_poi_queries_populates_business_state() -> None:
    initial_state = ProjectIntakeSkill().run(shopping_request())
    gateway = MockPOIGateway(
        {"A01": [record("P1", "地铁站", 500)]},
        clock=lambda: NOW,
    )

    result = execute_poi_queries(initial_state, gateway)

    assert len(result.poi_feature_sets) == len(initial_state.poi_queries)
    assert len(result.poi_evidence) == 1
    assert result.poi_evidence[0].status is EvidenceStatus.READY
    assert len(result.poi_evidence[0].feature_sets) == len(initial_state.poi_queries)


def test_execute_poi_queries_does_not_mutate_input_state() -> None:
    initial_state = ProjectIntakeSkill().run(shopping_request())

    execute_poi_queries(initial_state, MockPOIGateway(clock=lambda: NOW))

    assert initial_state.poi_feature_sets == []
    assert initial_state.poi_evidence == []


def test_execute_poi_queries_uses_bounded_parallelism_and_keeps_order() -> None:
    initial_state = ProjectIntakeSkill().run(shopping_request())
    first = query()
    second = first.model_copy(
        update={
            "query_id": "REQ-001:A01:food",
            "group_key": "food",
            "categories": ["餐厅"],
        }
    )
    prepared = initial_state.model_copy(
        deep=True,
        update={"poi_queries": [first, second]},
    )
    rendezvous = Barrier(2, timeout=2)

    class ParallelGateway:
        def search(self, prepared_query: POIQuery):
            rendezvous.wait()
            return MockPOIGateway(clock=lambda: NOW).search(prepared_query)

    result = execute_poi_queries(
        prepared,
        ParallelGateway(),
        max_workers=2,
    )

    assert [item.query for item in result.poi_feature_sets] == [first, second]


def test_execute_poi_queries_uses_gateway_batch_contract_when_available() -> None:
    initial_state = ProjectIntakeSkill().run(shopping_request())

    class BatchGateway:
        def __init__(self) -> None:
            self.calls = []

        def search(self, prepared_query: POIQuery):
            raise AssertionError(f"unexpected scalar search: {prepared_query.query_id}")

        def search_many(self, prepared_queries, *, max_workers):
            self.calls.append((list(prepared_queries), max_workers))
            delegate = MockPOIGateway(clock=lambda: NOW)
            return [delegate.search(item) for item in prepared_queries]

    gateway = BatchGateway()

    result = execute_poi_queries(initial_state, gateway, max_workers=3)

    assert gateway.calls == [(initial_state.poi_queries, 3)]
    assert [item.query for item in result.poi_feature_sets] == (
        initial_state.poi_queries
    )


def test_execute_poi_queries_rejects_non_positive_worker_count() -> None:
    initial_state = ProjectIntakeSkill().run(shopping_request())

    with pytest.raises(ValueError, match="worker count"):
        execute_poi_queries(
            initial_state,
            MockPOIGateway(clock=lambda: NOW),
            max_workers=0,
        )
