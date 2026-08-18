from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from math import pi
from typing import Protocol

from .evidence import AgentState, EvidenceStatus, POIEvidence
from .poi import (
    POIFeatureSet,
    POIMetric,
    POIProvider,
    POIQuery,
    POIRecord,
    POISourceMeta,
)


class POIGateway(Protocol):
    """Provider-neutral boundary for executing one normalized POI query."""

    def search(self, query: POIQuery) -> POIFeatureSet: ...


def calculate_poi_metrics(
    query: POIQuery,
    records: Iterable[POIRecord],
) -> dict[POIMetric, float]:
    """Calculate provider-independent metrics from normalized records."""

    record_list = list(records)
    count = len(record_list)
    radius_km = query.radius_m / 1_000
    metrics = {
        POIMetric.COUNT: float(count),
        POIMetric.DENSITY_PER_SQ_KM: count / (pi * radius_km**2),
    }

    distances = [
        record.distance_m
        for record in record_list
        if record.distance_m is not None
    ]
    if distances:
        metrics[POIMetric.NEAREST_DISTANCE_M] = min(distances)
        metrics[POIMetric.AVERAGE_DISTANCE_M] = sum(distances) / len(distances)
    return metrics


class MockPOIGateway:
    """Deterministic in-memory POI provider for business-flow tests."""

    def __init__(
        self,
        records_by_parcel: Mapping[str, Iterable[POIRecord]] | None = None,
        *,
        dataset_id: str = "poi-mock",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._records_by_parcel = {
            parcel_id: [record.model_copy(deep=True) for record in records]
            for parcel_id, records in (records_by_parcel or {}).items()
        }
        self._dataset_id = dataset_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def search(self, query: POIQuery) -> POIFeatureSet:
        candidates = self._records_by_parcel.get(query.parcel_id, [])
        matching = [
            record.model_copy(deep=True)
            for record in candidates
            if record.category in query.categories
            and (
                record.distance_m is None
                or record.distance_m <= query.radius_m
            )
        ]
        matching.sort(
            key=lambda record: (
                record.distance_m is None,
                record.distance_m or 0,
                record.poi_id,
            )
        )
        matching = matching[: query.limit]

        source = POISourceMeta(
            provider=POIProvider.MOCK,
            dataset_id=self._dataset_id,
            queried_at=self._clock(),
            record_count=len(matching),
        )
        return POIFeatureSet(
            query=query.model_copy(deep=True),
            records=matching,
            source=source,
            metrics=calculate_poi_metrics(query, matching),
        )


def execute_poi_queries(
    state: AgentState,
    gateway: POIGateway,
) -> AgentState:
    """Execute all prepared queries and return a newly validated state."""

    feature_sets = [gateway.search(query) for query in state.poi_queries]
    evidence = [
        POIEvidence(
            parcel_id=parcel.parcel_id,
            status=EvidenceStatus.READY,
            feature_sets=[
                feature_set
                for feature_set in feature_sets
                if feature_set.query.parcel_id == parcel.parcel_id
            ],
        )
        for parcel in state.request.candidate_parcels
    ]

    state_data = state.model_dump()
    state_data["poi_feature_sets"] = feature_sets
    state_data["poi_evidence"] = evidence
    return AgentState.model_validate(state_data)
