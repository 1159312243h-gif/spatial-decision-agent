from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from app.schemas.site_selection import (
    SiteSelectionAnalysisCreate,
    SiteSelectionPOIPreviewRequest,
)
from app.services.site_selection_service import (
    SiteSelectionRuntime,
    SiteSelectionRuntimeConfigurationError,
    SiteSelectionRuntimeProvider,
)
from app.services.site_selection_artifacts import (
    FileSystemSiteSelectionReportStore,
    SiteSelectionReportNotFoundError,
)
from app.services.site_selection_explanation import (
    SiteSelectionEvidenceExplainer,
    failed_explanation,
    unconfigured_explanation,
)
from practice.site_selection import (
    AgentState,
    AnalysisStatus,
    CandidateDiscoverySnapshotNotFoundError,
    DatasetManifest,
    POIFeatureSet,
    POIQuery,
    ProjectRequest,
    HumanReviewState,
    HumanReviewStatus,
    RunStageStatus,
    RunStageTrace,
    SiteSelectionWorkflowDependencies,
    SnapshotReusingPOIGateway,
    build_human_review_state,
    run_parallel_site_selection_workflow,
    validate_snapshot_selection,
)
from practice.site_selection.storage import (
    RedisSiteSelectionRuntimeStore,
    RunEvent,
    RunEventType,
    RunState,
    RunStatus,
)


_SAFE_SUPERVISOR_SESSION_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class SiteSelectionRunServiceUnavailableError(RuntimeError):
    """Raised when Redis-backed run services were not configured."""


class SiteSelectionRunNotFoundError(LookupError):
    """Raised when a run ID has no live Redis state."""


class SiteSelectionRunStateInconsistentError(RuntimeError):
    """Raised when an idempotency mapping points to expired run state."""


class SiteSelectionRunConflictError(RuntimeError):
    """Raised when an operation is invalid for the current run status."""


class SiteSelectionRunServiceProtocol(Protocol):
    def create_run(
        self,
        command: SiteSelectionAnalysisCreate,
        *,
        idempotency_key: str | None = None,
        supervisor_session_id: str | None = None,
    ) -> RunState: ...

    def get_run(self, run_id: str) -> RunState: ...

    def get_events(self, run_id: str) -> list[RunEvent]: ...

    def get_report_path(self, run_id: str) -> str: ...

    def cancel_run(self, run_id: str) -> RunState: ...

    def acknowledge_human_review(
        self,
        run_id: str,
        *,
        note: str | None = None,
    ) -> RunState: ...

    def preview_poi(
        self,
        command: SiteSelectionPOIPreviewRequest,
    ) -> POIPreviewResult: ...


@dataclass(frozen=True)
class POIPreviewResult:
    feature_set: POIFeatureSet
    cached: bool


@dataclass(frozen=True)
class PreparedSiteSelectionRun:
    state: RunState
    created: bool


RunWorkflow = Callable[
    [
        ProjectRequest,
        Iterable[DatasetManifest],
        SiteSelectionWorkflowDependencies,
    ],
    AgentState,
]


class SiteSelectionRunService:
    """Execute runs and persist their lifecycle in Redis."""

    def __init__(
        self,
        runtime_provider: SiteSelectionRuntimeProvider,
        runtime_store: RedisSiteSelectionRuntimeStore,
        *,
        workflow_runner: RunWorkflow = run_parallel_site_selection_workflow,
        clock: Callable[[], datetime] | None = None,
        run_id_factory: Callable[[], str] | None = None,
        request_id_factory: Callable[[], str] | None = None,
        report_store: FileSystemSiteSelectionReportStore | None = None,
        explainer: SiteSelectionEvidenceExplainer | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if runtime_provider is None or runtime_store is None:
            raise ValueError("运行服务必须配置 RuntimeProvider 和 Redis Store")
        self._runtime_provider = runtime_provider
        self._store = runtime_store
        self._workflow_runner = workflow_runner
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._run_id_factory = run_id_factory or (lambda: f"run-{uuid4()}")
        self._request_id_factory = request_id_factory or (
            lambda: f"analysis-{uuid4()}"
        )
        self._report_store = report_store
        self._explainer = explainer
        self._monotonic = monotonic or perf_counter

    def create_run(
        self,
        command: SiteSelectionAnalysisCreate,
        *,
        idempotency_key: str | None = None,
        supervisor_session_id: str | None = None,
    ) -> RunState:
        prepared = self.prepare_run(
            command,
            idempotency_key=idempotency_key,
            supervisor_session_id=supervisor_session_id,
        )
        if not prepared.created:
            return prepared.state
        return self.execute_run(prepared.state.run_id, command)

    def prepare_run(
        self,
        command: SiteSelectionAnalysisCreate,
        *,
        idempotency_key: str | None = None,
        supervisor_session_id: str | None = None,
    ) -> PreparedSiteSelectionRun:
        runtime = self._resolve_runtime(command.project_type)
        request = _build_request(
            command,
            request_id=self._request_id_factory(),
            requested_at=self._clock(),
        )
        self._dependencies_for(command, request, runtime)
        proposed_run_id = self._run_id_factory()
        if idempotency_key is not None:
            claim = self._store.claim_idempotency(
                idempotency_key,
                proposed_run_id,
                request_fingerprint=_command_fingerprint(command),
            )
            if not claim.created:
                existing = self._store.run_states.get(claim.run_id)
                if existing is None:
                    raise SiteSelectionRunStateInconsistentError(
                        "幂等键引用的运行状态已过期"
                    )
                return PreparedSiteSelectionRun(state=existing, created=False)

        run_id = proposed_run_id
        base_details = {
            "request_id": request.request_id,
            "project_type": request.project_type.value,
            "analysis_scope": request.analysis_scope.value,
            "requested_at": request.requested_at.isoformat(),
            "poi_evidence_snapshot_id": command.poi_evidence_snapshot_id,
            "poi_evidence_snapshot_reused": False,
        }
        if supervisor_session_id is not None:
            base_details["supervisor_session_id"] = (
                _normalize_supervisor_session_id(supervisor_session_id)
            )
        state = self._store.run_states.update(
            run_id,
            RunStatus.QUEUED,
            details=base_details,
            updated_at=self._clock(),
        )
        self._append_event(run_id, RunEventType.CREATED, base_details)
        return PreparedSiteSelectionRun(state=state, created=True)

    def mark_enqueued(self, run_id: str, *, job_id: str) -> RunState:
        state = self.get_run(run_id)
        if state.status is not RunStatus.QUEUED:
            raise SiteSelectionRunConflictError(
                f"只有 queued 运行可以登记队列任务：{state.status.value}"
            )
        details = {**state.details, "queue_job_id": job_id}
        updated = self._store.run_states.transition(
            run_id,
            {RunStatus.QUEUED},
            RunStatus.QUEUED,
            details=details,
            updated_at=self._clock(),
        )
        if updated is None:
            latest = self.get_run(run_id)
            raise SiteSelectionRunConflictError(
                f"运行登记队列任务时状态已变为：{latest.status.value}"
            )
        self._append_event(
            run_id,
            RunEventType.ENQUEUED,
            {"queue_job_id": job_id},
        )
        return updated

    def mark_enqueue_failed(self, run_id: str, exc: Exception) -> RunState:
        state = self.get_run(run_id)
        error = f"选址任务入队失败：{type(exc).__name__}"
        details = {**state.details, "queue_error_type": type(exc).__name__}
        failed = self._store.run_states.transition(
            run_id,
            {RunStatus.QUEUED},
            RunStatus.FAILED,
            error=error,
            details=details,
            updated_at=self._clock(),
        )
        if failed is None:
            return self.get_run(run_id)
        self._append_event(
            run_id,
            RunEventType.FAILED,
            {"error": error},
        )
        return failed

    def execute_run(
        self,
        run_id: str,
        command: SiteSelectionAnalysisCreate,
    ) -> RunState:
        state = self.get_run(run_id)
        if state.status in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        }:
            return state
        if state.status is not RunStatus.QUEUED:
            raise SiteSelectionRunConflictError(
                f"运行不能从 {state.status.value} 再次启动"
            )
        if state.details.get("project_type") != command.project_type.value:
            raise SiteSelectionRunStateInconsistentError(
                "排队运行的项目类型与任务载荷不一致"
            )
        if state.details.get("analysis_scope") != command.analysis_scope.value:
            raise SiteSelectionRunStateInconsistentError(
                "排队运行的分析范围与任务载荷不一致"
            )

        run_started_at = self._monotonic()
        traces: list[RunStageTrace] = []
        runtime = self._resolve_runtime(command.project_type)
        request_id = state.details.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise SiteSelectionRunStateInconsistentError(
                "排队运行缺少 request_id"
            )
        requested_at_raw = state.details.get("requested_at")
        if not isinstance(requested_at_raw, str):
            raise SiteSelectionRunStateInconsistentError(
                "排队运行缺少 requested_at"
            )
        try:
            requested_at = datetime.fromisoformat(requested_at_raw)
        except ValueError as exc:
            raise SiteSelectionRunStateInconsistentError(
                "排队运行的 requested_at 无效"
            ) from exc
        request = _build_request(
            command,
            request_id=request_id,
            requested_at=requested_at,
        )
        workflow_dependencies = self._dependencies_for(
            command,
            request,
            runtime,
        )
        base_details = dict(state.details)
        running = self._store.run_states.transition(
            run_id,
            {RunStatus.QUEUED},
            RunStatus.RUNNING,
            details=base_details,
            updated_at=self._clock(),
        )
        if running is None:
            latest = self.get_run(run_id)
            if latest.status in {
                RunStatus.COMPLETED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
                RunStatus.TIMED_OUT,
            }:
                return latest
            raise SiteSelectionRunConflictError(
                f"运行启动时状态已变为：{latest.status.value}"
            )
        self._append_event(run_id, RunEventType.STARTED, base_details)

        try:
            analysis = self._timed_stage(
                "workflow",
                lambda: AgentState.model_validate(
                    self._workflow_runner(
                        request,
                        runtime.datasets,
                        workflow_dependencies,
                    )
                ),
                traces,
            )
        except Exception as exc:
            terminal = self._externally_terminated(run_id)
            if terminal is not None:
                return terminal
            error = f"选址运行发生未处理异常：{type(exc).__name__}"
            failed = self._store.run_states.transition(
                run_id,
                {RunStatus.RUNNING},
                RunStatus.FAILED,
                error=error,
                details={
                    **base_details,
                    "trace": _finalize_trace(
                        traces,
                        run_started_at,
                        self._monotonic(),
                        succeeded=False,
                    ),
                },
                updated_at=self._clock(),
            )
            if failed is None:
                return self.get_run(run_id)
            self._append_event(
                run_id,
                RunEventType.FAILED,
                {**base_details, "error": error},
            )
            return failed

        details = {
            **base_details,
            "analysis": analysis.model_dump(mode="json"),
            "poi_evidence_snapshot_reused": (
                analysis.status is AnalysisStatus.COMPLETED
                and _analysis_reused_poi_snapshot(analysis)
            ),
        }
        terminal = self._externally_terminated(run_id)
        if terminal is not None:
            return terminal
        if analysis.status is not AnalysisStatus.COMPLETED:
            workflow_trace = traces[-1]
            traces[-1] = workflow_trace.model_copy(
                update={
                    "status": RunStageStatus.FAILED,
                    "error_type": "AnalysisFailed",
                }
            )
        if analysis.status is AnalysisStatus.COMPLETED:
            review_report = analysis.evidence_review_report
            try:
                if review_report is None:
                    raise SiteSelectionRunStateInconsistentError(
                        "completed analysis is missing evidence review"
                    )
                human_review = self._timed_stage(
                    "human_review",
                    lambda: build_human_review_state(
                        review_report,
                        updated_at=self._clock(),
                    ),
                    traces,
                )
            except Exception as exc:
                error = f"Run finalization failed: {type(exc).__name__}"
                failed = self._store.run_states.transition(
                    run_id,
                    {RunStatus.RUNNING},
                    RunStatus.FAILED,
                    error=error,
                    details={
                        **details,
                        "trace": _finalize_trace(
                            traces,
                            run_started_at,
                            self._monotonic(),
                            succeeded=False,
                        ),
                    },
                    updated_at=self._clock(),
                )
                if failed is None:
                    return self.get_run(run_id)
                self._append_event(
                    run_id,
                    RunEventType.FAILED,
                    {**base_details, "error": error},
                )
                return failed
            details["human_review"] = human_review.model_dump(mode="json")
            if self._explainer is None:
                explanation = unconfigured_explanation()
                traces.append(
                    RunStageTrace(
                        stage="explanation",
                        status=RunStageStatus.SKIPPED,
                        elapsed_ms=0,
                    )
                )
            else:
                try:
                    explanation = self._timed_stage(
                        "explanation",
                        lambda: self._explainer.explain(analysis),
                        traces,
                    )
                except Exception as exc:
                    explanation = failed_explanation(exc)
            details["explanation"] = explanation.model_dump(mode="json")
            if self._report_store is not None:
                try:
                    artifact = self._timed_stage(
                        "report",
                        lambda: self._report_store.create(run_id, analysis),
                        traces,
                    )
                except Exception as exc:
                    error = (
                        "选址报告生成失败："
                        f"{type(exc).__name__}"
                    )
                    failed = self._store.run_states.transition(
                        run_id,
                        {RunStatus.RUNNING},
                        RunStatus.FAILED,
                        error=error,
                        details={
                            **details,
                            "trace": _finalize_trace(
                                traces,
                                run_started_at,
                                self._monotonic(),
                                succeeded=False,
                            ),
                        },
                        updated_at=self._clock(),
                    )
                    if failed is None:
                        return self.get_run(run_id)
                    self._append_event(
                        run_id,
                        RunEventType.FAILED,
                        {**base_details, "error": error},
                    )
                    return failed
                details["report_url"] = artifact.public_url
                details["report_sha256"] = artifact.sha256
            else:
                traces.append(
                    RunStageTrace(
                        stage="report",
                        status=RunStageStatus.SKIPPED,
                        elapsed_ms=0,
                    )
                )
            details["trace"] = _finalize_trace(
                traces,
                run_started_at,
                self._monotonic(),
                succeeded=True,
            )
            terminal = self._externally_terminated(run_id)
            if terminal is not None:
                return terminal
            completed = self._store.run_states.transition(
                run_id,
                {RunStatus.RUNNING},
                RunStatus.COMPLETED,
                details=details,
                updated_at=self._clock(),
            )
            if completed is None:
                return self.get_run(run_id)
            self._append_event(run_id, RunEventType.COMPLETED, base_details)
            return completed

        if analysis.status is AnalysisStatus.FAILED:
            error = "；".join(analysis.errors) or "选址分析失败"
        else:
            error = f"选址工作流返回非终态：{analysis.status.value}"
        failed = self._store.run_states.transition(
            run_id,
            {RunStatus.RUNNING},
            RunStatus.FAILED,
            error=error,
            details={
                **details,
                "trace": _finalize_trace(
                    traces,
                    run_started_at,
                    self._monotonic(),
                    succeeded=False,
                ),
            },
            updated_at=self._clock(),
        )
        if failed is None:
            return self.get_run(run_id)
        self._append_event(
            run_id,
            RunEventType.FAILED,
            {**base_details, "error": error},
        )
        return failed

    def mark_cancelled(self, run_id: str) -> RunState:
        state = self.get_run(run_id)
        if state.status is RunStatus.CANCELLED:
            return state
        if state.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
            raise SiteSelectionRunConflictError(
                f"只有 queued 或 running 运行可以取消：{state.status.value}"
            )
        details = {
            **state.details,
            "cancelled_at": self._clock().isoformat(),
        }
        cancelled = self._store.run_states.transition(
            run_id,
            {RunStatus.QUEUED, RunStatus.RUNNING},
            RunStatus.CANCELLED,
            details=details,
            updated_at=self._clock(),
        )
        if cancelled is None:
            latest = self.get_run(run_id)
            if latest.status is RunStatus.CANCELLED:
                return latest
            raise SiteSelectionRunConflictError(
                f"运行取消时状态已变为：{latest.status.value}"
            )
        self._append_event(
            run_id,
            RunEventType.CANCELLED,
            {"queue_job_id": details.get("queue_job_id")},
        )
        return cancelled

    def mark_timed_out(
        self,
        run_id: str,
        *,
        error_type: str = "JobTimeoutException",
    ) -> RunState:
        state = self.get_run(run_id)
        if state.status in {RunStatus.CANCELLED, RunStatus.TIMED_OUT}:
            return state
        if state.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
            return state
        error = f"选址任务执行超时：{error_type}"
        details = {**state.details, "worker_error_type": error_type}
        timed_out = self._store.run_states.transition(
            run_id,
            {RunStatus.QUEUED, RunStatus.RUNNING},
            RunStatus.TIMED_OUT,
            error=error,
            details=details,
            updated_at=self._clock(),
        )
        if timed_out is None:
            return self.get_run(run_id)
        self._append_event(
            run_id,
            RunEventType.TIMED_OUT,
            {"error": error},
        )
        return timed_out

    def get_run(self, run_id: str) -> RunState:
        state = self._store.run_states.get(run_id)
        if state is None:
            raise SiteSelectionRunNotFoundError(f"选址运行不存在：{run_id}")
        return state

    def cancel_run(self, run_id: str) -> RunState:
        return self.mark_cancelled(run_id)

    def acknowledge_human_review(
        self,
        run_id: str,
        *,
        note: str | None = None,
    ) -> RunState:
        state = self.get_run(run_id)
        raw_review = state.details.get("human_review")
        if raw_review is None:
            raise SiteSelectionRunStateInconsistentError(
                "run is missing human review state"
            )
        review = HumanReviewState.model_validate(raw_review)
        if review.status is HumanReviewStatus.NOT_REQUIRED:
            raise SiteSelectionRunStateInconsistentError(
                "run does not require human review"
            )
        if review.status is HumanReviewStatus.ACKNOWLEDGED:
            return state

        normalized_note = note.strip() if note is not None else None
        if note is not None and not normalized_note:
            raise ValueError("human review note cannot be blank")
        acknowledged = HumanReviewState(
            status=HumanReviewStatus.ACKNOWLEDGED,
            reason_codes=review.reason_codes,
            updated_at=self._clock(),
            note=normalized_note,
        )
        details = dict(state.details)
        details["human_review"] = acknowledged.model_dump(mode="json")
        updated = self._store.run_states.update(
            run_id,
            state.status,
            details=details,
            updated_at=self._clock(),
        )
        self._append_event(
            run_id,
            RunEventType.HUMAN_REVIEW_ACKNOWLEDGED,
            {
                "reason_codes": acknowledged.reason_codes,
                "boundary": "acknowledgement_not_compliance_approval",
            },
        )
        return updated

    def get_events(self, run_id: str) -> list[RunEvent]:
        self.get_run(run_id)
        return self._store.list_events(run_id)

    def get_report_path(self, run_id: str) -> str:
        state = self.get_run(run_id)
        if state.status is not RunStatus.COMPLETED:
            raise SiteSelectionReportNotFoundError(
                f"选址运行尚无可下载报告：{run_id}"
            )
        if self._report_store is None or not state.details.get("report_url"):
            raise SiteSelectionReportNotFoundError(
                f"选址运行报告未配置：{run_id}"
            )
        return str(self._report_store.resolve(run_id))

    def preview_poi(
        self,
        command: SiteSelectionPOIPreviewRequest,
    ) -> POIPreviewResult:
        runtime = self._resolve_runtime(command.project_type)
        query = command.to_query()
        cache_scope = _runtime_cache_scope(runtime)
        if command.refresh:
            self._store.invalidate_cached_poi(
                query,
                cache_scope=cache_scope,
            )
        cached = self._store.get_cached_poi(query, cache_scope=cache_scope)
        if cached is not None:
            return POIPreviewResult(feature_set=cached, cached=True)

        result = runtime.dependencies.poi_gateway.search(query)
        if result.query != query:
            raise SiteSelectionRuntimeConfigurationError(
                "POI 网关返回了与预览请求不一致的查询"
            )
        self._store.save_cached_poi(result, cache_scope=cache_scope)
        return POIPreviewResult(feature_set=result, cached=False)

    def _resolve_runtime(self, project_type) -> SiteSelectionRuntime:
        runtime = self._runtime_provider.resolve(project_type)
        if runtime.project_type is not project_type:
            raise SiteSelectionRuntimeConfigurationError(
                "运行时项目类型与运行请求不一致"
            )
        return runtime

    def _dependencies_for(
        self,
        command: SiteSelectionAnalysisCreate,
        request: ProjectRequest,
        runtime: SiteSelectionRuntime,
    ) -> SiteSelectionWorkflowDependencies:
        snapshot_id = command.poi_evidence_snapshot_id
        if snapshot_id is None:
            return runtime.dependencies
        snapshot = self._store.get_candidate_discovery_snapshot(snapshot_id)
        if snapshot is None:
            raise CandidateDiscoverySnapshotNotFoundError(
                f"候选发现证据快照不存在或已过期：{snapshot_id}"
            )
        validate_snapshot_selection(
            snapshot,
            command.project_type,
            request.candidate_parcels,
        )
        return replace(
            runtime.dependencies,
            poi_gateway=SnapshotReusingPOIGateway(
                snapshot,
                fallback=runtime.dependencies.poi_gateway,
            ),
        )

    def _append_event(
        self,
        run_id: str,
        event_type: RunEventType,
        details: dict,
    ) -> None:
        self._store.append_event(
            RunEvent(
                run_id=run_id,
                event_type=event_type,
                occurred_at=self._clock(),
                details=details,
            )
        )

    def _externally_terminated(self, run_id: str) -> RunState | None:
        state = self.get_run(run_id)
        if state.status in {RunStatus.CANCELLED, RunStatus.TIMED_OUT}:
            return state
        return None

    def _timed_stage(
        self,
        stage: str,
        operation: Callable[[], object],
        traces: list[RunStageTrace],
    ):
        started_at = self._monotonic()
        try:
            result = operation()
        except Exception as exc:
            traces.append(
                _stage_trace(
                    stage,
                    RunStageStatus.FAILED,
                    started_at,
                    self._monotonic(),
                    error_type=type(exc).__name__,
                )
            )
            raise
        traces.append(
            _stage_trace(
                stage,
                RunStageStatus.SUCCEEDED,
                started_at,
                self._monotonic(),
            )
        )
        return result


class UnconfiguredSiteSelectionRunService:
    """Fail-closed default until both runtime and Redis are explicitly wired."""

    def _unavailable(self):
        raise SiteSelectionRunServiceUnavailableError(
            "选址运行服务尚未配置 Redis 运行时存储"
        )

    def create_run(
        self,
        command,
        *,
        idempotency_key=None,
        supervisor_session_id=None,
    ):
        return self._unavailable()

    def get_run(self, run_id):
        return self._unavailable()

    def get_events(self, run_id):
        return self._unavailable()

    def get_report_path(self, run_id):
        return self._unavailable()

    def cancel_run(self, run_id):
        return self._unavailable()

    def acknowledge_human_review(self, run_id, *, note=None):
        return self._unavailable()

    def preview_poi(self, command):
        return self._unavailable()


def _build_request(
    command: SiteSelectionAnalysisCreate,
    *,
    request_id: str,
    requested_at: datetime,
) -> ProjectRequest:
    return ProjectRequest(
        request_id=request_id,
        project_type=command.project_type,
        analysis_scope=command.analysis_scope,
        candidate_parcels=[
            parcel.to_domain() for parcel in command.candidate_parcels
        ],
        requested_at=requested_at,
    )


def _analysis_reused_poi_snapshot(analysis: AgentState) -> bool:
    return any(
        feature_set.source.evidence_reused
        for result in analysis.results
        for feature_set in result.poi_evidence.feature_sets
    )


def _runtime_cache_scope(runtime: SiteSelectionRuntime) -> str:
    gateway = runtime.dependencies.poi_gateway
    payload = {
        "project_type": runtime.project_type.value,
        "poi_source": getattr(
            gateway,
            "cache_token",
            type(gateway).__name__,
        ),
        "datasets": sorted(
            (dataset.dataset_id, dataset.version)
            for dataset in runtime.datasets
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _command_fingerprint(command: SiteSelectionAnalysisCreate) -> str:
    canonical = json.dumps(
        command.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_supervisor_session_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 200:
        raise ValueError("Supervisor session_id 长度必须在 1 到 200 之间")
    if _SAFE_SUPERVISOR_SESSION_ID.fullmatch(normalized) is None:
        raise ValueError(
            "Supervisor session_id 只能包含字母、数字、点、下划线和连字符"
        )
    return normalized


def _stage_trace(
    stage: str,
    status: RunStageStatus,
    started_at: float,
    finished_at: float,
    *,
    error_type: str | None = None,
) -> RunStageTrace:
    return RunStageTrace(
        stage=stage,
        status=status,
        elapsed_ms=round(max(0.0, finished_at - started_at) * 1_000, 3),
        error_type=error_type,
    )


def _finalize_trace(
    traces: list[RunStageTrace],
    run_started_at: float,
    finished_at: float,
    *,
    succeeded: bool,
) -> list[dict]:
    total = _stage_trace(
        "total",
        RunStageStatus.SUCCEEDED if succeeded else RunStageStatus.FAILED,
        run_started_at,
        finished_at,
        error_type=None if succeeded else "RunFailed",
    )
    return [
        trace.model_dump(mode="json")
        for trace in [*traces, total]
    ]
