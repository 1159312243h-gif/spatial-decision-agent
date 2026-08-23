from __future__ import annotations

import json
import re
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..domain import NonEmptyString
from ..evidence_snapshot import CandidateDiscoveryPOISnapshot
from ..online_land_use import LandUseFeatureSet, LandUseQuery
from ..poi import POIFeatureSet, POIQuery
from .redis_state import RedisRunStateStore, RunState


_SAFE_NAMESPACE = re.compile(r"^[A-Za-z0-9:_-]+$")
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class RedisRuntimeClient(Protocol):
    def set(
        self,
        name: str,
        value: str,
        *,
        ex: int,
        nx: bool = False,
    ) -> Any: ...

    def get(self, name: str) -> bytes | str | None: ...

    def delete(self, name: str) -> int: ...

    def rpush(self, name: str, value: str) -> int: ...

    def lrange(self, name: str, start: int, end: int) -> list[bytes | str]: ...

    def expire(self, name: str, seconds: int) -> Any: ...

    def ttl(self, name: str) -> int: ...


class RunEventType(StrEnum):
    CREATED = "created"
    ENQUEUED = "enqueued"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    HUMAN_REVIEW_ACKNOWLEDGED = "human_review_acknowledged"


class RunEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: NonEmptyString
    event_type: RunEventType
    occurred_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("运行事件时间必须包含时区")
        return value


class IdempotencyClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: NonEmptyString
    created: bool


class IdempotencyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: NonEmptyString
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class IdempotencyConflictError(RuntimeError):
    """Raised when one idempotency key is reused for another request."""


class RedisSiteSelectionRuntimeStore:
    """Redis boundary for run state, idempotency, POI cache, and events."""

    def __init__(
        self,
        client: RedisRuntimeClient,
        *,
        namespace: str = "site_selection",
        run_ttl_seconds: int = 86_400,
        idempotency_ttl_seconds: int = 86_400,
        poi_cache_ttl_seconds: int = 3_600,
        land_use_cache_ttl_seconds: int = 3_600,
        discovery_snapshot_ttl_seconds: int | None = None,
        event_ttl_seconds: int = 86_400,
        scenario_session_ttl_seconds: int = 86_400,
    ) -> None:
        if client is None:
            raise ValueError("Redis 运行时存储必须配置客户端")
        if _SAFE_NAMESPACE.fullmatch(namespace) is None:
            raise ValueError("Redis namespace 包含不安全字符")
        snapshot_ttl = (
            min(7_200, run_ttl_seconds)
            if discovery_snapshot_ttl_seconds is None
            else discovery_snapshot_ttl_seconds
        )
        ttls = {
            "run": run_ttl_seconds,
            "idempotency": idempotency_ttl_seconds,
            "poi_cache": poi_cache_ttl_seconds,
            "land_use_cache": land_use_cache_ttl_seconds,
            "discovery_snapshot": snapshot_ttl,
            "events": event_ttl_seconds,
            "scenario_session": scenario_session_ttl_seconds,
        }
        invalid = [name for name, value in ttls.items() if value <= 0]
        if invalid:
            raise ValueError("Redis TTL 必须大于 0：" + ", ".join(invalid))
        if idempotency_ttl_seconds > run_ttl_seconds:
            raise ValueError("幂等键 TTL 不能长于运行状态 TTL")
        if event_ttl_seconds > run_ttl_seconds:
            raise ValueError("运行事件 TTL 不能长于运行状态 TTL")
        if snapshot_ttl > run_ttl_seconds:
            raise ValueError("候选发现证据快照 TTL 不能长于运行状态 TTL")

        self._client = client
        self._namespace = namespace
        self._idempotency_ttl_seconds = idempotency_ttl_seconds
        self._poi_cache_ttl_seconds = poi_cache_ttl_seconds
        self._land_use_cache_ttl_seconds = land_use_cache_ttl_seconds
        self._discovery_snapshot_ttl_seconds = snapshot_ttl
        self._event_ttl_seconds = event_ttl_seconds
        self._scenario_session_ttl_seconds = scenario_session_ttl_seconds
        self.run_states = RedisRunStateStore(
            client,
            namespace=f"{namespace}:run_state",
            ttl_seconds=run_ttl_seconds,
        )

    @property
    def namespace(self) -> str:
        return self._namespace

    def claim_idempotency(
        self,
        idempotency_key: str,
        run_id: str,
        *,
        request_fingerprint: str,
    ) -> IdempotencyClaim:
        normalized = _normalize_idempotency_key(idempotency_key)
        _validate_run_id(run_id)
        record = IdempotencyRecord(
            run_id=run_id,
            request_fingerprint=request_fingerprint,
        )
        key = self._idempotency_key(normalized)
        created = bool(
            self._client.set(
                key,
                record.model_dump_json(),
                ex=self._idempotency_ttl_seconds,
                nx=True,
            )
        )
        if created:
            return IdempotencyClaim(run_id=run_id, created=True)

        payload = _decode(self._client.get(key))
        if payload is None:
            raise RuntimeError("Redis 幂等键竞争后未能读取现有 run_id")
        existing = IdempotencyRecord.model_validate_json(payload)
        _validate_run_id(existing.run_id)
        if existing.request_fingerprint != request_fingerprint:
            raise IdempotencyConflictError(
                "同一幂等键不能用于不同的选址请求"
            )
        return IdempotencyClaim(run_id=existing.run_id, created=False)

    def get_cached_poi(
        self,
        query: POIQuery,
        *,
        cache_scope: str,
    ) -> POIFeatureSet | None:
        payload = self._client.get(self._poi_cache_key(query, cache_scope))
        decoded = _decode(payload)
        if decoded is None:
            return None
        return POIFeatureSet.model_validate_json(decoded)

    def save_cached_poi(
        self,
        feature_set: POIFeatureSet,
        *,
        cache_scope: str,
    ) -> None:
        self._client.set(
            self._poi_cache_key(feature_set.query, cache_scope),
            feature_set.model_dump_json(),
            ex=self._poi_cache_ttl_seconds,
        )

    def invalidate_cached_poi(
        self,
        query: POIQuery,
        *,
        cache_scope: str,
    ) -> bool:
        return bool(
            self._client.delete(self._poi_cache_key(query, cache_scope))
        )

    def get_cached_land_use(
        self,
        query: LandUseQuery,
        *,
        cache_scope: str,
    ) -> LandUseFeatureSet | None:
        payload = self._client.get(
            self._land_use_cache_key(query, cache_scope)
        )
        decoded = _decode(payload)
        if decoded is None:
            return None
        return LandUseFeatureSet.model_validate_json(decoded)

    def save_cached_land_use(
        self,
        feature_set: LandUseFeatureSet,
        *,
        cache_scope: str,
    ) -> None:
        self._client.set(
            self._land_use_cache_key(feature_set.query, cache_scope),
            feature_set.model_dump_json(),
            ex=self._land_use_cache_ttl_seconds,
        )

    def save_candidate_discovery_snapshot(
        self,
        snapshot: CandidateDiscoveryPOISnapshot,
    ) -> None:
        self._client.set(
            self._discovery_snapshot_key(snapshot.snapshot_id),
            snapshot.model_dump_json(),
            ex=self._discovery_snapshot_ttl_seconds,
        )

    def get_candidate_discovery_snapshot(
        self,
        snapshot_id: str,
    ) -> CandidateDiscoveryPOISnapshot | None:
        payload = _decode(
            self._client.get(self._discovery_snapshot_key(snapshot_id))
        )
        if payload is None:
            return None
        return CandidateDiscoveryPOISnapshot.model_validate_json(payload)

    def save_scenario_session(
        self,
        session: "ScenarioConversationSession",
    ) -> None:
        self._client.set(
            self._scenario_session_key(session.session_id),
            session.model_dump_json(),
            ex=self._scenario_session_ttl_seconds,
        )

    def get_scenario_session(
        self,
        session_id: str,
    ) -> "ScenarioConversationSession | None":
        from ..scenario import ScenarioConversationSession

        payload = _decode(
            self._client.get(self._scenario_session_key(session_id))
        )
        if payload is None:
            return None
        return ScenarioConversationSession.model_validate_json(payload)

    def append_event(self, event: RunEvent) -> None:
        _validate_run_id(event.run_id)
        key = self._events_key(event.run_id)
        self._client.rpush(key, event.model_dump_json())
        self._client.expire(key, self._event_ttl_seconds)

    def list_events(self, run_id: str) -> list[RunEvent]:
        _validate_run_id(run_id)
        return [
            RunEvent.model_validate_json(_decode_required(payload))
            for payload in self._client.lrange(self._events_key(run_id), 0, -1)
        ]

    def idempotency_ttl(self, idempotency_key: str) -> int:
        normalized = _normalize_idempotency_key(idempotency_key)
        return self._client.ttl(self._idempotency_key(normalized))

    def poi_cache_ttl(self, query: POIQuery, *, cache_scope: str) -> int:
        return self._client.ttl(self._poi_cache_key(query, cache_scope))

    def land_use_cache_ttl(
        self,
        query: LandUseQuery,
        *,
        cache_scope: str,
    ) -> int:
        return self._client.ttl(
            self._land_use_cache_key(query, cache_scope)
        )

    def candidate_discovery_snapshot_ttl(self, snapshot_id: str) -> int:
        return self._client.ttl(self._discovery_snapshot_key(snapshot_id))

    def events_ttl(self, run_id: str) -> int:
        _validate_run_id(run_id)
        return self._client.ttl(self._events_key(run_id))

    def scenario_session_ttl(self, session_id: str) -> int:
        return self._client.ttl(self._scenario_session_key(session_id))

    def _idempotency_key(self, normalized_key: str) -> str:
        digest = sha256(normalized_key.encode("utf-8")).hexdigest()
        return f"{self._namespace}:idempotency:{digest}"

    def _poi_cache_key(self, query: POIQuery, cache_scope: str) -> str:
        normalized_scope = cache_scope.strip()
        if not normalized_scope:
            raise ValueError("POI cache_scope 不能为空")
        payload = {
            "scope": normalized_scope,
            "longitude": query.longitude,
            "latitude": query.latitude,
            "categories": sorted(query.categories),
            "radius_m": query.radius_m,
            "limit": query.limit,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = sha256(canonical.encode("utf-8")).hexdigest()
        return f"{self._namespace}:poi_cache:{digest}"

    def _events_key(self, run_id: str) -> str:
        return f"{self._namespace}:events:{run_id}"

    def _land_use_cache_key(
        self,
        query: LandUseQuery,
        cache_scope: str,
    ) -> str:
        normalized_scope = cache_scope.strip()
        if not normalized_scope:
            raise ValueError("用地 cache_scope 不能为空")
        payload = {
            "scope": normalized_scope,
            "project_type": query.project_type.value,
            "west": query.west,
            "south": query.south,
            "east": query.east,
            "north": query.north,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = sha256(canonical.encode("utf-8")).hexdigest()
        return f"{self._namespace}:land_use_cache:{digest}"

    def _discovery_snapshot_key(self, snapshot_id: str) -> str:
        _validate_snapshot_id(snapshot_id)
        return f"{self._namespace}:discovery_snapshot:{snapshot_id}"

    def _scenario_session_key(self, session_id: str) -> str:
        _validate_session_id(session_id)
        return f"{self._namespace}:scenario_session:{session_id}"


def _normalize_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("幂等键不能为空")
    if len(normalized) > 200:
        raise ValueError("幂等键长度不能超过 200")
    return normalized


def _validate_run_id(run_id: str) -> None:
    if _SAFE_RUN_ID.fullmatch(run_id) is None:
        raise ValueError("run_id 只能包含字母、数字、点、下划线和连字符")


def _validate_snapshot_id(snapshot_id: str) -> None:
    if _SAFE_RUN_ID.fullmatch(snapshot_id) is None:
        raise ValueError("snapshot_id 只能包含字母、数字、点、下划线和连字符")


def _validate_session_id(session_id: str) -> None:
    if _SAFE_RUN_ID.fullmatch(session_id) is None:
        raise ValueError("session_id 只能包含字母、数字、点、下划线和连字符")


def _decode(value: bytes | str | None) -> str | None:
    if value is None:
        return None
    return value.decode("utf-8") if isinstance(value, bytes) else value


def _decode_required(value: bytes | str) -> str:
    decoded = _decode(value)
    if decoded is None:
        raise RuntimeError("Redis 返回了空列表元素")
    return decoded
