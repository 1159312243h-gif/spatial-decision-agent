from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from app.schemas.site_selection import SiteSelectionAnalysisCreate
from app.services.site_selection_run_service import (
    POIPreviewResult,
    SiteSelectionRunConflictError,
    SiteSelectionRunService,
)
from practice.site_selection.storage import RunEvent, RunState, RunStatus


class SiteSelectionJobQueue(Protocol):
    def job_id_for(self, run_id: str) -> str: ...

    def enqueue(
        self,
        run_id: str,
        command: SiteSelectionAnalysisCreate,
        *,
        supervisor_session_id: str | None = None,
    ) -> None: ...

    def cancel(self, job_id: str, *, running: bool) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class RQQueueSettings:
    queue_name: str = "site-selection"
    job_timeout_seconds: int = 180
    result_ttl_seconds: int = 3_600
    failure_ttl_seconds: int = 86_400
    runtime_namespace: str = "site_selection:fixture"
    run_ttl_seconds: int = 86_400
    event_ttl_seconds: int = 86_400

    def __post_init__(self) -> None:
        normalized_name = self.queue_name.strip()
        if not normalized_name:
            raise ValueError("RQ queue name cannot be blank")
        object.__setattr__(self, "queue_name", normalized_name)
        values = (
            self.job_timeout_seconds,
            self.result_ttl_seconds,
            self.failure_ttl_seconds,
            self.run_ttl_seconds,
            self.event_ttl_seconds,
        )
        if any(value <= 0 for value in values):
            raise ValueError("RQ timeouts and TTLs must be positive")


class RQSiteSelectionJobQueue:
    """RQ adapter; Redis credentials stay in the connection, not the job payload."""

    def __init__(self, connection, settings: RQQueueSettings) -> None:
        if connection is None:
            raise ValueError("RQ queue requires a Redis connection")
        from rq import Queue

        self._connection = connection
        self._settings = settings
        self._queue = Queue(settings.queue_name, connection=connection)

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        settings: RQQueueSettings,
    ) -> RQSiteSelectionJobQueue:
        from redis import Redis

        return cls(Redis.from_url(redis_url), settings)

    def job_id_for(self, run_id: str) -> str:
        return f"site-selection-{run_id}"

    @property
    def job_timeout_seconds(self) -> int:
        return self._settings.job_timeout_seconds

    def enqueue(
        self,
        run_id: str,
        command: SiteSelectionAnalysisCreate,
        *,
        supervisor_session_id: str | None = None,
    ) -> None:
        from app.services.site_selection_worker import (
            execute_site_selection_job,
            record_site_selection_job_failure,
        )

        self._queue.enqueue_call(
            func=execute_site_selection_job,
            kwargs={
                "run_id": run_id,
                "command_payload": command.model_dump(mode="json"),
                "supervisor_session_id": supervisor_session_id,
            },
            job_id=self.job_id_for(run_id),
            timeout=self._settings.job_timeout_seconds,
            result_ttl=self._settings.result_ttl_seconds,
            failure_ttl=self._settings.failure_ttl_seconds,
            on_failure=record_site_selection_job_failure,
            meta={
                "run_id": run_id,
                "runtime_namespace": self._settings.runtime_namespace,
                "run_ttl_seconds": self._settings.run_ttl_seconds,
                "event_ttl_seconds": self._settings.event_ttl_seconds,
                "supervisor_session_id": supervisor_session_id,
            },
        )

    def cancel(self, job_id: str, *, running: bool) -> None:
        from rq.command import send_stop_job_command
        from rq.job import Job

        job = Job.fetch(job_id, connection=self._connection)
        if running:
            send_stop_job_command(self._connection, job_id)
        else:
            job.cancel()

    def close(self) -> None:
        close = getattr(self._connection, "close", None)
        if callable(close):
            close()


class QueuedSiteSelectionRunService:
    """Application facade that submits execution to a dedicated RQ worker."""

    def __init__(
        self,
        executor: SiteSelectionRunService,
        queue: SiteSelectionJobQueue,
        *,
        stale_run_grace_seconds: int = 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if executor is None or queue is None:
            raise ValueError("queued run service requires executor and queue")
        if stale_run_grace_seconds < 0:
            raise ValueError("stale run grace period cannot be negative")
        self._executor = executor
        self._queue = queue
        raw_timeout = getattr(queue, "job_timeout_seconds", None)
        self._job_timeout_seconds = (
            int(raw_timeout)
            if isinstance(raw_timeout, (int, float)) and raw_timeout > 0
            else None
        )
        self._stale_run_grace_seconds = stale_run_grace_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def create_run(
        self,
        command: SiteSelectionAnalysisCreate,
        *,
        idempotency_key: str | None = None,
        supervisor_session_id: str | None = None,
    ) -> RunState:
        prepared = self._executor.prepare_run(
            command,
            idempotency_key=idempotency_key,
            supervisor_session_id=supervisor_session_id,
        )
        if not prepared.created:
            return prepared.state

        run_id = prepared.state.run_id
        job_id = self._queue.job_id_for(run_id)
        enqueued = self._executor.mark_enqueued(run_id, job_id=job_id)
        try:
            self._queue.enqueue(
                run_id,
                command,
                supervisor_session_id=supervisor_session_id,
            )
        except Exception as exc:
            return self._executor.mark_enqueue_failed(run_id, exc)
        return enqueued

    def cancel_run(self, run_id: str) -> RunState:
        state = self._executor.get_run(run_id)
        if state.status is RunStatus.CANCELLED:
            return state
        if state.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
            raise SiteSelectionRunConflictError(
                f"只有 queued 或 running 运行可以取消：{state.status.value}"
            )
        job_id = state.details.get("queue_job_id")
        if not isinstance(job_id, str) or not job_id:
            raise SiteSelectionRunConflictError("运行缺少可取消的 queue_job_id")
        running = state.status is RunStatus.RUNNING
        cancelled = self._executor.mark_cancelled(run_id)
        try:
            self._queue.cancel(job_id, running=running)
        except Exception:
            # The persisted terminal state prevents a late worker from
            # starting or publishing results after cancellation.
            return cancelled
        return cancelled

    def get_run(self, run_id: str) -> RunState:
        state = self._executor.get_run(run_id)
        if (
            state.status is RunStatus.RUNNING
            and self._job_timeout_seconds is not None
            and (self._clock() - state.updated_at).total_seconds()
            > self._job_timeout_seconds + self._stale_run_grace_seconds
        ):
            return self._executor.mark_timed_out(
                run_id,
                error_type="StaleWorkerTimeout",
            )
        return state

    def get_events(self, run_id: str) -> list[RunEvent]:
        return self._executor.get_events(run_id)

    def get_report_path(self, run_id: str) -> str:
        return self._executor.get_report_path(run_id)

    def acknowledge_human_review(
        self,
        run_id: str,
        *,
        note: str | None = None,
    ) -> RunState:
        return self._executor.acknowledge_human_review(run_id, note=note)

    def preview_poi(
        self,
        command,
    ) -> POIPreviewResult:
        return self._executor.preview_poi(command)
