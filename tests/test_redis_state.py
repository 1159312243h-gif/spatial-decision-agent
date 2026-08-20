from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from practice.site_selection.storage.redis_state import (
    RedisRunStateStore,
    RunState,
    RunStatus,
)
from tests.storage_fakes import FakeRedis


NOW = datetime(2026, 8, 19, 15, 0, tzinfo=timezone.utc)


def test_run_state_is_namespaced_and_has_ttl() -> None:
    client = FakeRedis()
    store = RedisRunStateStore(
        client,
        namespace="site_selection:test_runs",
        ttl_seconds=600,
    )

    state = store.update(
        "run-001",
        RunStatus.RUNNING,
        details={"project_type": "shopping_mall"},
        updated_at=NOW,
    )

    assert "site_selection:test_runs:run-001" in client.values
    assert store.ttl("run-001") == 600
    assert store.get("run-001") == state


def test_failed_state_requires_error_and_round_trips() -> None:
    store = RedisRunStateStore(FakeRedis(), ttl_seconds=30)

    state = store.update(
        "run-002",
        RunStatus.FAILED,
        error="spatial validation failed",
        updated_at=NOW,
    )

    assert store.get("run-002") == state
    assert state.error == "spatial validation failed"


def test_non_failed_state_rejects_error() -> None:
    with pytest.raises(ValidationError, match="非失败"):
        RunState(
            run_id="run-003",
            status=RunStatus.COMPLETED,
            updated_at=NOW,
            error="stale error",
        )


def test_timed_out_state_requires_error_but_cancelled_does_not() -> None:
    with pytest.raises(ValidationError, match="timed_out"):
        RunState(
            run_id="run-timeout",
            status=RunStatus.TIMED_OUT,
            updated_at=NOW,
        )

    cancelled = RunState(
        run_id="run-cancelled",
        status=RunStatus.CANCELLED,
        updated_at=NOW,
    )

    assert cancelled.error is None


def test_invalid_namespace_and_run_id_are_rejected() -> None:
    with pytest.raises(ValueError, match="namespace"):
        RedisRunStateStore(FakeRedis(), namespace="bad namespace")
    store = RedisRunStateStore(FakeRedis())
    with pytest.raises(ValueError, match="run_id"):
        store.get("../run")


def test_delete_removes_state() -> None:
    store = RedisRunStateStore(FakeRedis(), ttl_seconds=60)
    store.update("run-004", RunStatus.QUEUED, updated_at=NOW)

    assert store.delete("run-004") is True
    assert store.get("run-004") is None
    assert store.ttl("run-004") == -2


def test_transition_only_updates_from_expected_status() -> None:
    store = RedisRunStateStore(FakeRedis(), ttl_seconds=60)
    store.update("run-cas", RunStatus.QUEUED, updated_at=NOW)

    running = store.transition(
        "run-cas",
        {RunStatus.QUEUED},
        RunStatus.RUNNING,
        updated_at=NOW,
    )
    stale_cancel = store.transition(
        "run-cas",
        {RunStatus.QUEUED},
        RunStatus.CANCELLED,
        updated_at=NOW,
    )

    assert running is not None
    assert stale_cancel is None
    assert store.get("run-cas").status is RunStatus.RUNNING
