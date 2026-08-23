from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from app.schemas.site_selection import (
    CandidateParcelInput,
    SiteSelectionAnalysisCreate,
)
from app.services.site_selection_run_service import SiteSelectionRunServiceProtocol
from practice.site_selection import (
    AnalysisScope,
    AgentState,
    CandidateDiscoveryReport,
    CandidateParcel,
    CandidateSelection,
    SiteSelectionSupervisor,
    SiteSelectionSupervisorRun,
    SupervisorAnalysisCompletion,
    SupervisorAnalysisStatus,
    SupervisorAnalysisSubmission,
    SupervisorSessionConflictError,
    SupervisorSessionNotFoundError,
    SupervisorStatus,
)
from practice.site_selection.storage import (
    RunState,
    RunStatus,
    SupervisorSessionEvent,
    SupervisorSessionEventType,
    SupervisorSessionLeaseExpiredError,
)


class SiteSelectionSupervisorAnalysisSubmitter:
    """Submits confirmed candidates to the existing durable run service."""

    def __init__(self, run_service: SiteSelectionRunServiceProtocol) -> None:
        if run_service is None:
            raise ValueError("Supervisor 分析提交器必须配置运行服务")
        self._run_service = run_service

    def __call__(
        self,
        session_id: str,
        report: CandidateDiscoveryReport,
        candidates: list[CandidateParcel],
    ) -> SupervisorAnalysisSubmission:
        if not candidates:
            raise ValueError("Supervisor 正式分析至少需要一个候选")
        snapshot_id = report.poi_evidence_snapshot_id
        if snapshot_id is None:
            raise ValueError("Supervisor 正式分析缺少 POI 证据快照")
        command = SiteSelectionAnalysisCreate(
            project_type=report.project_type,
            analysis_scope=(
                AnalysisScope.FULL_COMPLIANCE
                if report.formal_analysis_allowed
                else AnalysisScope.MARKET_SELECTION
            ),
            candidate_parcels=[
                CandidateParcelInput.model_validate(item.model_dump())
                for item in candidates
            ],
            poi_evidence_snapshot_id=snapshot_id,
        )
        state = self._run_service.create_run(
            command,
            idempotency_key=f"supervisor:{session_id}:analysis",
            supervisor_session_id=session_id,
        )
        return SupervisorAnalysisSubmission(
            run_id=state.run_id,
            status=SupervisorAnalysisStatus(state.status.value),
            analysis_scope=command.analysis_scope,
        )


class SupervisorSessionCoordinator(Protocol):
    def activate(self, session_id: str, checkpoint_id: str) -> None: ...
    def is_active(self, session_id: str) -> bool: ...
    def ttl(self, session_id: str) -> int: ...
    def acquire_transition(self, session_id: str) -> str | None: ...
    def release_transition(self, session_id: str, token: str) -> None: ...
    def append_event(self, event: SupervisorSessionEvent) -> None: ...
    def list_events(self, session_id: str) -> list[SupervisorSessionEvent]: ...
    def deactivate(self, session_id: str) -> None: ...


class SiteSelectionSupervisorServiceUnavailableError(RuntimeError):
    """Raised when durable Supervisor infrastructure is not configured."""


class SiteSelectionSupervisorServiceProtocol(Protocol):
    def start(self, request) -> SiteSelectionSupervisorRun: ...
    def get(self, session_id: str) -> SiteSelectionSupervisorRun: ...
    def confirm(
        self,
        session_id: str,
        selection: CandidateSelection,
        *,
        expected_checkpoint_id: str,
    ) -> SiteSelectionSupervisorRun: ...
    def complete_analysis(
        self,
        session_id: str,
        state: RunState,
    ) -> SiteSelectionSupervisorRun: ...
    def ttl(self, session_id: str) -> int: ...
    def list_events(self, session_id: str) -> list[SupervisorSessionEvent]: ...


class UnconfiguredSiteSelectionSupervisorService:
    def _unavailable(self, *args, **kwargs):
        del args, kwargs
        raise SiteSelectionSupervisorServiceUnavailableError(
            "Supervisor 持久化运行时尚未配置"
        )

    start = get = confirm = complete_analysis = ttl = list_events = _unavailable


def build_site_selection_supervisor_service(
    *,
    discovery_runner: Callable,
    run_service: SiteSelectionRunServiceProtocol,
    checkpointer,
    coordinator: SupervisorSessionCoordinator,
    clock: Callable[[], datetime] | None = None,
    session_id_factory: Callable[[], str] | None = None,
) -> SiteSelectionSupervisorApplicationService:
    """Build the single Supervisor topology used by API and Worker processes."""

    return SiteSelectionSupervisorApplicationService(
        SiteSelectionSupervisor(
            discovery_runner=discovery_runner,
            analysis_submitter=SiteSelectionSupervisorAnalysisSubmitter(
                run_service
            ),
            checkpointer=checkpointer,
        ),
        coordinator,
        run_service,
        clock=clock,
        session_id_factory=session_id_factory,
    )


class SiteSelectionSupervisorApplicationService:
    """Adds leases, distributed confirmation locking and audit to the graph."""

    def __init__(
        self,
        supervisor: SiteSelectionSupervisor,
        coordinator: SupervisorSessionCoordinator,
        run_service: SiteSelectionRunServiceProtocol | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        session_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._supervisor = supervisor
        self._coordinator = coordinator
        self._run_service = run_service
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._session_id_factory = session_id_factory or (
            lambda: f"supervisor-{uuid4()}"
        )

    def start(self, request) -> SiteSelectionSupervisorRun:
        session_id = self._session_id_factory()
        try:
            run = self._supervisor.start(session_id, request)
            self._coordinator.activate(session_id, run.checkpoint_id)
            self._event(run, SupervisorSessionEventType.STARTED)
            self._event(
                run,
                SupervisorSessionEventType.AWAITING_CONFIRMATION,
            )
        except Exception:
            self._discard_session(session_id)
            raise
        return run

    def get(self, session_id: str) -> SiteSelectionSupervisorRun:
        self._require_active(session_id)
        return self._reconcile_if_terminal(
            self._supervisor.get(session_id)
        )

    def confirm(
        self,
        session_id: str,
        selection: CandidateSelection,
        *,
        expected_checkpoint_id: str,
    ) -> SiteSelectionSupervisorRun:
        self._require_active(session_id)
        try:
            token = self._coordinator.acquire_transition(session_id)
        except SupervisorSessionLeaseExpiredError:
            self._expire(session_id)
        if token is None:
            raise SupervisorSessionConflictError(
                f"Supervisor session 正在确认中：{session_id}"
            )
        confirmed = selection.model_copy(
            update={"confirmed_at": self._clock()},
            deep=True,
        )
        before_confirmation = self._supervisor.get(session_id)
        try:
            try:
                run = self._supervisor.confirm(
                    session_id,
                    confirmed,
                    expected_checkpoint_id=expected_checkpoint_id,
                )
            except Exception as exc:
                self._event(
                    before_confirmation,
                    SupervisorSessionEventType.CONFIRMATION_REJECTED,
                    selection=confirmed,
                    error_type=type(exc).__name__,
                )
                raise
            self._coordinator.activate(session_id, run.checkpoint_id)
            self._event(
                run,
                SupervisorSessionEventType.CONFIRMED,
                selection=confirmed,
            )
            self._event(
                run,
                SupervisorSessionEventType.ANALYSIS_SUBMITTED,
                selection=confirmed,
                analysis_run_id=run.analysis_run_id,
            )
        finally:
            self._coordinator.release_transition(session_id, token)
        return self._reconcile_if_terminal(run)

    def complete_analysis(
        self,
        session_id: str,
        state: RunState,
    ) -> SiteSelectionSupervisorRun:
        self._require_active(session_id)
        linked_session = state.details.get("supervisor_session_id")
        if linked_session != session_id:
            raise SupervisorSessionConflictError(
                "分析运行与 Supervisor session 关联不一致"
            )
        current = self._supervisor.get(session_id)
        if current.status is not SupervisorStatus.AWAITING_ANALYSIS:
            if current.analysis_run_id == state.run_id and current.status in {
                SupervisorStatus.COMPLETED,
                SupervisorStatus.FAILED,
                SupervisorStatus.CANCELLED,
                SupervisorStatus.TIMED_OUT,
            }:
                return current
            raise SupervisorSessionConflictError(
                f"Supervisor session 当前不等待分析完成：{session_id}"
            )
        try:
            token = self._coordinator.acquire_transition(session_id)
        except SupervisorSessionLeaseExpiredError:
            self._expire(session_id)
        if token is None:
            raise SupervisorSessionConflictError(
                f"Supervisor session 正在由其他请求推进：{session_id}"
            )
        try:
            run = self._supervisor.complete_analysis(
                session_id,
                _completion_from_run_state(state),
            )
            self._coordinator.activate(session_id, run.checkpoint_id)
            event_type = {
                SupervisorStatus.COMPLETED: (
                    SupervisorSessionEventType.ANALYSIS_COMPLETED
                ),
                SupervisorStatus.FAILED: SupervisorSessionEventType.ANALYSIS_FAILED,
                SupervisorStatus.CANCELLED: (
                    SupervisorSessionEventType.ANALYSIS_CANCELLED
                ),
                SupervisorStatus.TIMED_OUT: (
                    SupervisorSessionEventType.ANALYSIS_TIMED_OUT
                ),
            }[run.status]
            self._event(
                run,
                event_type,
                analysis_run_id=state.run_id,
                error_type=run.analysis_error_type,
            )
            if run.status is SupervisorStatus.COMPLETED:
                self._event(
                    run,
                    SupervisorSessionEventType.COMPLETED,
                    analysis_run_id=state.run_id,
                )
            return run
        finally:
            self._coordinator.release_transition(session_id, token)

    def ttl(self, session_id: str) -> int:
        self._require_active(session_id)
        return self._coordinator.ttl(session_id)

    def list_events(self, session_id: str) -> list[SupervisorSessionEvent]:
        self._require_active(session_id)
        return self._coordinator.list_events(session_id)

    def _require_active(self, session_id: str) -> None:
        if self._coordinator.is_active(session_id):
            return
        self._expire(session_id)

    def _expire(self, session_id: str) -> None:
        self._discard_session(session_id)
        raise SupervisorSessionNotFoundError(session_id)

    def _discard_session(self, session_id: str) -> None:
        # Cleanup is compensating work and must not hide the triggering error.
        with suppress(Exception):
            self._coordinator.deactivate(session_id)
        with suppress(Exception):
            self._supervisor.delete(session_id)

    def _event(
        self,
        run: SiteSelectionSupervisorRun,
        event_type: SupervisorSessionEventType,
        *,
        selection: CandidateSelection | None = None,
        analysis_run_id: str | None = None,
        error_type: str | None = None,
    ) -> None:
        self._coordinator.append_event(
            SupervisorSessionEvent(
                session_id=run.session_id,
                event_type=event_type,
                occurred_at=self._clock(),
                checkpoint_id=run.checkpoint_id,
                analysis_run_id=analysis_run_id,
                reviewer_id=(selection.reviewer_id if selection else None),
                selected_candidate_ids=(
                    list(selection.selected_candidate_ids)
                    if selection
                    else []
                ),
                error_type=error_type,
            )
        )

    def _reconcile_if_terminal(
        self,
        run: SiteSelectionSupervisorRun,
    ) -> SiteSelectionSupervisorRun:
        if (
            self._run_service is None
            or run.status is not SupervisorStatus.AWAITING_ANALYSIS
            or run.analysis_run_id is None
        ):
            return run
        state = self._run_service.get_run(run.analysis_run_id)
        if state.status in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        }:
            try:
                return self.complete_analysis(run.session_id, state)
            except SupervisorSessionConflictError:
                # A Worker and a GET reconciliation can observe the same
                # terminal RunState. If the Worker owns the transition lock,
                # keep GET idempotent and let the next poll read its checkpoint.
                latest = self._supervisor.get(run.session_id)
                if latest.status is not SupervisorStatus.AWAITING_ANALYSIS:
                    return latest
                return latest.model_copy(
                    update={
                        "analysis_run_status": SupervisorAnalysisStatus(
                            state.status.value
                        )
                    }
                )
        return run.model_copy(
            update={
                "analysis_run_status": SupervisorAnalysisStatus(
                    state.status.value
                )
            }
        )


def _completion_from_run_state(state: RunState) -> SupervisorAnalysisCompletion:
    if state.status not in {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.TIMED_OUT,
    }:
        raise SupervisorSessionConflictError(
            f"分析运行尚未进入终态：{state.status.value}"
        )
    analysis = None
    error_type = None
    if state.status is RunStatus.COMPLETED:
        payload = state.details.get("analysis")
        if payload is None:
            raise SupervisorSessionConflictError(
                "completed 分析运行缺少 AgentState"
            )
        analysis = AgentState.model_validate(payload)
    else:
        raw_error_type = (
            state.details.get("worker_error_type")
            or state.details.get("queue_error_type")
            or state.details.get("analysis_error_type")
            or state.status.value
        )
        error_type = str(raw_error_type)
    return SupervisorAnalysisCompletion(
        run_id=state.run_id,
        status=SupervisorAnalysisStatus(state.status.value),
        analysis_state=analysis,
        error_type=error_type,
    )
