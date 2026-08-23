from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_CLAIM_LOCK_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then
  return -1
end
local claimed = redis.call('SET', KEYS[2], ARGV[1], 'NX', 'EX', ARGV[2])
if claimed then
  return 1
end
return 0
"""
_RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class SupervisorSessionEventType(StrEnum):
    STARTED = "started"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMATION_REJECTED = "confirmation_rejected"
    CONFIRMED = "confirmed"
    ANALYSIS_SUBMITTED = "analysis_submitted"
    ANALYSIS_COMPLETED = "analysis_completed"
    ANALYSIS_FAILED = "analysis_failed"
    ANALYSIS_CANCELLED = "analysis_cancelled"
    ANALYSIS_TIMED_OUT = "analysis_timed_out"
    ANALYSIS_RESUME_DEFERRED = "analysis_resume_deferred"
    COMPLETED = "completed"


class SupervisorSessionLeaseExpiredError(RuntimeError):
    """Raised when a confirmation races with session lease expiry."""


class SupervisorSessionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    event_type: SupervisorSessionEventType
    occurred_at: datetime
    checkpoint_id: str = Field(min_length=1)
    analysis_run_id: str | None = None
    reviewer_id: str | None = None
    selected_candidate_ids: list[str] = Field(default_factory=list)
    error_type: str | None = None

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Supervisor 审计时间必须包含时区")
        return value


class RedisSupervisorSessionCoordinator:
    """Redis lease, distributed lock and audit log for Supervisor sessions."""

    def __init__(
        self,
        client,
        *,
        namespace: str = "site_selection",
        session_ttl_seconds: int = 7_200,
        lock_ttl_seconds: int = 120,
    ) -> None:
        normalized = namespace.strip().strip(":")
        if not normalized:
            raise ValueError("Supervisor Redis namespace 不能为空")
        if session_ttl_seconds <= 0 or lock_ttl_seconds <= 0:
            raise ValueError("Supervisor session 和 lock TTL 必须是正数")
        if lock_ttl_seconds >= session_ttl_seconds:
            raise ValueError("Supervisor lock TTL 必须短于 session TTL")
        self._client = client
        self._namespace = normalized
        self._session_ttl_seconds = session_ttl_seconds
        self._lock_ttl_seconds = lock_ttl_seconds

    def activate(self, session_id: str, checkpoint_id: str) -> None:
        self._validate(session_id)
        self._client.set(
            self._session_key(session_id),
            checkpoint_id,
            ex=self._session_ttl_seconds,
        )
        self._client.expire(
            self._events_key(session_id),
            self._session_ttl_seconds,
        )

    def is_active(self, session_id: str) -> bool:
        self._validate(session_id)
        return self._client.get(self._session_key(session_id)) is not None

    def ttl(self, session_id: str) -> int:
        self._validate(session_id)
        return int(self._client.ttl(self._session_key(session_id)))

    def acquire_transition(self, session_id: str) -> str | None:
        self._validate(session_id)
        token = str(uuid4())
        result = int(
            self._client.eval(
                _CLAIM_LOCK_SCRIPT,
                2,
                self._session_key(session_id),
                self._lock_key(session_id),
                token,
                self._lock_ttl_seconds,
            )
        )
        if result == -1:
            raise SupervisorSessionLeaseExpiredError(session_id)
        return token if result == 1 else None

    def release_transition(self, session_id: str, token: str) -> None:
        self._validate(session_id)
        self._client.eval(
            _RELEASE_LOCK_SCRIPT,
            1,
            self._lock_key(session_id),
            token,
        )

    def acquire_confirmation(self, session_id: str) -> str | None:
        return self.acquire_transition(session_id)

    def release_confirmation(self, session_id: str, token: str) -> None:
        self.release_transition(session_id, token)

    def append_event(self, event: SupervisorSessionEvent) -> None:
        self._validate(event.session_id)
        key = self._events_key(event.session_id)
        self._client.rpush(key, event.model_dump_json())
        self._client.expire(key, self._session_ttl_seconds)

    def list_events(self, session_id: str) -> list[SupervisorSessionEvent]:
        self._validate(session_id)
        return [
            SupervisorSessionEvent.model_validate_json(_decode(item))
            for item in self._client.lrange(
                self._events_key(session_id),
                0,
                -1,
            )
        ]

    def deactivate(self, session_id: str) -> None:
        self._validate(session_id)
        self._client.delete(self._session_key(session_id))
        self._client.delete(self._lock_key(session_id))

    def _session_key(self, session_id: str) -> str:
        return f"{self._namespace}:supervisor:session:{session_id}"

    def _lock_key(self, session_id: str) -> str:
        return f"{self._namespace}:supervisor:lock:{session_id}"

    def _events_key(self, session_id: str) -> str:
        return f"{self._namespace}:supervisor:events:{session_id}"

    @staticmethod
    def _validate(session_id: str) -> None:
        if _SAFE_SESSION_ID.fullmatch(session_id) is None:
            raise ValueError(
                "Supervisor session_id 只能包含字母、数字、点、下划线和连字符"
            )


def _decode(value: bytes | str) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value
