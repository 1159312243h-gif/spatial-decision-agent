from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from app.schemas.site_selection import SiteSelectionAnalysisCreate
from practice.site_selection import (
    AgentState,
    CandidateDiscoverySnapshotNotFoundError,
    CandidateDiscoverySnapshotStore,
    DatasetManifest,
    ProjectRequest,
    ProjectType,
    SiteSelectionWorkflowDependencies,
    SnapshotReusingPOIGateway,
    run_site_selection_workflow,
    validate_snapshot_selection,
)


class SiteSelectionRuntimeUnavailableError(RuntimeError):
    """Raised when no reviewed runtime configuration is available."""


class SiteSelectionRuntimeConfigurationError(RuntimeError):
    """Raised when a provider returns a runtime for another project type."""


@dataclass(frozen=True)
class SiteSelectionRuntime:
    project_type: ProjectType
    datasets: Sequence[DatasetManifest]
    dependencies: SiteSelectionWorkflowDependencies

    def __post_init__(self) -> None:
        try:
            project_type = ProjectType(self.project_type)
        except (TypeError, ValueError) as exc:
            raise ValueError("选址分析运行时项目类型无效") from exc
        datasets = tuple(
            dataset.model_copy(deep=True) for dataset in self.datasets
        )
        if not datasets:
            raise ValueError("选址分析运行时至少需要一个数据清单")
        object.__setattr__(self, "project_type", project_type)
        object.__setattr__(self, "datasets", datasets)


class SiteSelectionRuntimeProvider(Protocol):
    def resolve(self, project_type: ProjectType) -> SiteSelectionRuntime: ...


class UnconfiguredSiteSelectionRuntimeProvider:
    """Safe default until reviewed scoring, policy, and data config exists."""

    def resolve(self, project_type: ProjectType) -> SiteSelectionRuntime:
        raise SiteSelectionRuntimeUnavailableError(
            f"项目类型尚未配置可执行分析运行时：{project_type.value}"
        )


class SiteSelectionRuntimeRegistry:
    """Read-only project-type lookup for reviewed runtime configurations."""

    def __init__(
        self,
        runtimes: Mapping[ProjectType, SiteSelectionRuntime] | None = None,
    ) -> None:
        self._runtimes: dict[ProjectType, SiteSelectionRuntime] = {}
        for key, runtime in (runtimes or {}).items():
            try:
                project_type = ProjectType(key)
            except (TypeError, ValueError) as exc:
                raise ValueError("运行时注册键不是受支持的项目类型") from exc
            if project_type is not runtime.project_type:
                raise ValueError("运行时注册键必须与运行时项目类型一致")
            self._runtimes[project_type] = _copy_runtime(runtime)

    @property
    def configured_types(self) -> tuple[ProjectType, ...]:
        return tuple(self._runtimes)

    def resolve(self, project_type: ProjectType) -> SiteSelectionRuntime:
        try:
            normalized_type = ProjectType(project_type)
            runtime = self._runtimes[normalized_type]
        except (TypeError, ValueError, KeyError) as exc:
            value = getattr(project_type, "value", project_type)
            raise SiteSelectionRuntimeUnavailableError(
                f"项目类型尚未配置可执行分析运行时：{value}"
            ) from exc
        return _copy_runtime(runtime)


WorkflowRunner = Callable[
    [
        ProjectRequest,
        Iterable[DatasetManifest],
        SiteSelectionWorkflowDependencies,
    ],
    AgentState,
]


class SiteSelectionAnalysisService:
    """Application boundary between HTTP input and the business workflow."""

    def __init__(
        self,
        runtime_provider: SiteSelectionRuntimeProvider,
        *,
        snapshot_store: CandidateDiscoverySnapshotStore | None = None,
        workflow_runner: WorkflowRunner = run_site_selection_workflow,
        clock: Callable[[], datetime] | None = None,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._runtime_provider = runtime_provider
        self._snapshot_store = snapshot_store
        self._workflow_runner = workflow_runner
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._request_id_factory = request_id_factory or (
            lambda: f"analysis-{uuid4()}"
        )

    def analyze(self, command: SiteSelectionAnalysisCreate) -> AgentState:
        request = ProjectRequest(
            request_id=self._request_id_factory(),
            project_type=command.project_type,
            analysis_scope=command.analysis_scope,
            candidate_parcels=[
                parcel.to_domain() for parcel in command.candidate_parcels
            ],
            requested_at=self._clock(),
        )
        runtime = self._runtime_provider.resolve(request.project_type)
        if runtime.project_type is not request.project_type:
            raise SiteSelectionRuntimeConfigurationError(
                "运行时项目类型与分析请求不一致"
            )
        dependencies = runtime.dependencies
        snapshot_id = command.poi_evidence_snapshot_id
        if snapshot_id is not None:
            snapshot = (
                self._snapshot_store.get_candidate_discovery_snapshot(
                    snapshot_id
                )
                if self._snapshot_store is not None
                else None
            )
            if snapshot is None:
                raise CandidateDiscoverySnapshotNotFoundError(
                    f"候选发现证据快照不存在或已过期：{snapshot_id}"
                )
            validate_snapshot_selection(
                snapshot,
                command.project_type,
                request.candidate_parcels,
            )
            dependencies = replace(
                dependencies,
                poi_gateway=SnapshotReusingPOIGateway(
                    snapshot,
                    fallback=dependencies.poi_gateway,
                ),
            )
        return self._workflow_runner(
            request,
            runtime.datasets,
            dependencies,
        )


def _copy_runtime(runtime: SiteSelectionRuntime) -> SiteSelectionRuntime:
    return SiteSelectionRuntime(
        project_type=runtime.project_type,
        datasets=runtime.datasets,
        dependencies=runtime.dependencies,
    )
