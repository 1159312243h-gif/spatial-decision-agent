from fastapi import APIRouter

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import answer_chat


router = APIRouter(tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
)
def create_chat(request: ChatRequest) -> ChatResponse:
    return answer_chat(request)