from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.schemas.site_selection import SiteSelectionAnalysisCreate
from app.services.site_selection_run_service import SiteSelectionRunService
from app.services.site_selection_supervisor import (
    build_site_selection_supervisor_service,
)
from app.site_selection_bootstrap import build_site_selection_bootstrap_from_environment
from practice.site_selection import CandidateDiscoveryService
from practice.site_selection.storage import (
    RedisSiteSelectionRuntimeStore,
    RunEvent,
    RunEventType,
    RunStatus,
)


logger = logging.getLogger(__name__)
TERMINAL_RUN_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
    RunStatus.TIMED_OUT,
}


def execute_site_selection_job(
    *,
    run_id: str,
    command_payload: dict[str, Any],
    supervisor_session_id: str | None = None,
) -> dict[str, Any]:
    values = dict(os.environ)
    values["SITE_SELECTION_RUN_MODE"] = "sync"
    bootstrap = build_site_selection_bootstrap_from_environment(
        values,
        include_mcp=False,
    )
    if bootstrap is None:
        raise RuntimeError("site-selection worker runtime is not configured")
    try:
        service = SiteSelectionRunService(
            bootstrap.runtime_provider,
            bootstrap.run_store,
            report_store=bootstrap.report_store,
            explainer=bootstrap.explainer,
        )
        state = service.execute_run(
            run_id,
            SiteSelectionAnalysisCreate.model_validate(command_payload),
        )
        _attempt_supervisor_resume(
            bootstrap,
            state,
            expected_session_id=supervisor_session_id,
            run_service=service,
        )
        return state.model_dump(mode="json")
    finally:
        bootstrap.close()


def record_site_selection_job_failure(
    job,
    connection,
    exc_type,
    exc_value,
    traceback,
) -> bool:
    del exc_value, traceback
    run_id = str(job.meta.get("run_id", ""))
    namespace = str(job.meta.get("runtime_namespace", "site_selection:fixture"))
    if not run_id:
        return True
    store = RedisSiteSelectionRuntimeStore(
        connection,
        namespace=namespace,
        run_ttl_seconds=int(job.meta.get("run_ttl_seconds", 86_400)),
        event_ttl_seconds=int(job.meta.get("event_ttl_seconds", 86_400)),
    )
    state = store.run_states.get(run_id)
    if state is None:
        return True
    if state.status in TERMINAL_RUN_STATUSES:
        _attempt_supervisor_resume_from_environment(
            state,
            expected_session_id=job.meta.get("supervisor_session_id"),
        )
        return True

    error_type = getattr(exc_type, "__name__", "WorkerError")
    is_timeout = "Timeout" in error_type
    status = RunStatus.TIMED_OUT if is_timeout else RunStatus.FAILED
    error = (
        f"选址任务执行超时：{error_type}"
        if is_timeout
        else f"选址 Worker 执行失败：{error_type}"
    )
    details = {**state.details, "worker_error_type": error_type}
    updated = store.run_states.transition(
        run_id,
        {RunStatus.QUEUED, RunStatus.RUNNING},
        status,
        error=error,
        details=details,
        updated_at=datetime.now(timezone.utc),
    )
    if updated is None:
        return True
    store.append_event(
        RunEvent(
            run_id=run_id,
            event_type=(
                RunEventType.TIMED_OUT if is_timeout else RunEventType.FAILED
            ),
            occurred_at=datetime.now(timezone.utc),
            details={"error": error},
        )
    )
    _attempt_supervisor_resume_from_environment(
        updated,
        expected_session_id=job.meta.get("supervisor_session_id"),
    )
    return True


def resume_supervisor_for_terminal_run(
    bootstrap,
    state,
    *,
    expected_session_id: str | None = None,
    run_service: SiteSelectionRunService | None = None,
) -> bool:
    """Resume the correlated Supervisor without changing the RunState."""

    if state.status not in TERMINAL_RUN_STATUSES:
        return False
    linked_session_id = state.details.get("supervisor_session_id")
    if not isinstance(linked_session_id, str) or not linked_session_id:
        return False
    if (
        expected_session_id is not None
        and str(expected_session_id).strip() != linked_session_id
    ):
        raise RuntimeError("worker Supervisor correlation does not match RunState")
    checkpointer = getattr(bootstrap, "supervisor_checkpointer", None)
    coordinator = getattr(bootstrap, "supervisor_coordinator", None)
    if checkpointer is None or coordinator is None:
        return False
    active_run_service = run_service or SiteSelectionRunService(
        bootstrap.runtime_provider,
        bootstrap.run_store,
        report_store=bootstrap.report_store,
        explainer=bootstrap.explainer,
    )
    discovery_service = CandidateDiscoveryService(
        bootstrap.runtime_provider,
        snapshot_store=bootstrap.run_store,
    )
    supervisor_service = build_site_selection_supervisor_service(
        discovery_runner=discovery_service.discover,
        run_service=active_run_service,
        checkpointer=checkpointer,
        coordinator=coordinator,
    )
    supervisor_service.complete_analysis(linked_session_id, state)
    return True


def _attempt_supervisor_resume(
    bootstrap,
    state,
    *,
    expected_session_id: str | None,
    run_service: SiteSelectionRunService | None = None,
) -> None:
    try:
        resume_supervisor_for_terminal_run(
            bootstrap,
            state,
            expected_session_id=expected_session_id,
            run_service=run_service,
        )
    except Exception as exc:
        # The RunState is already authoritative and terminal. A later
        # Supervisor GET performs the same idempotent reconciliation.
        logger.warning(
            "Supervisor resume deferred for run_id=%s error_type=%s",
            state.run_id,
            type(exc).__name__,
        )


def _attempt_supervisor_resume_from_environment(
    state,
    *,
    expected_session_id: str | None,
) -> None:
    linked_session_id = state.details.get("supervisor_session_id")
    if not isinstance(linked_session_id, str) or not linked_session_id:
        return
    values = dict(os.environ)
    values["SITE_SELECTION_RUN_MODE"] = "sync"
    bootstrap = None
    try:
        bootstrap = build_site_selection_bootstrap_from_environment(
            values,
            include_mcp=False,
        )
        if bootstrap is not None:
            _attempt_supervisor_resume(
                bootstrap,
                state,
                expected_session_id=expected_session_id,
            )
    except Exception as exc:
        logger.warning(
            "Supervisor failure reconciliation deferred for run_id=%s "
            "error_type=%s",
            state.run_id,
            type(exc).__name__,
        )
    finally:
        if bootstrap is not None:
            bootstrap.close()
