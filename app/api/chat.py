from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status

from app.schemas.chat import (
    ChatConfirmRequest,
    ChatRequest,
    ChatResponse,
    ChatSessionResponse,
)
from app.services.site_selection_conversation import (
    ScenarioConfirmationBlockedError,
    ScenarioConversationNotFoundError,
    ScenarioVersionConflictError,
    SiteSelectionConversationService,
)


router = APIRouter(tags=["chat"])
SessionIdPath = Annotated[
    str,
    Path(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._-]+$"),
]


def get_conversation_service(request: Request) -> SiteSelectionConversationService:
    return request.app.state.site_selection_conversation_service


@router.post("/chat", response_model=ChatResponse)
def create_chat(
    command: ChatRequest,
    service: Annotated[
        SiteSelectionConversationService,
        Depends(get_conversation_service),
    ],
) -> ChatResponse:
    try:
        reply = service.converse(
            command.question,
            session_id=command.session_id,
            project_type=command.project_type,
        )
        return ChatResponse.from_reply(
            reply,
            received_candidates=len(command.candidate_parcels),
        )
    except ScenarioConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/chat/{session_id}", response_model=ChatSessionResponse)
def get_chat(
    session_id: SessionIdPath,
    service: Annotated[
        SiteSelectionConversationService,
        Depends(get_conversation_service),
    ],
) -> ChatSessionResponse:
    try:
        return service.get_session(session_id)
    except ScenarioConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/chat/{session_id}/confirm", response_model=ChatResponse)
def confirm_chat_scenario(
    session_id: SessionIdPath,
    command: ChatConfirmRequest,
    service: Annotated[
        SiteSelectionConversationService,
        Depends(get_conversation_service),
    ],
) -> ChatResponse:
    try:
        return ChatResponse.from_reply(
            service.confirm(
                session_id,
                command.version_id,
                confirmed_by=command.confirmed_by,
            )
        )
    except ScenarioConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (ScenarioVersionConflictError, ScenarioConfirmationBlockedError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
