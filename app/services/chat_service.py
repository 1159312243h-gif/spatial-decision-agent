from app.schemas.chat import ChatRequest, ChatResponse


def answer_chat(request: ChatRequest) -> ChatResponse:
    return ChatResponse(
        answer=(
            f"已接收 {request.project_type} 项目的问题："
            f"{request.question}。"
            "当前为桩接口，尚未执行真实选址分析。"
        ),
        status="stub",
        received_candidates=len(request.candidate_parcels),
    )