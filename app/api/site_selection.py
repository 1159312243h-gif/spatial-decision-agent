from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Request,
    Response,
    status,
)
from fastapi.responses import FileResponse

from app.schemas.site_selection import (
    HumanReviewAcknowledgeRequest,
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
    SiteSelectionSupervisorConfirmRequest,
    SiteSelectionSupervisorEventsResponse,
    SiteSelectionSupervisorResponse,
)
from app.services.site_selection_service import (
    SiteSelectionAnalysisService,
    SiteSelectionRuntimeUnavailableError,
)
from app.services.site_selection_run_service import (
    SiteSelectionRunConflictError,
    SiteSelectionRunNotFoundError,
    SiteSelectionRunServiceProtocol,
    SiteSelectionRunServiceUnavailableError,
    SiteSelectionRunStateInconsistentError,
)
from app.services.site_selection_artifacts import SiteSelectionReportNotFoundError
from app.services.site_selection_supervisor import (
    SiteSelectionSupervisorServiceProtocol,
    SiteSelectionSupervisorServiceUnavailableError,
)
from practice.site_selection import (
    AnalysisStatus,
    CandidateDiscoveryBlockedError,
    CandidateDiscoveryReport,
    CandidateDiscoveryRequest,
    CandidateDiscoveryService,
    CandidateDiscoverySnapshotError,
    CandidateConfirmationBlockedError,
    OrchestratorAgent,
    OrchestratorAgentInput,
    SupervisorAnalysisBlockedError,
    SupervisorSessionConflictError,
    SupervisorSessionNotFoundError,
    SupervisorStatus,
)
from practice.site_selection.storage import (
    IdempotencyConflictError,
    RunStatus,
)


router = APIRouter(prefix="/site-selection", tags=["site-selection"])
RunIdPath = Annotated[
    str,
    Path(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._-]+$"),
]
SupervisorSessionIdPath = Annotated[
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


def get_candidate_discovery_service(
    request: Request,
) -> CandidateDiscoveryService:
    return request.app.state.site_selection_candidate_discovery_service


def get_site_selection_supervisor_service(
    request: Request,
) -> SiteSelectionSupervisorServiceProtocol:
    return request.app.state.site_selection_supervisor_service


@router.post(
    "/supervisor/sessions",
    response_model=SiteSelectionSupervisorResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_site_selection_supervisor_session(
    command: CandidateDiscoveryRequest,
    service: Annotated[
        SiteSelectionSupervisorServiceProtocol,
        Depends(get_site_selection_supervisor_service),
    ],
) -> SiteSelectionSupervisorResponse:
    try:
        run = service.start(command)
        return SiteSelectionSupervisorResponse.from_run(
            run,
            session_ttl_seconds=service.ttl(run.session_id),
        )
    except (
        SiteSelectionSupervisorServiceUnavailableError,
        SiteSelectionRuntimeUnavailableError,
    ) as exc:
        _raise_supervisor_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "supervisor_unavailable",
            str(exc),
            request_id=command.request_id,
        )
    except CandidateDiscoveryBlockedError as exc:
        _raise_supervisor_error(
            status.HTTP_409_CONFLICT,
            "supervisor_confirmation_blocked",
            str(exc),
            request_id=command.request_id,
        )
    except Exception as exc:
        _raise_supervisor_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "supervisor_internal_error",
            "创建 Supervisor session 时发生未处理异常",
            request_id=command.request_id,
            errors=[type(exc).__name__],
        )


@router.get(
    "/supervisor/sessions/{session_id}",
    response_model=SiteSelectionSupervisorResponse,
)
def get_site_selection_supervisor_session(
    session_id: SupervisorSessionIdPath,
    service: Annotated[
        SiteSelectionSupervisorServiceProtocol,
        Depends(get_site_selection_supervisor_service),
    ],
) -> SiteSelectionSupervisorResponse:
    try:
        return SiteSelectionSupervisorResponse.from_run(
            service.get(session_id),
            session_ttl_seconds=service.ttl(session_id),
        )
    except SupervisorSessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supervisor session 不存在或已过期",
        )
    except SiteSelectionSupervisorServiceUnavailableError as exc:
        _raise_supervisor_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "supervisor_unavailable",
            str(exc),
        )
    except Exception as exc:
        _raise_supervisor_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "supervisor_internal_error",
            "读取 Supervisor session 时发生未处理异常",
            errors=[type(exc).__name__],
        )


@router.post(
    "/supervisor/sessions/{session_id}/confirm",
    response_model=SiteSelectionSupervisorResponse,
)
def confirm_site_selection_supervisor_session(
    session_id: SupervisorSessionIdPath,
    command: SiteSelectionSupervisorConfirmRequest,
    response: Response,
    service: Annotated[
        SiteSelectionSupervisorServiceProtocol,
        Depends(get_site_selection_supervisor_service),
    ],
) -> SiteSelectionSupervisorResponse:
    try:
        run = service.confirm(
            session_id,
            command.to_domain(),
            expected_checkpoint_id=command.expected_checkpoint_id,
        )
        if run.status is SupervisorStatus.AWAITING_ANALYSIS:
            response.status_code = status.HTTP_202_ACCEPTED
        return SiteSelectionSupervisorResponse.from_run(
            run,
            session_ttl_seconds=service.ttl(session_id),
        )
    except SupervisorSessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supervisor session 不存在或已过期",
        )
    except (
        CandidateConfirmationBlockedError,
        CandidateDiscoverySnapshotError,
        SupervisorAnalysisBlockedError,
    ) as exc:
        _raise_supervisor_error(
            status.HTTP_409_CONFLICT,
            "supervisor_confirmation_blocked",
            str(exc),
        )
    except SupervisorSessionConflictError as exc:
        _raise_supervisor_error(
            status.HTTP_409_CONFLICT,
            "supervisor_conflict",
            str(exc),
        )
    except (
        SiteSelectionSupervisorServiceUnavailableError,
        SiteSelectionRuntimeUnavailableError,
    ) as exc:
        _raise_supervisor_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "supervisor_unavailable",
            str(exc),
        )
    except Exception as exc:
        _raise_supervisor_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "supervisor_internal_error",
            "确认 Supervisor session 时发生未处理异常",
            errors=[type(exc).__name__],
        )


@router.get(
    "/supervisor/sessions/{session_id}/events",
    response_model=SiteSelectionSupervisorEventsResponse,
)
def get_site_selection_supervisor_events(
    session_id: SupervisorSessionIdPath,
    service: Annotated[
        SiteSelectionSupervisorServiceProtocol,
        Depends(get_site_selection_supervisor_service),
    ],
) -> SiteSelectionSupervisorEventsResponse:
    try:
        return SiteSelectionSupervisorEventsResponse(
            session_id=session_id,
            events=service.list_events(session_id),
        )
    except SupervisorSessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supervisor session 不存在或已过期",
        )
    except SiteSelectionSupervisorServiceUnavailableError as exc:
        _raise_supervisor_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "supervisor_unavailable",
            str(exc),
        )
    except Exception as exc:
        _raise_supervisor_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "supervisor_internal_error",
            "读取 Supervisor 审计事件时发生未处理异常",
            errors=[type(exc).__name__],
        )


@router.post(
    "/candidates/discover",
    response_model=CandidateDiscoveryReport,
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "用地或市场证据不足，候选发现被阻断"
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "候选发现运行时尚未配置"
        },
    },
)
def discover_site_selection_candidates(
    command: CandidateDiscoveryRequest,
    service: Annotated[
        CandidateDiscoveryService,
        Depends(get_candidate_discovery_service),
    ],
) -> CandidateDiscoveryReport:
    try:
        return service.discover(command)
    except SiteSelectionRuntimeUnavailableError as exc:
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            SiteSelectionAnalysisErrorDetail(
                code="runtime_unavailable",
                message=str(exc),
                request_id=command.request_id,
            ),
        )
    except CandidateDiscoveryBlockedError as exc:
        _raise_api_error(
            status.HTTP_409_CONFLICT,
            SiteSelectionAnalysisErrorDetail(
                code="candidate_discovery_blocked",
                message=str(exc),
                request_id=command.request_id,
            ),
        )
    except Exception as exc:
        _raise_api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            SiteSelectionAnalysisErrorDetail(
                code="candidate_discovery_internal_error",
                message="候选自动发现发生未处理异常",
                request_id=command.request_id,
                errors=[type(exc).__name__],
            ),
        )


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
    except CandidateDiscoverySnapshotError as exc:
        _raise_api_error(
            status.HTTP_409_CONFLICT,
            SiteSelectionAnalysisErrorDetail(
                code="analysis_blocked",
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
        analysis_scope=state.request.analysis_scope,
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
    response: Response,
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
    except CandidateDiscoverySnapshotError as exc:
        _raise_api_error(
            status.HTTP_409_CONFLICT,
            SiteSelectionAnalysisErrorDetail(
                code="analysis_blocked",
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
    if state.status in {RunStatus.QUEUED, RunStatus.RUNNING}:
        response.status_code = status.HTTP_202_ACCEPTED
    return SiteSelectionRunResponse.from_state(state)


@router.post(
    "/runs/{run_id}/cancel",
    response_model=SiteSelectionRunResponse,
)
def cancel_site_selection_run(
    run_id: RunIdPath,
    service: Annotated[
        SiteSelectionRunServiceProtocol,
        Depends(get_site_selection_run_service),
    ],
) -> SiteSelectionRunResponse:
    try:
        state = service.cancel_run(run_id)
    except SiteSelectionRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except SiteSelectionRunConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except SiteSelectionRunServiceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
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


@router.post(
    "/runs/{run_id}/human-review/acknowledge",
    response_model=SiteSelectionRunResponse,
)
def acknowledge_site_selection_human_review(
    run_id: RunIdPath,
    command: HumanReviewAcknowledgeRequest,
    service: Annotated[
        SiteSelectionRunServiceProtocol,
        Depends(get_site_selection_run_service),
    ],
) -> SiteSelectionRunResponse:
    try:
        state = service.acknowledge_human_review(
            run_id,
            note=command.note,
        )
    except SiteSelectionRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (SiteSelectionRunStateInconsistentError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except SiteSelectionRunServiceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    return SiteSelectionRunResponse.from_state(state)


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


@router.get(
    "/runs/{run_id}/report",
    response_class=FileResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "运行或报告不存在"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "运行服务尚未配置"
        },
    },
)
def download_site_selection_run_report(
    run_id: RunIdPath,
    service: Annotated[
        SiteSelectionRunServiceProtocol,
        Depends(get_site_selection_run_service),
    ],
) -> FileResponse:
    try:
        path = service.get_report_path(run_id)
    except (SiteSelectionRunNotFoundError, SiteSelectionReportNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except SiteSelectionRunServiceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    return FileResponse(
        path,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        filename=f"site-selection-{run_id}.docx",
    )


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


def _raise_supervisor_error(
    status_code: int,
    code: str,
    message: str,
    *,
    request_id: str | None = None,
    errors: list[str] | None = None,
) -> NoReturn:
    _raise_api_error(
        status_code,
        SiteSelectionAnalysisErrorDetail(
            code=code,
            message=message,
            request_id=request_id,
            errors=errors or [],
        ),
    )
