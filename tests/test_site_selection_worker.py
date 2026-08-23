from __future__ import annotations

from types import SimpleNamespace

from app.services import site_selection_worker
from app.services.site_selection_run_service import SiteSelectionRunService
from app.services.site_selection_worker import record_site_selection_job_failure
from app.services.site_selection_service import SiteSelectionRuntimeRegistry
from practice.site_selection import ProjectType
from practice.site_selection.storage import (
    RedisSiteSelectionRuntimeStore,
    RunState,
    RunStatus,
)
from tests.storage_fakes import FakeRedis
from tests.test_site_selection_run_service import command, runtime


def configured_store():
    client = FakeRedis()
    store = RedisSiteSelectionRuntimeStore(client, namespace="worker_test")
    return client, store


def prepared_run(store):
    provider = SiteSelectionRuntimeRegistry(
        {ProjectType.SHOPPING_MALL: runtime()}
    )
    executor = SiteSelectionRunService(
        provider,
        store,
        run_id_factory=lambda: "run-worker-001",
        request_id_factory=lambda: "analysis-worker-001",
    )
    return provider, executor.prepare_run(command()).state


def test_worker_executes_prepared_run_and_closes_runtime(monkeypatch) -> None:
    _, store = configured_store()
    provider, prepared = prepared_run(store)
    bootstrap = SimpleNamespace(
        runtime_provider=provider,
        run_store=store,
        report_store=None,
        explainer=None,
        closed=False,
    )
    bootstrap.close = lambda: setattr(bootstrap, "closed", True)
    captured = {}

    def fake_bootstrap(values, *, include_mcp):
        captured.update(values)
        assert include_mcp is False
        return bootstrap

    monkeypatch.setattr(
        site_selection_worker,
        "build_site_selection_bootstrap_from_environment",
        fake_bootstrap,
    )

    result = site_selection_worker.execute_site_selection_job(
        run_id=prepared.run_id,
        command_payload=command().model_dump(mode="json"),
    )

    assert result["status"] == "completed"
    assert store.run_states.get(prepared.run_id).status is RunStatus.COMPLETED
    assert captured["SITE_SELECTION_RUN_MODE"] == "sync"
    assert bootstrap.closed is True


def test_timeout_callback_records_timed_out_state() -> None:
    client, store = configured_store()
    _, prepared = prepared_run(store)
    job = SimpleNamespace(
        meta={
            "run_id": prepared.run_id,
            "runtime_namespace": "worker_test",
            "run_ttl_seconds": 86_400,
            "event_ttl_seconds": 86_400,
        }
    )

    record_site_selection_job_failure(
        job,
        client,
        TimeoutError,
        TimeoutError("secret"),
        None,
    )

    state = store.run_states.get(prepared.run_id)
    assert state.status is RunStatus.TIMED_OUT
    assert state.error == "选址任务执行超时：TimeoutError"
    assert "secret" not in state.model_dump_json()


def test_failure_callback_preserves_cancelled_state() -> None:
    client, store = configured_store()
    _, prepared = prepared_run(store)
    store.run_states.update(
        prepared.run_id,
        RunStatus.CANCELLED,
        details=prepared.details,
        updated_at=prepared.updated_at,
    )
    job = SimpleNamespace(
        meta={
            "run_id": prepared.run_id,
            "runtime_namespace": "worker_test",
        }
    )

    record_site_selection_job_failure(
        job,
        client,
        RuntimeError,
        RuntimeError("secret"),
        None,
    )

    assert store.run_states.get(prepared.run_id).status is RunStatus.CANCELLED


def test_generic_failure_callback_records_sanitized_failure() -> None:
    client, store = configured_store()
    _, prepared = prepared_run(store)
    job = SimpleNamespace(
        meta={
            "run_id": prepared.run_id,
            "runtime_namespace": "worker_test",
        }
    )

    record_site_selection_job_failure(
        job,
        client,
        RuntimeError,
        RuntimeError("secret-token"),
        None,
    )

    state = store.run_states.get(prepared.run_id)
    assert state.status is RunStatus.FAILED
    assert state.error == "选址 Worker 执行失败：RuntimeError"
    assert "secret-token" not in state.model_dump_json()


def test_worker_resumes_correlated_supervisor_after_terminal_run(
    monkeypatch,
) -> None:
    completed = RunState(
        run_id="run-worker-terminal-001",
        status=RunStatus.COMPLETED,
        updated_at=prepared_run(configured_store()[1])[1].updated_at,
        details={"supervisor_session_id": "supervisor-worker-001"},
    )
    captured = {}

    class FakeSupervisorService:
        def complete_analysis(self, session_id, state):
            captured["session_id"] = session_id
            captured["state"] = state

    def fake_factory(**kwargs):
        captured["factory"] = kwargs
        return FakeSupervisorService()

    monkeypatch.setattr(
        site_selection_worker,
        "build_site_selection_supervisor_service",
        fake_factory,
    )
    bootstrap = SimpleNamespace(
        runtime_provider=object(),
        run_store=object(),
        report_store=None,
        explainer=None,
        supervisor_checkpointer=object(),
        supervisor_coordinator=object(),
    )

    resumed = site_selection_worker.resume_supervisor_for_terminal_run(
        bootstrap,
        completed,
        expected_session_id="supervisor-worker-001",
        run_service=object(),
    )

    assert resumed is True
    assert captured["session_id"] == "supervisor-worker-001"
    assert captured["state"] == completed
    assert captured["factory"]["checkpointer"] is (
        bootstrap.supervisor_checkpointer
    )


def test_worker_does_not_resume_mismatched_supervisor() -> None:
    state = RunState(
        run_id="run-worker-mismatch-001",
        status=RunStatus.CANCELLED,
        updated_at=prepared_run(configured_store()[1])[1].updated_at,
        details={"supervisor_session_id": "supervisor-a"},
    )
    bootstrap = SimpleNamespace(
        supervisor_checkpointer=object(),
        supervisor_coordinator=object(),
    )

    try:
        site_selection_worker.resume_supervisor_for_terminal_run(
            bootstrap,
            state,
            expected_session_id="supervisor-b",
        )
    except RuntimeError as exc:
        assert "correlation" in str(exc)
    else:
        raise AssertionError("错配的 Supervisor correlation 必须被拒绝")
