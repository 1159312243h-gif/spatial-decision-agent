from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.site_selection import (
    SiteSelectionAnalysisCreate,
    SiteSelectionPOIPreviewRequest,
)
from app.services.site_selection_run_service import SiteSelectionRunService
from app.services.site_selection_service import (
    SiteSelectionRuntime,
    SiteSelectionRuntimeRegistry,
)
from practice.site_selection import (
    ProjectType,
    SiteSelectionWorkflowDependencies,
    run_parallel_site_selection_workflow,
)
from practice.site_selection.storage import (
    RedisSiteSelectionRuntimeStore,
    RunEventType,
    RunStatus,
)
from tests.storage_fakes import FakeRedis
from tests.test_site_selection_workflow import dependencies, manifests


NOW = datetime(2026, 8, 21, 14, 0, tzinfo=timezone.utc)


def command() -> SiteSelectionAnalysisCreate:
    return SiteSelectionAnalysisCreate.model_validate(
        {
            "project_type": "shopping_mall",
            "candidate_parcels": [
                {
                    "parcel_id": "A01",
                    "longitude": 121.47,
                    "latitude": 31.23,
                    "geometry_dataset_id": "parcel-workflow-2026-08",
                }
            ],
        }
    )


def preview_command() -> SiteSelectionPOIPreviewRequest:
    return SiteSelectionPOIPreviewRequest(
        project_type=ProjectType.SHOPPING_MALL,
        longitude=121.47,
        latitude=31.23,
        categories=["地铁站"],
        radius_m=1_000,
        limit=20,
    )


def runtime(*, configured_dependencies=None) -> SiteSelectionRuntime:
    return SiteSelectionRuntime(
        project_type=ProjectType.SHOPPING_MALL,
        datasets=manifests(),
        dependencies=configured_dependencies or dependencies(),
    )


def service(
    *,
    store=None,
    configured_runtime=None,
    runner=run_parallel_site_selection_workflow,
    run_ids=None,
) -> SiteSelectionRunService:
    run_id_iter = iter(run_ids or ["run-001"])
    return SiteSelectionRunService(
        SiteSelectionRuntimeRegistry(
            {
                ProjectType.SHOPPING_MALL: (
                    configured_runtime or runtime()
                )
            }
        ),
        store or RedisSiteSelectionRuntimeStore(FakeRedis()),
        workflow_runner=runner,
        clock=lambda: NOW,
        run_id_factory=lambda: next(run_id_iter),
        request_id_factory=lambda: "analysis-run-001",
    )


def test_create_run_persists_completed_state_and_ordered_events() -> None:
    store = RedisSiteSelectionRuntimeStore(
        FakeRedis(),
        run_ttl_seconds=600,
        idempotency_ttl_seconds=600,
        event_ttl_seconds=600,
    )
    run_service = service(store=store)

    state = run_service.create_run(command())

    assert state.status is RunStatus.COMPLETED
    assert state.details["analysis"]["status"] == "completed"
    assert run_service.get_run("run-001") == state
    assert [event.event_type for event in run_service.get_events("run-001")] == [
        RunEventType.CREATED,
        RunEventType.STARTED,
        RunEventType.COMPLETED,
    ]
    assert store.run_states.ttl("run-001") == 600


def test_repeated_idempotency_key_returns_same_run_without_rerun() -> None:
    calls = []

    def runner(request, datasets, configured_dependencies):
        calls.append(request.request_id)
        return run_parallel_site_selection_workflow(
            request,
            datasets,
            configured_dependencies,
        )

    run_service = service(runner=runner, run_ids=["run-001", "run-002"])

    first = run_service.create_run(command(), idempotency_key="client-001")
    second = run_service.create_run(command(), idempotency_key="client-001")

    assert first.run_id == second.run_id == "run-001"
    assert calls == ["analysis-run-001"]


def test_unknown_runner_exception_is_sanitized_in_state_and_event() -> None:
    def exploding_runner(*args):
        raise RuntimeError("secret-token=must-not-leak")

    run_service = service(runner=exploding_runner)

    state = run_service.create_run(command())

    assert state.status is RunStatus.FAILED
    assert state.error == "选址运行发生未处理异常：RuntimeError"
    assert "secret-token" not in state.model_dump_json()
    assert run_service.get_events("run-001")[-1].event_type is RunEventType.FAILED


def test_poi_preview_is_cached_after_first_gateway_call() -> None:
    configured = dependencies()

    class CountingGateway:
        def __init__(self):
            self.calls = 0
            self.cache_token = "counting:v1"

        def search(self, query):
            self.calls += 1
            return configured.poi_gateway.search(query)

    gateway = CountingGateway()
    configured_dependencies = SiteSelectionWorkflowDependencies(
        poi_gateway=gateway,
        poi_scoring_config=configured.poi_scoring_config,
        spatial_gateway=configured.spatial_gateway,
        constraint_specs=configured.constraint_specs,
        rules=configured.rules,
        buffer_distance_m=configured.buffer_distance_m,
    )
    run_service = service(
        configured_runtime=runtime(
            configured_dependencies=configured_dependencies
        )
    )

    first = run_service.preview_poi(preview_command())
    second = run_service.preview_poi(preview_command())

    assert first.cached is False
    assert second.cached is True
    assert second.feature_set == first.feature_set
    assert gateway.calls == 1

    refreshed_command = preview_command().model_copy(
        update={"refresh": True}
    )
    refreshed = run_service.preview_poi(refreshed_command)

    assert refreshed.cached is False
    assert gateway.calls == 2

    gateway.cache_token = "counting:v2"
    after_version_change = run_service.preview_poi(preview_command())

    assert after_version_change.cached is False
    assert gateway.calls == 3
