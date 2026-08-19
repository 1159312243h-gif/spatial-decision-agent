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
from practice.site_selection.storage import RedisSiteSelectionRuntimeStore


def create_app(
    runtime_provider: SiteSelectionRuntimeProvider | None = None,
    *,
    run_store: RedisSiteSelectionRuntimeStore | None = None,
) -> FastAPI:
    application = FastAPI(
        title="AI Agent Learning API",
        version="0.1.0",
    )
    provider = (
        runtime_provider
        if runtime_provider is not None
        else UnconfiguredSiteSelectionRuntimeProvider()
    )
    application.state.site_selection_analysis_service = (
        SiteSelectionAnalysisService(provider)
    )
    application.state.site_selection_run_service = (
        SiteSelectionRunService(provider, run_store)
        if run_store is not None
        else UnconfiguredSiteSelectionRunService()
    )

    application.include_router(health_router)
    application.include_router(documents_router)
    application.include_router(chat_router)
    application.include_router(site_selection_router)
    return application


app = create_app()
