from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.services.site_selection_queue import (
    QueuedSiteSelectionRunService,
    RQSiteSelectionJobQueue,
    RQQueueSettings,
)
from app.services.site_selection_run_service import (
    SiteSelectionRunConflictError,
)
from practice.site_selection.storage import (
    RedisSiteSelectionRuntimeStore,
    RunEventType,
    RunStatus,
)
from tests.storage_fakes import FakeRedis
from tests.test_site_selection_run_service import command, service


@dataclass
class FakeJobQueue:
    fail_enqueue: bool = False
    enqueued: list[tuple[str, object]] = field(default_factory=list)
    cancelled: list[tuple[str, bool]] = field(default_factory=list)
    closed: bool = False

    def job_id_for(self, run_id: str) -> str:
        return f"site-selection-{run_id}"

    def enqueue(self, run_id: str, queued_command) -> None:
        if self.fail_enqueue:
            raise RuntimeError("secret queue diagnostics")
        self.enqueued.append((run_id, queued_command))

    def cancel(self, job_id: str, *, running: bool) -> None:
        self.cancelled.append((job_id, running))

    def close(self) -> None:
        self.closed = True


@dataclass
class CapturingRQQueue:
    calls: list[dict[str, object]] = field(default_factory=list)

    def enqueue_call(self, **kwargs):
        self.calls.append(kwargs)


def queued_service(*, queue=None, run_ids=None, store=None, runner=None):
    executor = service(
        store=store,
        run_ids=run_ids,
        **({"runner": runner} if runner is not None else {}),
    )
    return executor, QueuedSiteSelectionRunService(
        executor,
        queue or FakeJobQueue(),
    )


def test_async_create_only_prepares_and_enqueues_work() -> None:
    def forbidden_runner(*args):
        raise AssertionError("API process must not execute workflow")

    queue = FakeJobQueue()
    executor, queued = queued_service(queue=queue, runner=forbidden_runner)

    state = queued.create_run(command())

    assert state.status is RunStatus.QUEUED
    assert state.details["queue_job_id"] == "site-selection-run-001"
    assert [item[0] for item in queue.enqueued] == ["run-001"]
    assert [event.event_type for event in executor.get_events("run-001")] == [
        RunEventType.CREATED,
        RunEventType.ENQUEUED,
    ]


def test_async_idempotency_enqueues_exactly_once() -> None:
    queue = FakeJobQueue()
    _, queued = queued_service(
        queue=queue,
        run_ids=["run-001", "run-002"],
    )

    first = queued.create_run(command(), idempotency_key="async-client-001")
    second = queued.create_run(command(), idempotency_key="async-client-001")

    assert first == second
    assert len(queue.enqueued) == 1


def test_enqueue_failure_is_sanitized_and_persisted() -> None:
    queue = FakeJobQueue(fail_enqueue=True)
    executor, queued = queued_service(queue=queue)

    state = queued.create_run(command())

    assert state.status is RunStatus.FAILED
    assert state.error == "选址任务入队失败：RuntimeError"
    assert "secret queue diagnostics" not in state.model_dump_json()
    assert executor.get_events(state.run_id)[-1].event_type is RunEventType.FAILED


def test_queued_cancel_is_idempotent() -> None:
    queue = FakeJobQueue()
    executor, queued = queued_service(queue=queue)
    created = queued.create_run(command())

    first = queued.cancel_run(created.run_id)
    second = queued.cancel_run(created.run_id)

    assert first.status is RunStatus.CANCELLED
    assert second == first
    assert queue.cancelled == [("site-selection-run-001", False)]
    assert executor.execute_run(created.run_id, command()) == first


def test_running_cancel_uses_worker_stop_command() -> None:
    store = RedisSiteSelectionRuntimeStore(FakeRedis())
    queue = FakeJobQueue()
    executor, queued = queued_service(queue=queue, store=store)
    created = queued.create_run(command())
    store.run_states.update(
        created.run_id,
        RunStatus.RUNNING,
        details=created.details,
        updated_at=created.updated_at,
    )

    state = queued.cancel_run(created.run_id)

    assert state.status is RunStatus.CANCELLED
    assert queue.cancelled == [("site-selection-run-001", True)]


def test_completed_run_cannot_be_cancelled() -> None:
    queue = FakeJobQueue()
    executor, queued = queued_service(queue=queue)
    created = queued.create_run(command())
    completed = executor.execute_run(created.run_id, command())

    assert completed.status is RunStatus.COMPLETED
    with pytest.raises(SiteSelectionRunConflictError, match="completed"):
        queued.cancel_run(completed.run_id)


def test_queue_settings_reject_blank_name_and_non_positive_ttls() -> None:
    with pytest.raises(ValueError, match="blank"):
        RQQueueSettings(queue_name=" ")
    with pytest.raises(ValueError, match="positive"):
        RQQueueSettings(job_timeout_seconds=0)
    assert RQQueueSettings(queue_name=" test-queue ").queue_name == "test-queue"


def test_rq_adapter_uses_enqueue_call_timeout_parameter() -> None:
    backend = CapturingRQQueue()
    adapter = RQSiteSelectionJobQueue.__new__(RQSiteSelectionJobQueue)
    adapter._settings = RQQueueSettings(job_timeout_seconds=123)
    adapter._queue = backend

    adapter.enqueue("run-001", command())

    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert call["timeout"] == 123
    assert "job_timeout" not in call
