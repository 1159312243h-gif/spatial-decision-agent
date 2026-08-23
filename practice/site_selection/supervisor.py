from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from time import perf_counter
from typing import Literal, TypedDict

from langgraph.types import Command, interrupt
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agent_graph_runtime import compile_agent_plan_graph
from .agent_orchestration import (
    AgentExecutionPlan,
    AgentStepStatus,
    AgentStepTrace,
    build_site_selection_supervisor_execution_plan,
    order_agent_traces,
    trace_for,
)
from .candidate_discovery import CandidateDiscoveryReport, CandidateDiscoveryRequest
from .domain import AnalysisScope, CandidateParcel, NonEmptyString, ProjectType
from .evidence import AgentState, AnalysisStatus


class SupervisorStatus(StrEnum):
    RUNNING = "running"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    AWAITING_ANALYSIS = "awaiting_analysis"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class SupervisorAnalysisStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class SupervisorConfigurationError(ValueError):
    """Raised when a recoverable Supervisor runtime is not fully configured."""


class SupervisorSessionNotFoundError(KeyError):
    """Raised when no checkpoint exists for a requested session."""


class SupervisorSessionConflictError(RuntimeError):
    """Raised when a session is started twice or resumed in the wrong state."""


class CandidateConfirmationBlockedError(RuntimeError):
    """Raised when a resumed selection does not match reviewed discovery."""


class SupervisorAnalysisBlockedError(RuntimeError):
    """Raised when the formal-analysis subgraph does not complete."""


class CandidateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_candidate_ids: list[NonEmptyString] = Field(min_length=1)
    note: NonEmptyString | None = None
    reviewer_id: NonEmptyString | None = None
    confirmed_at: datetime | None = None

    @model_validator(mode="after")
    def candidate_ids_are_unique(self) -> CandidateSelection:
        if len(self.selected_candidate_ids) != len(
            set(self.selected_candidate_ids)
        ):
            raise ValueError("人工确认的候选 ID 不能重复")
        if self.confirmed_at is not None and (
            self.confirmed_at.tzinfo is None
            or self.confirmed_at.utcoffset() is None
        ):
            raise ValueError("人工确认时间必须包含时区")
        return self


class SupervisorConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["candidate_confirmation_required"] = (
        "candidate_confirmation_required"
    )
    discovery_request_id: NonEmptyString
    project_type: ProjectType
    candidate_ids: list[NonEmptyString] = Field(min_length=1)
    poi_evidence_snapshot_id: NonEmptyString
    warnings: list[NonEmptyString] = Field(default_factory=list)


class SupervisorAnalysisSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: NonEmptyString
    status: SupervisorAnalysisStatus
    analysis_scope: AnalysisScope = AnalysisScope.FULL_COMPLIANCE


class SupervisorAnalysisWaitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["analysis_completion_required"] = (
        "analysis_completion_required"
    )
    run_id: NonEmptyString


class SupervisorAnalysisCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: NonEmptyString
    status: SupervisorAnalysisStatus
    analysis_state: AgentState | None = None
    error_type: NonEmptyString | None = None

    @model_validator(mode="after")
    def completion_is_terminal_and_consistent(self) -> SupervisorAnalysisCompletion:
        terminal = {
            SupervisorAnalysisStatus.COMPLETED,
            SupervisorAnalysisStatus.FAILED,
            SupervisorAnalysisStatus.CANCELLED,
            SupervisorAnalysisStatus.TIMED_OUT,
        }
        if self.status not in terminal:
            raise ValueError("Supervisor 分析完成事件必须是终态")
        if self.status is SupervisorAnalysisStatus.COMPLETED:
            if (
                self.analysis_state is None
                or self.analysis_state.status is not AnalysisStatus.COMPLETED
            ):
                raise ValueError("completed 分析事件必须携带 completed AgentState")
            if self.error_type is not None:
                raise ValueError("completed 分析事件不能携带 error_type")
        elif self.analysis_state is not None:
            raise ValueError("非 completed 分析事件不能携带 AgentState")
        return self


class SiteSelectionSupervisorState(TypedDict, total=False):
    session_id: str
    discovery_request: CandidateDiscoveryRequest
    discovery_report: CandidateDiscoveryReport
    confirmation: CandidateSelection
    selected_candidates: list[CandidateParcel]
    analysis_submission: SupervisorAnalysisSubmission
    analysis_completion: SupervisorAnalysisCompletion
    analysis_state: AgentState
    analysis_error_type: str
    status: SupervisorStatus
    execution_plan: AgentExecutionPlan
    supervisor_trace: list[AgentStepTrace]


class SiteSelectionSupervisorRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: NonEmptyString
    checkpoint_id: NonEmptyString
    status: SupervisorStatus
    discovery_report: CandidateDiscoveryReport | None = None
    confirmation_request: SupervisorConfirmationRequest | None = None
    confirmation: CandidateSelection | None = None
    analysis_run_id: NonEmptyString | None = None
    analysis_run_status: SupervisorAnalysisStatus | None = None
    analysis_error_type: NonEmptyString | None = None
    analysis_state: AgentState | None = None
    execution_plan: AgentExecutionPlan
    supervisor_trace: list[AgentStepTrace] = Field(default_factory=list)


CandidateDiscoveryRunner = Callable[
    [CandidateDiscoveryRequest], CandidateDiscoveryReport
]
AnalysisSubmissionRunner = Callable[
    [str, CandidateDiscoveryReport, list[CandidateParcel]],
    SupervisorAnalysisSubmission,
]


def build_site_selection_supervisor_graph(
    *,
    discovery_runner: CandidateDiscoveryRunner,
    analysis_submitter: AnalysisSubmissionRunner,
    checkpointer,
    monotonic: Callable[[], float] | None = None,
):
    """Compile the checkpointed discovery-confirmation-analysis Supervisor."""

    if not callable(discovery_runner) or not callable(analysis_submitter):
        raise SupervisorConfigurationError(
            "Supervisor 必须配置候选发现 Runner 和分析提交器"
        )
    if checkpointer is None:
        raise SupervisorConfigurationError(
            "Supervisor 必须配置 Checkpointer，禁止不可恢复的人工中断"
        )
    timer = monotonic or perf_counter
    plan = build_site_selection_supervisor_execution_plan()

    def supervisor_intake(state: SiteSelectionSupervisorState):
        started_at = timer()
        request = state["discovery_request"]
        return {
            "status": SupervisorStatus.RUNNING,
            "execution_plan": plan,
            "supervisor_trace": [
                trace_for(
                    plan.step("supervisor_intake"),
                    AgentStepStatus.SUCCEEDED,
                    _elapsed_ms(timer, started_at),
                )
            ],
            "discovery_request": request.model_copy(deep=True),
            "session_id": state["session_id"],
        }

    def candidate_discovery(state: SiteSelectionSupervisorState):
        started_at = timer()
        report = discovery_runner(state["discovery_request"])
        request = state["discovery_request"]
        if (
            report.request_id != request.request_id
            or report.project_type is not request.project_type
        ):
            raise SupervisorAnalysisBlockedError(
                "候选发现报告与 Supervisor 请求不一致"
            )
        return {
            "discovery_report": report.model_copy(deep=True),
            "status": SupervisorStatus.AWAITING_CONFIRMATION,
            "supervisor_trace": _append_trace(
                plan,
                state,
                "candidate_discovery",
                timer,
                started_at,
            ),
        }

    def candidate_confirmation(state: SiteSelectionSupervisorState):
        report = state["discovery_report"]
        confirmation_request = _confirmation_request(report)
        resumed = interrupt(confirmation_request.model_dump(mode="json"))
        started_at = timer()
        confirmation = CandidateSelection.model_validate(resumed)
        selected = _validate_confirmation(report, confirmation)
        return {
            "confirmation": confirmation,
            "selected_candidates": selected,
            "status": SupervisorStatus.RUNNING,
            "supervisor_trace": _append_trace(
                plan,
                state,
                "candidate_confirmation",
                timer,
                started_at,
            ),
        }

    def analysis_submitted(state: SiteSelectionSupervisorState):
        started_at = timer()
        submission = analysis_submitter(
            state["session_id"],
            state["discovery_report"],
            [item.model_copy(deep=True) for item in state["selected_candidates"]],
        )
        return {
            "analysis_submission": submission,
            "status": SupervisorStatus.AWAITING_ANALYSIS,
            "supervisor_trace": _append_trace(
                plan,
                state,
                "analysis_submitted",
                timer,
                started_at,
            ),
        }

    def analysis_wait(state: SiteSelectionSupervisorState):
        submission = SupervisorAnalysisSubmission.model_validate(
            state["analysis_submission"]
        )
        resumed = interrupt(
            SupervisorAnalysisWaitRequest(run_id=submission.run_id).model_dump(
                mode="json"
            )
        )
        started_at = timer()
        completion = SupervisorAnalysisCompletion.model_validate(resumed)
        if completion.run_id != submission.run_id:
            raise SupervisorAnalysisBlockedError(
                "分析完成事件与 Supervisor 保存的 run_id 不一致"
            )
        output = {
            "analysis_completion": completion,
            "status": SupervisorStatus.RUNNING,
            "supervisor_trace": _append_trace(
                plan,
                state,
                "analysis_wait",
                timer,
                started_at,
            ),
        }
        if completion.analysis_state is not None:
            output["analysis_state"] = completion.analysis_state
        if completion.error_type is not None:
            output["analysis_error_type"] = completion.error_type
        return output

    def analysis_completed(state: SiteSelectionSupervisorState):
        started_at = timer()
        completion_payload = state.get("analysis_completion")
        if completion_payload is None:
            raise SupervisorAnalysisBlockedError(
                "Supervisor 完成门禁缺少分析完成事件"
            )
        completion = SupervisorAnalysisCompletion.model_validate(
            completion_payload
        )
        terminal_status = {
            SupervisorAnalysisStatus.COMPLETED: SupervisorStatus.COMPLETED,
            SupervisorAnalysisStatus.FAILED: SupervisorStatus.FAILED,
            SupervisorAnalysisStatus.CANCELLED: SupervisorStatus.CANCELLED,
            SupervisorAnalysisStatus.TIMED_OUT: SupervisorStatus.TIMED_OUT,
        }[completion.status]
        return {
            "status": terminal_status,
            "supervisor_trace": _append_trace(
                plan,
                state,
                "analysis_completed",
                timer,
                started_at,
            ),
        }

    return compile_agent_plan_graph(
        plan=plan,
        state_schema=SiteSelectionSupervisorState,
        node_handlers={
            "supervisor_intake": supervisor_intake,
            "candidate_discovery": candidate_discovery,
            "candidate_confirmation": candidate_confirmation,
            "analysis_submitted": analysis_submitted,
            "analysis_wait": analysis_wait,
            "analysis_completed": analysis_completed,
        },
        checkpointer=checkpointer,
    )


class SiteSelectionSupervisor:
    """Application-neutral facade over a checkpointed Supervisor graph."""

    def __init__(
        self,
        *,
        discovery_runner: CandidateDiscoveryRunner,
        analysis_submitter: AnalysisSubmissionRunner,
        checkpointer,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._plan = build_site_selection_supervisor_execution_plan()
        self._checkpointer = checkpointer
        self._graph = build_site_selection_supervisor_graph(
            discovery_runner=discovery_runner,
            analysis_submitter=analysis_submitter,
            checkpointer=checkpointer,
            monotonic=monotonic,
        )

    @property
    def graph(self):
        return self._graph

    def start(
        self,
        session_id: str,
        request: CandidateDiscoveryRequest,
    ) -> SiteSelectionSupervisorRun:
        config = _thread_config(session_id)
        if self._graph.get_state(config).values:
            raise SupervisorSessionConflictError(
                f"Supervisor session 已存在：{session_id}"
            )
        output = self._graph.invoke(
            {"session_id": session_id, "discovery_request": request},
            config=config,
        )
        del output
        return _snapshot_run_view(
            session_id,
            self._plan,
            self._graph.get_state(config),
        )

    def complete_analysis(
        self,
        session_id: str,
        completion: SupervisorAnalysisCompletion,
    ) -> SiteSelectionSupervisorRun:
        config = _thread_config(session_id)
        snapshot = self._graph.get_state(config)
        if not snapshot.values:
            raise SupervisorSessionNotFoundError(session_id)
        if "analysis_wait" not in snapshot.next:
            existing = snapshot.values.get("analysis_completion")
            if existing is not None:
                parsed = SupervisorAnalysisCompletion.model_validate(existing)
                if parsed.run_id == completion.run_id:
                    return _snapshot_run_view(session_id, self._plan, snapshot)
            raise SupervisorSessionConflictError(
                f"Supervisor session 当前不等待分析完成：{session_id}"
            )
        submission = SupervisorAnalysisSubmission.model_validate(
            snapshot.values.get("analysis_submission")
        )
        if submission.run_id != completion.run_id:
            raise SupervisorSessionConflictError(
                "分析完成事件与 Supervisor session 的 run_id 不一致"
            )
        self._graph.invoke(
            Command(resume=completion.model_dump(mode="json")),
            config=config,
        )
        return _snapshot_run_view(
            session_id,
            self._plan,
            self._graph.get_state(config),
        )

    def get(self, session_id: str) -> SiteSelectionSupervisorRun:
        snapshot = self._graph.get_state(_thread_config(session_id))
        if not snapshot.values:
            raise SupervisorSessionNotFoundError(session_id)
        return _snapshot_run_view(session_id, self._plan, snapshot)

    def confirm(
        self,
        session_id: str,
        selection: CandidateSelection,
        *,
        expected_checkpoint_id: str,
    ) -> SiteSelectionSupervisorRun:
        config = _thread_config(session_id)
        snapshot = self._graph.get_state(config)
        if not snapshot.values:
            raise SupervisorSessionNotFoundError(session_id)
        checkpoint_id = _snapshot_checkpoint_id(snapshot)
        if checkpoint_id != expected_checkpoint_id:
            raise SupervisorSessionConflictError(
                "Supervisor session 已更新，请刷新后重试："
                f"{session_id}"
            )
        if "candidate_confirmation" not in snapshot.next:
            raise SupervisorSessionConflictError(
                f"Supervisor session 当前不等待候选确认：{session_id}"
            )
        report_payload = snapshot.values.get("discovery_report")
        if report_payload is None:
            raise SupervisorSessionConflictError(
                f"Supervisor session 缺少候选发现报告：{session_id}"
            )
        report = CandidateDiscoveryReport.model_validate(report_payload)
        # Validate before resuming so a rejected request does not consume or
        # advance the durable human-review interrupt. The node repeats this
        # check as a defense-in-depth execution gate.
        _validate_confirmation(report, selection)
        output = self._graph.invoke(
            Command(resume=selection.model_dump(mode="json")),
            config=config,
        )
        del output
        return _snapshot_run_view(
            session_id,
            self._plan,
            self._graph.get_state(config),
        )

    def delete(self, session_id: str) -> None:
        normalized = _thread_config(session_id)["configurable"]["thread_id"]
        delete_thread = getattr(self._checkpointer, "delete_thread", None)
        if not callable(delete_thread):
            raise SupervisorConfigurationError(
                "Supervisor Checkpointer 不支持删除过期 session"
            )
        delete_thread(normalized)


def _confirmation_request(
    report: CandidateDiscoveryReport,
) -> SupervisorConfirmationRequest:
    snapshot_id = report.poi_evidence_snapshot_id
    if snapshot_id is None:
        raise CandidateConfirmationBlockedError(
            "Supervisor 候选确认要求候选发现 POI 证据快照"
        )
    return SupervisorConfirmationRequest(
        discovery_request_id=report.request_id,
        project_type=report.project_type,
        candidate_ids=[item.candidate.parcel_id for item in report.candidates],
        poi_evidence_snapshot_id=snapshot_id,
        warnings=report.warnings,
    )


def _validate_confirmation(
    report: CandidateDiscoveryReport,
    confirmation: CandidateSelection,
) -> list[CandidateParcel]:
    market_selection_allowed = (
        report.project_type
        in {ProjectType.COFFEE_SHOP, ProjectType.CONVENIENCE_STORE}
    )
    if not report.formal_analysis_allowed and not market_selection_allowed:
        raise CandidateConfirmationBlockedError(
            "候选发现结果既不具备合规依据，也不支持市场选址分析"
        )
    by_id = {item.candidate.parcel_id: item for item in report.candidates}
    unknown = sorted(set(confirmation.selected_candidate_ids) - set(by_id))
    if unknown:
        raise CandidateConfirmationBlockedError(
            "人工确认包含发现报告之外的候选：" + ", ".join(unknown)
        )
    selected = [by_id[item_id] for item_id in confirmation.selected_candidate_ids]
    blocked = [] if market_selection_allowed else [
        item.candidate.parcel_id for item in selected
        if not item.formal_analysis_allowed
    ]
    if blocked:
        raise CandidateConfirmationBlockedError(
            "人工确认包含不可进入正式分析的候选：" + ", ".join(blocked)
        )
    return [item.candidate.model_copy(deep=True) for item in selected]


def _append_trace(
    plan: AgentExecutionPlan,
    state: SiteSelectionSupervisorState,
    node_id: str,
    timer: Callable[[], float],
    started_at: float,
) -> list[AgentStepTrace]:
    return order_agent_traces(
        plan,
        [
            *state.get("supervisor_trace", []),
            trace_for(
                plan.step(node_id),
                AgentStepStatus.SUCCEEDED,
                _elapsed_ms(timer, started_at),
            ),
        ],
    )


def _snapshot_run_view(
    session_id: str,
    plan: AgentExecutionPlan,
    snapshot,
) -> SiteSelectionSupervisorRun:
    values = snapshot.values
    report = (
        CandidateDiscoveryReport.model_validate(values["discovery_report"])
        if values.get("discovery_report") is not None
        else None
    )
    awaiting_confirmation = "candidate_confirmation" in snapshot.next
    awaiting_analysis = "analysis_wait" in snapshot.next
    confirmation_request = (
        _confirmation_request(report)
        if awaiting_confirmation and report is not None
        else None
    )
    submission = (
        SupervisorAnalysisSubmission.model_validate(
            values["analysis_submission"]
        )
        if values.get("analysis_submission") is not None
        else None
    )
    completion = (
        SupervisorAnalysisCompletion.model_validate(
            values["analysis_completion"]
        )
        if values.get("analysis_completion") is not None
        else None
    )
    return SiteSelectionSupervisorRun(
        session_id=session_id,
        checkpoint_id=_snapshot_checkpoint_id(snapshot),
        status=(
            SupervisorStatus.AWAITING_CONFIRMATION
            if awaiting_confirmation
            else (
                SupervisorStatus.AWAITING_ANALYSIS
                if awaiting_analysis
                else SupervisorStatus(values["status"])
            )
        ),
        discovery_report=report,
        confirmation_request=confirmation_request,
        confirmation=values.get("confirmation"),
        analysis_run_id=(submission.run_id if submission is not None else None),
        analysis_run_status=(
            completion.status
            if completion is not None
            else (submission.status if submission is not None else None)
        ),
        analysis_error_type=values.get("analysis_error_type"),
        analysis_state=values.get("analysis_state"),
        execution_plan=values.get("execution_plan", plan),
        supervisor_trace=values.get("supervisor_trace", []),
    )


def _snapshot_checkpoint_id(snapshot) -> str:
    config = snapshot.config or {}
    configurable = config.get("configurable", {})
    checkpoint_id = str(configurable.get("checkpoint_id", "")).strip()
    if not checkpoint_id:
        raise SupervisorConfigurationError(
            "Supervisor Checkpointer 未返回 checkpoint_id"
        )
    return checkpoint_id


def _thread_config(session_id: str) -> dict:
    normalized = session_id.strip()
    if not normalized:
        raise ValueError("Supervisor session_id 不能为空")
    return {"configurable": {"thread_id": normalized}}


def _elapsed_ms(timer: Callable[[], float], started_at: float) -> float:
    return max(0.0, timer() - started_at) * 1_000
