from __future__ import annotations

import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from hashlib import sha256
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain import CandidateParcel, NonEmptyString, ProjectType
from .poi import POIFeatureSet, POIProvider, POIQuery
from .poi_adapters import haversine_distance_m
from .poi_service import POIGateway, calculate_poi_metrics


DEFAULT_SNAPSHOT_SUPPLEMENT_MAX_QUERIES = 8
SNAPSHOT_SUPPLEMENT_BUDGET_EXHAUSTED = (
    "候选点在线补查超过单轮查询预算，已保留发现快照切片"
)


class CandidateDiscoverySnapshotError(RuntimeError):
    """Base error for missing, expired, or incompatible discovery evidence."""


class CandidateDiscoverySnapshotNotFoundError(CandidateDiscoverySnapshotError):
    """Raised when a submitted discovery snapshot is no longer available."""


class CandidateDiscoverySnapshotMismatchError(CandidateDiscoverySnapshotError):
    """Raised when selected candidates do not belong to a discovery snapshot."""


class CandidateDiscoveryPOISnapshot(BaseModel):
    """Immutable scoring evidence shared by discovery and formal analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(pattern=r"^[A-Za-z0-9._-]+$")
    discovery_request_id: NonEmptyString
    project_type: ProjectType
    created_at: datetime
    candidates: list[CandidateParcel] = Field(min_length=1)
    feature_sets: list[POIFeatureSet] = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("created_at")
    @classmethod
    def created_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("候选发现证据快照时间必须包含时区")
        return value

    @model_validator(mode="after")
    def snapshot_is_consistent(self) -> CandidateDiscoveryPOISnapshot:
        candidate_ids = [item.parcel_id for item in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("候选发现证据快照不能包含重复候选")
        group_keys = [item.query.group_key for item in self.feature_sets]
        if len(group_keys) != len(set(group_keys)):
            raise ValueError("候选发现证据快照不能包含重复评分组")
        checksum_payload = self.model_dump(
            mode="json",
            exclude={"content_sha256"},
        )
        checksum_matches = self.content_sha256 == _snapshot_checksum(
            checksum_payload
        )
        legacy_payload = _legacy_snapshot_payload(checksum_payload)
        legacy_checksum_matches = (
            legacy_payload is not None
            and self.content_sha256 == _snapshot_checksum(legacy_payload)
        )
        if not checksum_matches and not legacy_checksum_matches:
            raise ValueError("候选发现证据快照校验和不一致")
        return self

    @property
    def unique_record_count(self) -> int:
        return len(
            {
                (
                    item.source.provider,
                    item.source.dataset_id,
                    record.poi_id,
                )
                for item in self.feature_sets
                for record in item.records
            }
        )


class CandidateDiscoverySnapshotStore(Protocol):
    def save_candidate_discovery_snapshot(
        self,
        snapshot: CandidateDiscoveryPOISnapshot,
    ) -> None: ...

    def get_candidate_discovery_snapshot(
        self,
        snapshot_id: str,
    ) -> CandidateDiscoveryPOISnapshot | None: ...


def build_candidate_discovery_poi_snapshot(
    *,
    discovery_request_id: str,
    project_type: ProjectType,
    created_at: datetime,
    candidates: Sequence[CandidateParcel],
    feature_sets: Sequence[POIFeatureSet],
    snapshot_id: str | None = None,
) -> CandidateDiscoveryPOISnapshot:
    payload = {
        "snapshot_id": snapshot_id or f"poi-snapshot-{uuid4()}",
        "discovery_request_id": discovery_request_id,
        "project_type": project_type,
        "created_at": created_at,
        "candidates": [item.model_copy(deep=True) for item in candidates],
        "feature_sets": [item.model_copy(deep=True) for item in feature_sets],
    }
    serialized = CandidateDiscoveryPOISnapshot.model_construct(
        **payload,
        content_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"content_sha256"})
    return CandidateDiscoveryPOISnapshot(
        **payload,
        content_sha256=_snapshot_checksum(serialized),
    )


def validate_snapshot_selection(
    snapshot: CandidateDiscoveryPOISnapshot,
    project_type: ProjectType,
    candidates: Sequence[CandidateParcel],
) -> None:
    if snapshot.project_type is not project_type:
        raise CandidateDiscoverySnapshotMismatchError(
            "候选发现证据快照与项目类型不一致"
        )
    discovered = {item.parcel_id: item for item in snapshot.candidates}
    for candidate in candidates:
        original = discovered.get(candidate.parcel_id)
        if original is None:
            raise CandidateDiscoverySnapshotMismatchError(
                f"候选不属于证据快照：{candidate.parcel_id}"
            )
        if (
            abs(original.longitude - candidate.longitude) > 1e-8
            or abs(original.latitude - candidate.latitude) > 1e-8
            or original.geometry_dataset_id != candidate.geometry_dataset_id
        ):
            raise CandidateDiscoverySnapshotMismatchError(
                f"候选位置或空间数据集已偏离证据快照：{candidate.parcel_id}"
            )


class SnapshotReusingPOIGateway:
    """Reuse complete discovery evidence and supplement incomplete local slices."""

    def __init__(
        self,
        snapshot: CandidateDiscoveryPOISnapshot,
        *,
        fallback: POIGateway | None = None,
        max_supplement_queries: int = DEFAULT_SNAPSHOT_SUPPLEMENT_MAX_QUERIES,
    ) -> None:
        if max_supplement_queries <= 0:
            raise ValueError("候选点 POI 补查查询预算必须大于 0")
        self._snapshot = snapshot.model_copy(deep=True)
        self._fallback = fallback
        self._max_supplement_queries = max_supplement_queries
        self._by_group = {
            item.query.group_key: item for item in self._snapshot.feature_sets
        }

    @property
    def cache_token(self) -> str:
        return f"discovery-snapshot:{self._snapshot.content_sha256}"

    def search(self, query: POIQuery) -> POIFeatureSet:
        broad = self._by_group.get(query.group_key)
        supplement_reason = _supplement_reason(query, broad)
        if supplement_reason is not None:
            return self._supplement(
                query,
                broad=broad,
                reason=supplement_reason,
            )
        assert broad is not None
        return self._slice_snapshot(query, broad)

    def search_many(
        self,
        queries: Sequence[POIQuery],
        *,
        max_workers: int = 4,
    ) -> list[POIFeatureSet]:
        """Reuse local slices and bound candidate supplements by whole cohort."""

        if max_workers <= 0:
            raise ValueError("POI query worker count must be positive")
        query_list = list(queries)
        if not query_list:
            return []

        reasons = [
            _supplement_reason(query, self._by_group.get(query.group_key))
            for query in query_list
        ]
        indexed_queries = enumerate(
            zip(query_list, reasons, strict=True)
        )
        mandatory_indexes = {
            index
            for index, (query, reason) in indexed_queries
            if reason is not None and self._by_group.get(query.group_key) is None
        }
        cohort_indexes: dict[str, list[int]] = {}
        for index, (query, reason) in enumerate(zip(query_list, reasons, strict=True)):
            if reason is None or index in mandatory_indexes:
                continue
            cohort_indexes.setdefault(query.group_key, []).append(index)

        selected_indexes = set(mandatory_indexes)
        remaining_budget = max(
            0,
            self._max_supplement_queries - len(mandatory_indexes),
        )
        # Keep a scoring group comparable across candidates. Larger cohorts are
        # preferred when they fit, recovering the most candidate evidence per
        # bounded batch instead of spending the budget on scattered groups.
        ordered_cohorts = sorted(
            cohort_indexes.values(),
            key=lambda indexes: (-len(indexes), indexes[0]),
        )
        for indexes in ordered_cohorts:
            if len(indexes) > remaining_budget:
                continue
            selected_indexes.update(indexes)
            remaining_budget -= len(indexes)

        def execute(index: int) -> POIFeatureSet:
            query = query_list[index]
            reason = reasons[index]
            broad = self._by_group.get(query.group_key)
            if (
                reason is not None
                and broad is not None
                and index not in selected_indexes
            ):
                return self._slice_snapshot(
                    query,
                    broad,
                    supplement_reason=reason,
                    supplement_error=SNAPSHOT_SUPPLEMENT_BUDGET_EXHAUSTED,
                )
            return self.search(query)

        if len(query_list) == 1 or max_workers == 1:
            return [execute(index) for index in range(len(query_list))]
        with ThreadPoolExecutor(
            max_workers=min(max_workers, len(query_list)),
            thread_name_prefix="snapshot-poi",
        ) as executor:
            return list(executor.map(execute, range(len(query_list))))

    def _supplement(
        self,
        query: POIQuery,
        *,
        broad: POIFeatureSet | None,
        reason: str,
    ) -> POIFeatureSet:
        try:
            if self._fallback is None:
                raise CandidateDiscoverySnapshotMismatchError(
                    f"证据快照不完整且未配置候选点 POI 补采网关：{query.group_key}"
                )
            supplemented = self._fallback.search(query)
            if supplemented.query != query:
                raise CandidateDiscoverySnapshotMismatchError(
                    f"候选点 POI 补采返回了不匹配的查询：{query.group_key}"
                )
        except Exception as exc:
            if broad is None:
                raise
            error = str(exc).strip() or "候选点 POI 补采失败"
            return self._slice_snapshot(
                query,
                broad,
                supplement_reason=reason,
                supplement_error=f"{type(exc).__name__}: {error}",
            )

        degraded_error = _degraded_supplement_error(supplemented)
        if degraded_error is not None:
            if broad is not None:
                return self._slice_snapshot(
                    query,
                    broad,
                    supplement_reason=reason,
                    supplement_error=degraded_error,
                )
            source = supplemented.source.model_copy(
                deep=True,
                update={
                    "evidence_snapshot_id": self._snapshot.snapshot_id,
                    "evidence_reused": False,
                    "evidence_supplemented": False,
                    "evidence_supplement_reason": reason,
                    "evidence_supplement_error": degraded_error,
                },
            )
            return supplemented.model_copy(
                deep=True,
                update={"source": source},
            )

        source = supplemented.source.model_copy(
            deep=True,
            update={
                "evidence_snapshot_id": self._snapshot.snapshot_id,
                "evidence_reused": False,
                "evidence_supplemented": True,
                "evidence_supplement_reason": reason,
                "evidence_supplement_error": None,
            },
        )
        return supplemented.model_copy(
            deep=True,
            update={"source": source},
        )

    def _slice_snapshot(
        self,
        query: POIQuery,
        broad: POIFeatureSet,
        *,
        supplement_reason: str | None = None,
        supplement_error: str | None = None,
    ) -> POIFeatureSet:
        categories = set(query.categories)
        snapshot_categories = set(broad.query.categories)

        filtered = []
        for record in broad.records:
            if record.category not in categories:
                continue
            distance_m = haversine_distance_m(
                query.longitude,
                query.latitude,
                record.longitude,
                record.latitude,
            )
            if distance_m <= query.radius_m:
                filtered.append(
                    record.model_copy(update={"distance_m": distance_m})
                )
        filtered.sort(key=lambda item: (item.distance_m or 0, item.poi_id))
        returned = filtered[: query.limit]
        completeness_unknown = (
            (
                broad.source.is_truncated
                and not _truncated_snapshot_covers_query(query, broad)
            )
            or not categories.issubset(snapshot_categories)
        )
        available_record_count = len(filtered)
        if completeness_unknown and available_record_count <= len(returned):
            available_record_count = len(returned) + 1
        is_truncated = completeness_unknown or len(filtered) > len(returned)
        source = broad.source.model_copy(
            deep=True,
            update={
                "record_count": len(returned),
                "available_record_count": available_record_count,
                "is_truncated": is_truncated,
                "evidence_snapshot_id": self._snapshot.snapshot_id,
                "evidence_reused": True,
                "evidence_supplemented": False,
                "evidence_supplement_reason": supplement_reason,
                "evidence_supplement_error": supplement_error,
            },
        )
        return POIFeatureSet(
            query=query.model_copy(deep=True),
            records=returned,
            source=source,
            metrics=calculate_poi_metrics(query, returned),
        )


def _supplement_reason(
    query: POIQuery,
    broad: POIFeatureSet | None,
) -> str | None:
    if broad is None:
        return "snapshot_missing_group"
    if not set(query.categories).issubset(broad.query.categories):
        return "snapshot_missing_categories"
    if broad.source.is_synthetic or broad.source.fallback_from is not None:
        return "snapshot_synthetic_fallback"
    if (
        broad.source.is_truncated
        and not _truncated_snapshot_covers_query(query, broad)
    ):
        return "snapshot_truncated"
    return None


def _truncated_snapshot_covers_query(
    query: POIQuery,
    broad: POIFeatureSet,
) -> bool:
    """Prove a local OSM circle lies inside the retained nearest-record radius."""

    source = broad.source
    if (
        not source.is_truncated
        or source.provider is not POIProvider.OSM
        or source.is_synthetic
        or source.fallback_from is not None
        or source.record_count != broad.query.limit
        or not broad.records
        or any(record.distance_m is None for record in broad.records)
    ):
        return False
    retained_radius_m = max(
        float(record.distance_m or 0) for record in broad.records
    )
    center_distance_m = haversine_distance_m(
        broad.query.longitude,
        broad.query.latitude,
        query.longitude,
        query.latitude,
    )
    return center_distance_m + query.radius_m < retained_radius_m


def _degraded_supplement_error(
    feature_set: POIFeatureSet,
) -> str | None:
    source = feature_set.source
    if not source.is_synthetic and source.fallback_from is None:
        return None
    reason = source.fallback_reason or "synthetic_fixture"
    return f"候选点在线补查降级为 Fixture：{reason}"


def _snapshot_checksum(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _legacy_snapshot_payload(payload: dict) -> dict | None:
    """Recreate checksums written before candidate supplement metadata existed."""

    legacy = json.loads(json.dumps(payload, ensure_ascii=False))
    new_defaults = {
        "evidence_supplemented": False,
        "evidence_supplement_reason": None,
        "evidence_supplement_error": None,
    }
    for feature_set in legacy.get("feature_sets", []):
        source = feature_set.get("source", {})
        if any(source.get(key) != value for key, value in new_defaults.items()):
            return None
        for key in new_defaults:
            source.pop(key, None)
    return legacy
