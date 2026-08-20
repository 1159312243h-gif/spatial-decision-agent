from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from app.schemas.site_selection import SiteSelectionAnalysisCreate
from app.services.site_selection_run_service import SiteSelectionRunService
from app.site_selection_bootstrap import build_site_selection_bootstrap_from_environment
from practice.site_selection.storage import (
    RedisSiteSelectionRuntimeStore,
    RunEvent,
    RunEventType,
    RunStatus,
)


def execute_site_selection_job(
    *,
    run_id: str,
    command_payload: dict[str, Any],
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
    if state is None or state.status in {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.TIMED_OUT,
    }:
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
    return True
