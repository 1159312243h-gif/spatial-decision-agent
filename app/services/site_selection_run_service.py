from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
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
from practice.site_selection import (
    AgentState,
    AnalysisStatus,
    DatasetManifest,
    POIFeatureSet,
    POIQuery,
    ProjectRequest,
    SiteSelectionWorkflowDependencies,
    run_parallel_site_selection_workflow,
)
from practice.site_selection.storage import (
    RedisSiteSelectionRuntimeStore,
    RunEvent,
    RunEventType,
    RunState,
    RunStatus,
)


class SiteSelectionRunServiceUnavailableError(RuntimeError):
    """Raised when Redis-backed run services were not configured."""


class SiteSelectionRunNotFoundError(LookupError):
    """Raised when a run ID has no live Redis state."""


class SiteSelectionRunStateInconsistentError(RuntimeError):
    """Raised when an idempotency mapping points to expired run state."""


class SiteSelectionRunServiceProtocol(Protocol):
    def create_run(
        self,
        command: SiteSelectionAnalysisCreate,
        *,
        idempotency_key: str | None = None,
    ) -> RunState: ...

    def get_run(self, run_id: str) -> RunState: ...

    def get_events(self, run_id: str) -> list[RunEvent]: ...

    def preview_poi(
        self,
        command: SiteSelectionPOIPreviewRequest,
    ) -> POIPreviewResult: ...


@dataclass(frozen=True)
class POIPreviewResult:
    feature_set: POIFeatureSet
    cached: bool


RunWorkflow = Callable[
    [
        ProjectRequest,
        Iterable[DatasetManifest],
        SiteSelectionWorkflowDependencies,
    ],
    AgentState,
]


class SiteSelectionRunService:
    """Synchronous first-version run API backed by Redis runtime records."""

    def __init__(
        self,
        runtime_provider: SiteSelectionRuntimeProvider,
        runtime_store: RedisSiteSelectionRuntimeStore,
        *,
        workflow_runner: RunWorkflow = run_parallel_site_selection_workflow,
        clock: Callable[[], datetime] | None = None,
        run_id_factory: Callable[[], str] | None = None,
        request_id_factory: Callable[[], str] | None = None,
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

    def create_run(
        self,
        command: SiteSelectionAnalysisCreate,
        *,
        idempotency_key: str | None = None,
    ) -> RunState:
        runtime = self._resolve_runtime(command.project_type)
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
                return existing

        run_id = proposed_run_id
        request = _build_request(
            command,
            request_id=self._request_id_factory(),
            requested_at=self._clock(),
        )
        base_details = {
            "request_id": request.request_id,
            "project_type": request.project_type.value,
        }
        self._store.run_states.update(
            run_id,
            RunStatus.QUEUED,
            details=base_details,
            updated_at=self._clock(),
        )
        self._append_event(run_id, RunEventType.CREATED, base_details)
        self._store.run_states.update(
            run_id,
            RunStatus.RUNNING,
            details=base_details,
            updated_at=self._clock(),
        )
        self._append_event(run_id, RunEventType.STARTED, base_details)

        try:
            analysis = self._workflow_runner(
                request,
                runtime.datasets,
                runtime.dependencies,
            )
        except Exception as exc:
            error = f"选址运行发生未处理异常：{type(exc).__name__}"
            failed = self._store.run_states.update(
                run_id,
                RunStatus.FAILED,
                error=error,
                details=base_details,
                updated_at=self._clock(),
            )
            self._append_event(
                run_id,
                RunEventType.FAILED,
                {**base_details, "error": error},
            )
            return failed

        details = {
            **base_details,
            "analysis": analysis.model_dump(mode="json"),
        }
        if analysis.status is AnalysisStatus.COMPLETED:
            completed = self._store.run_states.update(
                run_id,
                RunStatus.COMPLETED,
                details=details,
                updated_at=self._clock(),
            )
            self._append_event(run_id, RunEventType.COMPLETED, base_details)
            return completed

        if analysis.status is AnalysisStatus.FAILED:
            error = "；".join(analysis.errors) or "选址分析失败"
        else:
            error = f"选址工作流返回非终态：{analysis.status.value}"
        failed = self._store.run_states.update(
            run_id,
            RunStatus.FAILED,
            error=error,
            details=details,
            updated_at=self._clock(),
        )
        self._append_event(
            run_id,
            RunEventType.FAILED,
            {**base_details, "error": error},
        )
        return failed

    def get_run(self, run_id: str) -> RunState:
        state = self._store.run_states.get(run_id)
        if state is None:
            raise SiteSelectionRunNotFoundError(f"选址运行不存在：{run_id}")
        return state

    def get_events(self, run_id: str) -> list[RunEvent]:
        self.get_run(run_id)
        return self._store.list_events(run_id)

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


class UnconfiguredSiteSelectionRunService:
    """Fail-closed default until both runtime and Redis are explicitly wired."""

    def _unavailable(self):
        raise SiteSelectionRunServiceUnavailableError(
            "选址运行服务尚未配置 Redis 运行时存储"
        )

    def create_run(self, command, *, idempotency_key=None):
        return self._unavailable()

    def get_run(self, run_id):
        return self._unavailable()

    def get_events(self, run_id):
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
        candidate_parcels=[
            parcel.to_domain() for parcel in command.candidate_parcels
        ],
        requested_at=requested_at,
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
