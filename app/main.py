from collections.abc import Callable
from contextlib import asynccontextmanager
import json
from pathlib import Path

from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.site_selection import router as site_selection_router
from app.services.site_selection_service import (
    SiteSelectionAnalysisService,
    SiteSelectionRuntimeProvider,
    UnconfiguredSiteSelectionRuntimeProvider,
)
from app.services.site_selection_run_service import (
    SiteSelectionRunService,
    UnconfiguredSiteSelectionRunService,
)
from app.services.site_selection_queue import (
    QueuedSiteSelectionRunService,
    SiteSelectionJobQueue,
)
from app.services.site_selection_artifacts import FileSystemSiteSelectionReportStore
from app.services.site_selection_explanation import SiteSelectionEvidenceExplainer
from app.services.site_selection_conversation import (
    SiteSelectionConversationService,
)
from app.services.site_selection_supervisor import (
    SiteSelectionSupervisorServiceProtocol,
    SupervisorSessionCoordinator,
    UnconfiguredSiteSelectionSupervisorService,
    build_site_selection_supervisor_service,
)
from app.site_selection_bootstrap import (
    build_site_selection_bootstrap_from_environment,
)
from practice.site_selection.storage import RedisSiteSelectionRuntimeStore
from practice.site_selection import (
    CandidateDiscoveryService,
    FallbackScenarioInterpreter,
    FixtureRegionResolver,
    InMemoryScenarioSessionStore,
    InMemoryScenarioMemoryStore,
    RegionCatalogEntry,
)
from practice.site_selection.scenario import RegionResolver, ScenarioInterpreter
from practice.site_selection.memory import ScenarioMemoryStore


def create_app(
    runtime_provider: SiteSelectionRuntimeProvider | None = None,
    *,
    run_store: RedisSiteSelectionRuntimeStore | None = None,
    report_store: FileSystemSiteSelectionReportStore | None = None,
    mcp_server: object | None = None,
    resource_closer: Callable[[], None] | None = None,
    explainer: SiteSelectionEvidenceExplainer | None = None,
    job_queue: SiteSelectionJobQueue | None = None,
    supervisor_checkpointer=None,
    supervisor_coordinator: SupervisorSessionCoordinator | None = None,
    supervisor_service: SiteSelectionSupervisorServiceProtocol | None = None,
    scenario_interpreter: ScenarioInterpreter | None = None,
    region_resolver: RegionResolver | None = None,
    memory_store: ScenarioMemoryStore | None = None,
    land_use_provider=None,
) -> FastAPI:
    lifespan = None
    if resource_closer is not None:
        @asynccontextmanager
        async def lifespan(_application: FastAPI):
            try:
                yield
            finally:
                resource_closer()

    application = FastAPI(
        title="AI Agent Learning API",
        version="0.1.0",
        lifespan=lifespan,
    )
    provider = (
        runtime_provider
        if runtime_provider is not None
        else UnconfiguredSiteSelectionRuntimeProvider()
    )
    analysis_service = SiteSelectionAnalysisService(
        provider,
        snapshot_store=run_store,
    )
    candidate_discovery_service = CandidateDiscoveryService(
        provider,
        snapshot_store=run_store,
        land_use_provider=land_use_provider,
    )
    application.state.site_selection_analysis_service = analysis_service
    application.state.site_selection_candidate_discovery_service = (
        candidate_discovery_service
    )
    active_region_resolver = region_resolver or FixtureRegionResolver(
        _load_default_region_catalog()
    )
    application.state.site_selection_conversation_service = (
        SiteSelectionConversationService(
            run_store or InMemoryScenarioSessionStore(),
            FallbackScenarioInterpreter(scenario_interpreter),
            active_region_resolver,
            memory_store=memory_store or InMemoryScenarioMemoryStore(),
        )
    )
    if run_store is not None:
        run_executor = SiteSelectionRunService(
            provider,
            run_store,
            report_store=report_store,
            explainer=explainer,
        )
        run_service = (
            QueuedSiteSelectionRunService(run_executor, job_queue)
            if job_queue is not None
            else run_executor
        )
    else:
        run_service = UnconfiguredSiteSelectionRunService()
    application.state.site_selection_run_service = run_service
    if supervisor_service is not None:
        application.state.site_selection_supervisor_service = supervisor_service
    elif supervisor_checkpointer is not None and supervisor_coordinator is not None:
        application.state.site_selection_supervisor_service = (
            build_site_selection_supervisor_service(
                discovery_runner=candidate_discovery_service.discover,
                run_service=run_service,
                checkpointer=supervisor_checkpointer,
                coordinator=supervisor_coordinator,
            )
        )
    else:
        application.state.site_selection_supervisor_service = (
            UnconfiguredSiteSelectionSupervisorService()
        )
    application.state.site_selection_mcp_server = mcp_server

    application.include_router(health_router)
    application.include_router(documents_router)
    application.include_router(chat_router)
    application.include_router(site_selection_router)
    return application


def create_app_from_environment() -> FastAPI:
    bootstrap = build_site_selection_bootstrap_from_environment()
    if bootstrap is None:
        return create_app()
    application = create_app(
        bootstrap.runtime_provider,
        run_store=bootstrap.run_store,
        report_store=bootstrap.report_store,
        mcp_server=bootstrap.mcp_server,
        resource_closer=bootstrap.close,
        explainer=bootstrap.explainer,
        job_queue=bootstrap.job_queue,
        supervisor_checkpointer=bootstrap.supervisor_checkpointer,
        supervisor_coordinator=bootstrap.supervisor_coordinator,
        scenario_interpreter=bootstrap.scenario_interpreter,
        region_resolver=bootstrap.region_resolver,
        memory_store=bootstrap.memory_store,
        land_use_provider=(
            bootstrap.land_use_provider.provider
            if bootstrap.land_use_provider is not None
            else None
        ),
    )
    application.state.site_selection_bootstrap = bootstrap
    return application


def _load_default_region_catalog() -> list[RegionCatalogEntry]:
    path = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "regions.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [RegionCatalogEntry.model_validate(item) for item in payload["entries"]]


app = create_app_from_environment()
