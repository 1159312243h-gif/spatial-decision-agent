from datetime import datetime, timezone

import pytest

from practice.site_selection.storage import (
    RedisSupervisorSessionCoordinator,
    SupervisorSessionEvent,
    SupervisorSessionEventType,
    SupervisorSessionLeaseExpiredError,
)
from tests.storage_fakes import FakeRedis


class SupervisorFakeRedis(FakeRedis):
    def eval(self, script: str, numkeys: int, *keys_and_args) -> int:
        del script
        if numkeys == 2 and len(keys_and_args) == 4:
            session_key, lock_key, token, ttl = keys_and_args
            if session_key not in self.values:
                return -1
            if lock_key in self.values:
                return 0
            self.values[lock_key] = token
            self.expirations[lock_key] = int(ttl)
            return 1
        if numkeys == 1 and len(keys_and_args) == 2:
            key, token = keys_and_args
            if self.values.get(key) != token:
                return 0
            self.delete(key)
            return 1
        raise ValueError("unexpected Supervisor lock script arguments")


def test_redis_supervisor_coordinates_lease_lock_and_audit_events() -> None:
    redis = SupervisorFakeRedis()
    coordinator = RedisSupervisorSessionCoordinator(
        redis,
        namespace="fixture",
        session_ttl_seconds=7_200,
        lock_ttl_seconds=120,
    )

    coordinator.activate("session-001", "checkpoint-001")
    token = coordinator.acquire_confirmation("session-001")

    assert coordinator.is_active("session-001") is True
    assert coordinator.ttl("session-001") == 7_200
    assert token is not None
    assert coordinator.acquire_confirmation("session-001") is None

    coordinator.release_confirmation("session-001", "wrong-token")
    assert coordinator.acquire_confirmation("session-001") is None
    coordinator.release_confirmation("session-001", token)
    assert coordinator.acquire_confirmation("session-001") is not None

    event = SupervisorSessionEvent(
        session_id="session-001",
        event_type=SupervisorSessionEventType.CONFIRMED,
        occurred_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        checkpoint_id="checkpoint-002",
        reviewer_id="planner-001",
        selected_candidate_ids=["candidate-001"],
    )
    coordinator.append_event(event)

    assert coordinator.list_events("session-001") == [event]
    assert redis.expirations["fixture:supervisor:events:session-001"] == 7_200


def test_redis_supervisor_rejects_unsafe_ids_and_invalid_ttls() -> None:
    with pytest.raises(ValueError, match="短于"):
        RedisSupervisorSessionCoordinator(
            SupervisorFakeRedis(),
            session_ttl_seconds=60,
            lock_ttl_seconds=60,
        )

    coordinator = RedisSupervisorSessionCoordinator(SupervisorFakeRedis())
    with pytest.raises(ValueError, match="只能包含"):
        coordinator.is_active("unsafe/session")

    with pytest.raises(SupervisorSessionLeaseExpiredError):
        coordinator.acquire_confirmation("expired-session")
