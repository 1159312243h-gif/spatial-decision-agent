from scripts.smoke_async_runtime import AsyncSmokeError, REQUIRED_EVENTS


def test_async_smoke_requires_the_complete_event_chain() -> None:
    assert REQUIRED_EVENTS == {
        "created",
        "enqueued",
        "started",
        "completed",
    }


def test_async_smoke_error_preserves_safe_runtime_diagnostics() -> None:
    error = AsyncSmokeError(
        "worker",
        "async worker did not complete the analysis",
        run_id="run-001",
        status="failed",
        run_error="选址任务入队失败：TypeError",
        event_types={"created", "enqueued", "failed"},
    )

    rendered = str(error)

    assert "stage=worker" in rendered
    assert "run_id=run-001" in rendered
    assert "status=failed" in rendered
    assert "run_error=选址任务入队失败：TypeError" in rendered
    assert "events=created,enqueued,failed" in rendered
