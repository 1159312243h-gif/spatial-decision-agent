from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain import NonEmptyString


_SAFE_NAMESPACE = re.compile(r"^[A-Za-z0-9:_-]+$")
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class RedisClient(Protocol):
    def set(self, name: str, value: str, *, ex: int) -> Any: ...

    def get(self, name: str) -> bytes | str | None: ...

    def delete(self, name: str) -> int: ...

    def ttl(self, name: str) -> int: ...


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: NonEmptyString
    status: RunStatus
    updated_at: datetime
    error: NonEmptyString | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def state_is_consistent(self) -> RunState:
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("运行状态更新时间必须包含时区")
        if self.status is RunStatus.FAILED and self.error is None:
            raise ValueError("failed 状态必须包含错误信息")
        if self.status is not RunStatus.FAILED and self.error is not None:
            raise ValueError("非 failed 状态不能携带错误信息")
        if _SAFE_RUN_ID.fullmatch(self.run_id) is None:
            raise ValueError("run_id 只能包含字母、数字、点、下划线和连字符")
        return self


class RedisRunStateStore:
    """Namespaced JSON run state with an explicit expiration time."""

    def __init__(
        self,
        client: RedisClient,
        *,
        namespace: str = "site_selection:run_state",
        ttl_seconds: int = 86_400,
    ) -> None:
        if client is None:
            raise ValueError("Redis 状态存储必须配置客户端")
        if _SAFE_NAMESPACE.fullmatch(namespace) is None:
            raise ValueError("Redis namespace 包含不安全字符")
        if ttl_seconds <= 0:
            raise ValueError("Redis TTL 必须大于 0")
        self._client = client
        self._namespace = namespace
        self._ttl_seconds = ttl_seconds

    @property
    def namespace(self) -> str:
        return self._namespace

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def save(self, state: RunState) -> None:
        payload = state.model_dump_json()
        self._client.set(
            self._key(state.run_id),
            payload,
            ex=self._ttl_seconds,
        )

    def get(self, run_id: str) -> RunState | None:
        payload = self._client.get(self._key(run_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return RunState.model_validate_json(payload)

    def update(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: str | None = None,
        details: dict[str, Any] | None = None,
        updated_at: datetime | None = None,
    ) -> RunState:
        state = RunState(
            run_id=run_id,
            status=status,
            updated_at=updated_at or datetime.now(timezone.utc),
            error=error,
            details=details or {},
        )
        self.save(state)
        return state

    def delete(self, run_id: str) -> bool:
        return bool(self._client.delete(self._key(run_id)))

    def ttl(self, run_id: str) -> int:
        return self._client.ttl(self._key(run_id))

    def _key(self, run_id: str) -> str:
        if _SAFE_RUN_ID.fullmatch(run_id) is None:
            raise ValueError("run_id 只能包含字母、数字、点、下划线和连字符")
        return f"{self._namespace}:{run_id}"
