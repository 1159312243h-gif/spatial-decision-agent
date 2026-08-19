from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.schemas.site_selection import (
    SiteSelectionAnalysisCreate,
    SiteSelectionPOIPreviewRequest,
)
from app.services.site_selection_run_service import SiteSelectionRunService
from app.services.site_selection_artifacts import (
    FileSystemSiteSelectionReportStore,
    SiteSelectionReportNotFoundError,
)
from app.services.site_selection_explanation import (
    CandidateEvidenceNote,
    EvidenceExplanationStatus,
    SiteSelectionEvidenceExplanation,
)
from app.services.site_selection_service import (
    SiteSelectionRuntime,
    SiteSelectionRuntimeRegistry,
)
from practice.site_selection import (
    EvidenceReviewIssue,
    EvidenceReviewReport,
    EvidenceReviewStatus,
    ProjectType,
    ReviewIssueSeverity,
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
    report_store=None,
    explainer=None,
    monotonic=None,
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
        report_store=report_store,
        explainer=explainer,
        monotonic=monotonic,
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
    assert state.details["human_review"]["status"] == "pending"
    assert [item["stage"] for item in state.details["trace"]] == [
        "workflow",
        "human_review",
        "explanation",
        "report",
        "total",
    ]


def test_human_review_acknowledgement_is_audited_without_approving_result() -> None:
    run_service = service()
    initial = run_service.create_run(command())

    acknowledged = run_service.acknowledge_human_review(
        initial.run_id,
        note="Evidence reviewed by operator.",
    )

    review = acknowledged.details["human_review"]
    assert acknowledged.status is RunStatus.COMPLETED
    assert review["status"] == "acknowledged"
    assert review["note"] == "Evidence reviewed by operator."
    assert run_service.get_events(initial.run_id)[-1].event_type is (
        RunEventType.HUMAN_REVIEW_ACKNOWLEDGED
    )
    assert run_service.get_events(initial.run_id)[-1].details["boundary"] == (
        "acknowledgement_not_compliance_approval"
    )


def test_repeated_human_review_acknowledgement_is_idempotent() -> None:
    run_service = service()
    initial = run_service.create_run(command())

    first = run_service.acknowledge_human_review(
        initial.run_id,
        note="First operator review.",
    )
    second = run_service.acknowledge_human_review(
        initial.run_id,
        note="Ignored duplicate request.",
    )

    assert second == first
    assert second.details["human_review"]["note"] == "First operator review."
    assert [
        event.event_type
        for event in run_service.get_events(initial.run_id)
    ].count(RunEventType.HUMAN_REVIEW_ACKNOWLEDGED) == 1


def test_blocked_evidence_review_fails_run_with_sanitized_trace() -> None:
    def blocked_runner(request, datasets, configured_dependencies):
        result = run_parallel_site_selection_workflow(
            request,
            datasets,
            configured_dependencies,
        )
        blocked = EvidenceReviewReport(
            request_id=request.request_id,
            review_version="review-v1",
            status=EvidenceReviewStatus.BLOCKED,
            requires_human_review=False,
            issues=[
                EvidenceReviewIssue(
                    issue_code="gis_lineage_incomplete",
                    severity=ReviewIssueSeverity.BLOCKER,
                    message="Sensitive diagnostic details must not leak.",
                )
            ],
        )
        return result.model_copy(update={"evidence_review_report": blocked})

    run_service = service(runner=blocked_runner)

    state = run_service.create_run(command())

    assert state.status is RunStatus.FAILED
    assert state.error == "Run finalization failed: ValueError"
    assert "Sensitive diagnostic" not in state.error
    assert [item["stage"] for item in state.details["trace"]] == [
        "workflow",
        "human_review",
        "total",
    ]
    assert [item["status"] for item in state.details["trace"]] == [
        "succeeded",
        "failed",
        "failed",
    ]
    assert "human_review" not in state.details


def test_invalid_workflow_result_is_recorded_as_failure() -> None:
    run_service = service(runner=lambda *args: {"unexpected": "payload"})

    state = run_service.create_run(command())

    assert state.status is RunStatus.FAILED
    assert state.details["trace"][0]["stage"] == "workflow"
    assert state.details["trace"][0]["error_type"] == "ValidationError"
    assert state.details["trace"][-1]["status"] == "failed"


def test_completed_run_generates_downloadable_report(tmp_path) -> None:
    report_store = FileSystemSiteSelectionReportStore(tmp_path)
    run_service = service(report_store=report_store)

    state = run_service.create_run(command())

    assert state.status is RunStatus.COMPLETED
    assert state.details["report_url"] == (
        "/site-selection/runs/run-001/report"
    )
    assert len(state.details["report_sha256"]) == 64
    assert run_service.get_report_path("run-001") == str(
        tmp_path.resolve() / "run-001.docx"
    )


def test_completed_run_stores_bounded_explanation_separately() -> None:
    class FixtureExplainer:
        def explain(self, state):
            return SiteSelectionEvidenceExplanation(
                status=EvidenceExplanationStatus.GENERATED,
                summary="只解释已完成证据。",
                candidate_notes=[
                    CandidateEvidenceNote(
                        parcel_id="A01",
                        explanation="面积与 POI 指标均来自结构化证据。",
                        evidence_references=["gis:A01:area_hectares"],
                    )
                ],
            )

    state = service(explainer=FixtureExplainer()).create_run(command())

    assert state.status is RunStatus.COMPLETED
    assert state.details["explanation"]["status"] == "generated"
    assert state.details["analysis"]["status"] == "completed"


def test_explanation_failure_is_explicit_without_changing_analysis_result() -> None:
    class ExplodingExplainer:
        def explain(self, state):
            raise RuntimeError("secret-token")

    state = service(explainer=ExplodingExplainer()).create_run(command())

    assert state.status is RunStatus.COMPLETED
    assert state.details["explanation"] == {
        "status": "failed",
        "summary": None,
        "candidate_notes": [],
        "error": "LLM 证据解释不可用：RuntimeError",
        "boundary_notice": (
            "该解释仅复述已完成证据，不改变评分、排序、规则结果，"
            "也不构成合规结论或选址推荐。"
        ),
    }
    assert "secret-token" not in state.model_dump_json()


def test_run_without_report_store_has_no_download(tmp_path) -> None:
    run_service = service()
    run_service.create_run(command())

    with pytest.raises(SiteSelectionReportNotFoundError, match="未配置"):
        run_service.get_report_path("run-001")


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
