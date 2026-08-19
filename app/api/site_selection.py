from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, status

from app.schemas.site_selection import (
    SiteSelectionAnalysisCreate,
    SiteSelectionAnalysisErrorDetail,
    SiteSelectionAnalysisErrorResponse,
    SiteSelectionAnalysisResponse,
    SiteSelectionPreflightRequest,
    SiteSelectionPreflightResponse,
    SiteSelectionPOIPreviewRequest,
    SiteSelectionPOIPreviewResponse,
    SiteSelectionRunEventsResponse,
    SiteSelectionRunResponse,
)
from app.services.site_selection_service import (
    SiteSelectionAnalysisService,
    SiteSelectionRuntimeUnavailableError,
)
from app.services.site_selection_run_service import (
    SiteSelectionRunNotFoundError,
    SiteSelectionRunServiceProtocol,
    SiteSelectionRunServiceUnavailableError,
    SiteSelectionRunStateInconsistentError,
)
from practice.site_selection import (
    AnalysisStatus,
    OrchestratorAgent,
    OrchestratorAgentInput,
)
from practice.site_selection.storage import IdempotencyConflictError


router = APIRouter(prefix="/site-selection", tags=["site-selection"])
RunIdPath = Annotated[
    str,
    Path(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._-]+$"),
]


def get_site_selection_analysis_service(
    request: Request,
) -> SiteSelectionAnalysisService:
    return request.app.state.site_selection_analysis_service


def get_site_selection_run_service(
    request: Request,
) -> SiteSelectionRunServiceProtocol:
    return request.app.state.site_selection_run_service


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
        evidence_review_report=state.evidence_review_report,
        errors=state.errors,
    )


@router.post(
    "/runs",
    response_model=SiteSelectionRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_site_selection_run(
    command: SiteSelectionAnalysisCreate,
    service: Annotated[
        SiteSelectionRunServiceProtocol,
        Depends(get_site_selection_run_service),
    ],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=200,
            pattern=r"^\S(?:.*\S)?$",
        ),
    ] = None,
) -> SiteSelectionRunResponse:
    try:
        state = service.create_run(
            command,
            idempotency_key=idempotency_key,
        )
    except (SiteSelectionRunServiceUnavailableError, SiteSelectionRuntimeUnavailableError) as exc:
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            SiteSelectionAnalysisErrorDetail(
                code="runtime_unavailable",
                message=str(exc),
            ),
        )
    except SiteSelectionRunStateInconsistentError:
        _raise_api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            SiteSelectionAnalysisErrorDetail(
                code="analysis_internal_error",
                message="选址运行状态不一致",
                errors=["SiteSelectionRunStateInconsistentError"],
            ),
        )
    except IdempotencyConflictError as exc:
        _raise_api_error(
            status.HTTP_409_CONFLICT,
            SiteSelectionAnalysisErrorDetail(
                code="idempotency_conflict",
                message=str(exc),
            ),
        )
    except Exception as exc:
        _raise_api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            SiteSelectionAnalysisErrorDetail(
                code="analysis_internal_error",
                message="创建选址运行时发生未处理异常",
                errors=[type(exc).__name__],
            ),
        )
    return SiteSelectionRunResponse.from_state(state)


@router.get(
    "/runs/{run_id}",
    response_model=SiteSelectionRunResponse,
)
def get_site_selection_run(
    run_id: RunIdPath,
    service: Annotated[
        SiteSelectionRunServiceProtocol,
        Depends(get_site_selection_run_service),
    ],
) -> SiteSelectionRunResponse:
    try:
        return SiteSelectionRunResponse.from_state(service.get_run(run_id))
    except SiteSelectionRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except SiteSelectionRunServiceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )


@router.get(
    "/runs/{run_id}/events",
    response_model=SiteSelectionRunEventsResponse,
)
def get_site_selection_run_events(
    run_id: RunIdPath,
    service: Annotated[
        SiteSelectionRunServiceProtocol,
        Depends(get_site_selection_run_service),
    ],
) -> SiteSelectionRunEventsResponse:
    try:
        events = service.get_events(run_id)
    except SiteSelectionRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except SiteSelectionRunServiceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    return SiteSelectionRunEventsResponse(run_id=run_id, events=events)


@router.post(
    "/poi/preview",
    response_model=SiteSelectionPOIPreviewResponse,
)
def preview_site_selection_poi(
    command: SiteSelectionPOIPreviewRequest,
    service: Annotated[
        SiteSelectionRunServiceProtocol,
        Depends(get_site_selection_run_service),
    ],
) -> SiteSelectionPOIPreviewResponse:
    try:
        result = service.preview_poi(command)
    except (SiteSelectionRunServiceUnavailableError, SiteSelectionRuntimeUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    except Exception as exc:
        _raise_api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            SiteSelectionAnalysisErrorDetail(
                code="analysis_internal_error",
                message="POI 预览发生未处理异常",
                errors=[type(exc).__name__],
            ),
        )
    return SiteSelectionPOIPreviewResponse(
        cached=result.cached,
        feature_set=result.feature_set,
    )


def _raise_api_error(
    status_code: int,
    detail: SiteSelectionAnalysisErrorDetail,
) -> NoReturn:
    raise HTTPException(
        status_code=status_code,
        detail=detail.model_dump(mode="json"),
    )
