from collections.abc import Callable
from contextlib import asynccontextmanager

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
from app.site_selection_bootstrap import (
    build_site_selection_bootstrap_from_environment,
)
from practice.site_selection.storage import RedisSiteSelectionRuntimeStore


def create_app(
    runtime_provider: SiteSelectionRuntimeProvider | None = None,
    *,
    run_store: RedisSiteSelectionRuntimeStore | None = None,
    report_store: FileSystemSiteSelectionReportStore | None = None,
    mcp_server: object | None = None,
    resource_closer: Callable[[], None] | None = None,
    explainer: SiteSelectionEvidenceExplainer | None = None,
    job_queue: SiteSelectionJobQueue | None = None,
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
    application.state.site_selection_analysis_service = (
        SiteSelectionAnalysisService(provider)
    )
    if run_store is not None:
        run_executor = SiteSelectionRunService(
            provider,
            run_store,
            report_store=report_store,
            explainer=explainer,
        )
        application.state.site_selection_run_service = (
            QueuedSiteSelectionRunService(run_executor, job_queue)
            if job_queue is not None
            else run_executor
        )
    else:
        application.state.site_selection_run_service = (
            UnconfiguredSiteSelectionRunService()
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
    )
    application.state.site_selection_bootstrap = bootstrap
    return application


app = create_app_from_environment()
