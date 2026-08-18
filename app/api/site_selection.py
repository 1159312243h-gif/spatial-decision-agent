from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.schemas.site_selection import (
    SiteSelectionAnalysisCreate,
    SiteSelectionAnalysisErrorDetail,
    SiteSelectionAnalysisErrorResponse,
    SiteSelectionAnalysisResponse,
    SiteSelectionPreflightRequest,
    SiteSelectionPreflightResponse,
)
from app.services.site_selection_service import (
    SiteSelectionAnalysisService,
    SiteSelectionRuntimeUnavailableError,
)
from practice.site_selection import (
    AnalysisStatus,
    OrchestratorAgent,
    OrchestratorAgentInput,
)


router = APIRouter(prefix="/site-selection", tags=["site-selection"])


def get_site_selection_analysis_service(
    request: Request,
) -> SiteSelectionAnalysisService:
    return request.app.state.site_selection_analysis_service


@router.post(
    "/preflight",
    response_model=SiteSelectionPreflightResponse,
)
def evaluate_site_selection_preflight(
    command: SiteSelectionPreflightRequest,
) -> SiteSelectionPreflightResponse:
    output = OrchestratorAgent().run(
        OrchestratorAgentInput(draft=command.to_draft())
    )
    return SiteSelectionPreflightResponse.from_decision(output.decision)


@router.post(
    "/analyses",
    response_model=SiteSelectionAnalysisResponse,
    responses={
        status.HTTP_409_CONFLICT: {
            "model": SiteSelectionAnalysisErrorResponse,
            "description": "业务证据或分析步骤阻断",
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": SiteSelectionAnalysisErrorResponse,
            "description": "未处理的服务异常",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": SiteSelectionAnalysisErrorResponse,
            "description": "运行配置尚未就绪",
        },
    },
)
def create_site_selection_analysis(
    command: SiteSelectionAnalysisCreate,
    service: Annotated[
        SiteSelectionAnalysisService,
        Depends(get_site_selection_analysis_service),
    ],
) -> SiteSelectionAnalysisResponse:
    try:
        state = service.analyze(command)
    except SiteSelectionRuntimeUnavailableError as exc:
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            SiteSelectionAnalysisErrorDetail(
                code="runtime_unavailable",
                message=str(exc),
            ),
        )
    except Exception as exc:
        _raise_api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            SiteSelectionAnalysisErrorDetail(
                code="analysis_internal_error",
                message="选址分析服务发生未处理异常",
                errors=[type(exc).__name__],
            ),
        )

    if state.status is AnalysisStatus.FAILED:
        _raise_api_error(
            status.HTTP_409_CONFLICT,
            SiteSelectionAnalysisErrorDetail(
                code="analysis_blocked",
                message="选址分析未能完成",
                request_id=state.request.request_id,
                errors=state.errors,
            ),
        )

    if state.status is not AnalysisStatus.COMPLETED:
        _raise_api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            SiteSelectionAnalysisErrorDetail(
                code="analysis_internal_error",
                message="选址分析服务返回了非终态结果",
                request_id=state.request.request_id,
                errors=[f"unexpected_status={state.status.value}"],
            ),
        )

    if (
        len(state.results) != len(state.request.candidate_parcels)
        or state.comparison_report is None
    ):
        _raise_api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            SiteSelectionAnalysisErrorDetail(
                code="analysis_internal_error",
                message="选址分析服务返回了不完整的完成状态",
                request_id=state.request.request_id,
                errors=["incomplete_completed_state"],
            ),
        )

    return SiteSelectionAnalysisResponse(
        request_id=state.request.request_id,
        requested_at=state.request.requested_at,
        project_type=state.request.project_type,
        status=state.status,
        results=state.results,
        comparison_report=state.comparison_report,
        errors=state.errors,
    )


def _raise_api_error(
    status_code: int,
    detail: SiteSelectionAnalysisErrorDetail,
) -> NoReturn:
    raise HTTPException(
        status_code=status_code,
        detail=detail.model_dump(mode="json"),
    )
