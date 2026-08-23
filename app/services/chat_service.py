"""Compatibility facade for callers that used the original chat service module."""

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.site_selection_conversation import (
    SiteSelectionConversationService,
)


def answer_chat(
    request: ChatRequest,
    service: SiteSelectionConversationService,
) -> ChatResponse:
    reply = service.converse(
        request.question,
        session_id=request.session_id,
        project_type=request.project_type,
    )
    return ChatResponse.from_reply(
        reply,
        received_candidates=len(request.candidate_parcels),
    )
