from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from shapely.geometry import shape

from app.schemas.site_selection import CandidateParcelInput, SiteSelectionAnalysisCreate
from app.services.site_selection_service import SiteSelectionAnalysisService
from app.services.site_selection_supervisor import (
    SiteSelectionSupervisorAnalysisSubmitter,
)
from app.site_selection_bootstrap import (
    build_fixture_runtime_registry,
    load_fixture_spatial_seed,
)
from practice.site_selection import (
    AnalysisScope,
    AnalysisStatus,
    CandidateConfirmationBlockedError,
    CandidateDiscoveryRequest,
    CandidateDiscoveryStrategy,
    CandidateDiscoveryService,
    CandidateSelection,
    DiscoveryBounds,
    ProjectType,
    SiteSelectionSupervisor,
    SupervisorAnalysisCompletion,
    SupervisorAnalysisStatus,
    SupervisorAnalysisSubmission,
    SupervisorConfigurationError,
    SupervisorSessionConflictError,
    SupervisorSessionNotFoundError,
    SupervisorStatus,
    build_site_selection_supervisor_execution_plan,
    build_site_selection_supervisor_graph,
    run_parallel_site_selection_workflow,
)
from practice.site_selection.storage import RunState, RunStatus
from practice.site_selection.spatial import MockSpatialDatasetGateway


FIXTURE_ROOT = Path(__file__).parents[1] / "data" / "fixtures"


class InMemorySnapshotStore:
    def __init__(self) -> None:
        self.snapshots = {}

    def save_candidate_discovery_snapshot(self, snapshot) -> None:
        self.snapshots[snapshot.snapshot_id] = snapshot

    def get_candidate_discovery_snapshot(self, snapshot_id):
        return self.snapshots.get(snapshot_id)


class CountingRunner:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.calls = 0

    def __call__(self, *args):
        self.calls += 1
        return self.delegate(*args)


class AsyncAnalysisHarness:
    def __init__(self, analysis_service: SiteSelectionAnalysisService) -> None:
        self.analysis_service = analysis_service
        self.calls = 0
        self.report = None
        self.candidates = []
        self.run_id = "run-supervisor-analysis-001"

    def __call__(self, session_id, report, candidates):
        self.calls += 1
        self.report = report
        self.candidates = list(candidates)
        assert session_id
        return SupervisorAnalysisSubmission(
            run_id=self.run_id,
            status=SupervisorAnalysisStatus.QUEUED,
        )

    def completed_state(self):
        return self.analysis_service.analyze(
            SiteSelectionAnalysisCreate(
                project_type=self.report.project_type,
                candidate_parcels=[
                    CandidateParcelInput.model_validate(item.model_dump())
                    for item in self.candidates
                ],
                poi_evidence_snapshot_id=self.report.poi_evidence_snapshot_id,
            )
        )


def _frames():
    seed = load_fixture_spatial_seed(FIXTURE_ROOT / "spatial_layers.json")
    return {
        layer.layer_id: gpd.GeoDataFrame(
            [feature.properties for feature in layer.features],
            geometry=[shape(feature.geometry) for feature in layer.features],
            crs=seed.crs,
        )
        for layer in seed.layers
    }


def _request() -> CandidateDiscoveryRequest:
    return CandidateDiscoveryRequest(
        request_id="supervisor-discovery-001",
        project_type=ProjectType.COFFEE_SHOP,
        bounds=DiscoveryBounds(
            west=121.29,
            south=31.14,
            east=121.37,
            north=31.19,
        ),
        max_candidates=6,
        minimum_separation_m=600,
    )


def _supervisor():
    store = InMemorySnapshotStore()
    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=MockSpatialDatasetGateway(_frames()),
    )
    discovery = CountingRunner(
        CandidateDiscoveryService(
            registry,
            snapshot_store=store,
            snapshot_id_factory=lambda: "supervisor-poi-snapshot-001",
        ).discover
    )
    analysis = AsyncAnalysisHarness(
        SiteSelectionAnalysisService(
            registry,
            snapshot_store=store,
            workflow_runner=run_parallel_site_selection_workflow,
            request_id_factory=lambda: "supervisor-analysis-001",
        )
    )
    supervisor = SiteSelectionSupervisor(
        discovery_runner=discovery,
        analysis_submitter=analysis,
        checkpointer=InMemorySaver(),
    )
    return supervisor, discovery, analysis


def _confirm(supervisor, paused, candidate_ids=None):
    return supervisor.confirm(
        paused.session_id,
        CandidateSelection(
            selected_candidate_ids=(
                candidate_ids or paused.confirmation_request.candidate_ids[:2]
            )
        ),
        expected_checkpoint_id=paused.checkpoint_id,
    )


def _market_report():
    supervisor, _, _ = _supervisor()
    report = supervisor.start("market-report-source", _request()).discovery_report
    return report.model_copy(
        update={
            "strategy": CandidateDiscoveryStrategy.MARKET_EXPLORATION,
            "formal_analysis_allowed": False,
            "candidates": [
                item.model_copy(
                    update={
                        "candidate": item.candidate.model_copy(
                            update={
                                "area_hectares": None,
                                "geometry_dataset_id": None,
                            }
                        ),
                        "land_use_class": "unknown",
                        "land_use_dataset_id": None,
                        "land_use_dataset_version": None,
                        "formal_analysis_allowed": False,
                        "requires_human_review": True,
                    }
                )
                for item in report.candidates
            ],
        }
    )


def test_supervisor_pauses_submits_and_resumes_from_worker_completion() -> None:
    supervisor, discovery, analysis = _supervisor()
    paused = supervisor.start("session-001", _request())

    assert paused.status is SupervisorStatus.AWAITING_CONFIRMATION
    assert paused.confirmation_request.poi_evidence_snapshot_id == (
        "supervisor-poi-snapshot-001"
    )
    awaiting = _confirm(supervisor, paused)

    assert awaiting.status is SupervisorStatus.AWAITING_ANALYSIS
    assert awaiting.analysis_run_id == analysis.run_id
    assert awaiting.analysis_run_status is SupervisorAnalysisStatus.QUEUED
    assert awaiting.analysis_state is None
    assert [trace.node_id for trace in awaiting.supervisor_trace] == [
        "supervisor_intake",
        "candidate_discovery",
        "candidate_confirmation",
        "analysis_submitted",
    ]
    assert discovery.calls == 1
    assert analysis.calls == 1

    completion = SupervisorAnalysisCompletion(
        run_id=analysis.run_id,
        status=SupervisorAnalysisStatus.COMPLETED,
        analysis_state=analysis.completed_state(),
    )
    completed = supervisor.complete_analysis(paused.session_id, completion)

    assert completed.status is SupervisorStatus.COMPLETED
    assert completed.analysis_state.status is AnalysisStatus.COMPLETED
    assert [item.parcel_id for item in completed.analysis_state.results] == (
        paused.confirmation_request.candidate_ids[:2]
    )
    assert any(
        feature_set.source.evidence_reused
        for result in completed.analysis_state.results
        for feature_set in result.poi_evidence.feature_sets
    )
    assert [trace.node_id for trace in completed.supervisor_trace] == [
        "supervisor_intake",
        "candidate_discovery",
        "candidate_confirmation",
        "analysis_submitted",
        "analysis_wait",
        "analysis_completed",
    ]
    assert supervisor.complete_analysis(paused.session_id, completion) == completed


def test_supervisor_allows_retail_market_analysis_without_land_geometry() -> None:
    report = _market_report()

    class CaptureAnalysis:
        def __init__(self):
            self.candidates = []

        def __call__(self, session_id, submitted_report, candidates):
            assert session_id == "session-market-selection"
            assert submitted_report == report
            self.candidates = list(candidates)
            return SupervisorAnalysisSubmission(
                run_id="run-market-selection",
                status=SupervisorAnalysisStatus.QUEUED,
                analysis_scope=AnalysisScope.MARKET_SELECTION,
            )

    analysis = CaptureAnalysis()
    supervisor = SiteSelectionSupervisor(
        discovery_runner=lambda request: report,
        analysis_submitter=analysis,
        checkpointer=InMemorySaver(),
    )
    paused = supervisor.start("session-market-selection", _request())

    submitted = _confirm(supervisor, paused)

    assert submitted.status is SupervisorStatus.AWAITING_ANALYSIS
    assert analysis.candidates
    assert all(item.geometry_dataset_id is None for item in analysis.candidates)


def test_application_submitter_routes_unverified_retail_to_market_scope() -> None:
    report = _market_report()

    class CaptureRunService:
        def __init__(self):
            self.command = None

        def create_run(self, command, **kwargs):
            assert kwargs["supervisor_session_id"] == "session-market-submit"
            self.command = command
            return RunState(
                run_id="run-market-submit",
                status=RunStatus.QUEUED,
                updated_at=report.generated_at,
            )

    run_service = CaptureRunService()
    submission = SiteSelectionSupervisorAnalysisSubmitter(run_service)(
        "session-market-submit",
        report,
        [report.candidates[0].candidate],
    )

    assert run_service.command.analysis_scope is AnalysisScope.MARKET_SELECTION
    assert submission.analysis_scope is AnalysisScope.MARKET_SELECTION


@pytest.mark.parametrize(
    ("analysis_status", "supervisor_status"),
    [
        (SupervisorAnalysisStatus.FAILED, SupervisorStatus.FAILED),
        (SupervisorAnalysisStatus.CANCELLED, SupervisorStatus.CANCELLED),
        (SupervisorAnalysisStatus.TIMED_OUT, SupervisorStatus.TIMED_OUT),
    ],
)
def test_supervisor_preserves_analysis_terminal_states(
    analysis_status,
    supervisor_status,
) -> None:
    supervisor, _, analysis = _supervisor()
    paused = supervisor.start(f"session-{analysis_status.value}", _request())
    _confirm(supervisor, paused)

    terminal = supervisor.complete_analysis(
        paused.session_id,
        SupervisorAnalysisCompletion(
            run_id=analysis.run_id,
            status=analysis_status,
            error_type="WorkerTerminalError",
        ),
    )

    assert terminal.status is supervisor_status
    assert terminal.analysis_run_status is analysis_status
    assert terminal.analysis_error_type == "WorkerTerminalError"
    assert terminal.analysis_state is None


def test_supervisor_runtime_nodes_match_reviewed_plan() -> None:
    supervisor, _, _ = _supervisor()
    assert set(supervisor.graph.get_graph().nodes) - {"__start__", "__end__"} == {
        step.node_id for step in build_site_selection_supervisor_execution_plan().steps
    }


def test_supervisor_rejects_candidate_tampering_before_submission() -> None:
    supervisor, discovery, analysis = _supervisor()
    paused = supervisor.start("session-tampered", _request())

    with pytest.raises(CandidateConfirmationBlockedError, match="发现报告之外"):
        _confirm(supervisor, paused, ["unknown-candidate"])

    assert supervisor.get(paused.session_id) == paused
    assert discovery.calls == 1
    assert analysis.calls == 0
    assert _confirm(supervisor, paused).status is SupervisorStatus.AWAITING_ANALYSIS
    assert analysis.calls == 1


def test_supervisor_requires_checkpoint_and_enforces_session_lifecycle() -> None:
    with pytest.raises(SupervisorConfigurationError, match="Checkpointer"):
        build_site_selection_supervisor_graph(
            discovery_runner=lambda request: request,
            analysis_submitter=lambda session_id, report, candidates: report,
            checkpointer=None,
        )

    supervisor, _, _ = _supervisor()
    supervisor.start("session-lifecycle", _request())
    with pytest.raises(SupervisorSessionConflictError, match="已存在"):
        supervisor.start("session-lifecycle", _request())
    with pytest.raises(SupervisorSessionNotFoundError):
        supervisor.confirm(
            "missing-session",
            CandidateSelection(selected_candidate_ids=["candidate-001"]),
            expected_checkpoint_id="missing-checkpoint",
        )
    supervisor.delete("session-lifecycle")
    with pytest.raises(SupervisorSessionNotFoundError):
        supervisor.get("session-lifecycle")


def test_supervisor_rejects_stale_checkpoint_before_resume() -> None:
    supervisor, discovery, analysis = _supervisor()
    paused = supervisor.start("session-stale", _request())

    with pytest.raises(SupervisorSessionConflictError, match="刷新后重试"):
        supervisor.confirm(
            paused.session_id,
            CandidateSelection(
                selected_candidate_ids=paused.confirmation_request.candidate_ids[:1]
            ),
            expected_checkpoint_id="stale-checkpoint",
        )

    assert supervisor.get(paused.session_id) == paused
    assert discovery.calls == 1
    assert analysis.calls == 0
