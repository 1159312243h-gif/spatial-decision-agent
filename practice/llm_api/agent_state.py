from __future__ import annotations

from operator import add
from typing import Annotated, Any, Literal, TypedDict


AgentStep = Literal["input", "model", "tool", "final", "done"]
AgentStatus = Literal["running", "completed", "failed", "limit_reached"]


class ToolCallRecord(TypedDict):
    """One tool request produced by the model and waiting for execution."""

    type: Literal["function_call"]
    name: str
    arguments: str | dict[str, Any]
    call_id: str


class ToolResultRecord(TypedDict):
    """One normalized tool result stored in graph state."""

    name: str
    call_id: str
    ok: bool
    output: Any
    error: str | None


class AgentState(TypedDict):
    """Shared state contract for the minimal LangGraph tool-calling graph."""

    # Nodes return only newly created items; the reducer appends them.
    messages: Annotated[list[dict[str, Any]], add]
    current_step: AgentStep
    pending_tool_calls: list[ToolCallRecord]
    tool_results: Annotated[list[ToolResultRecord], add]
    error: str | None
    tool_call_count: int
    max_tool_calls: int
    status: AgentStatus
    final_answer: str | None


def create_initial_state(
    user_message: str,
    max_tool_calls: int = 3,
) -> AgentState:
    """Create a complete and independent state for one graph invocation."""

    normalized_message = user_message.strip()
    if not normalized_message:
        raise ValueError("用户消息不能为空")

    if isinstance(max_tool_calls, bool) or max_tool_calls <= 0:
        raise ValueError("最大工具调用次数必须是正整数")

    return AgentState(
        messages=[{"role": "user", "content": normalized_message}],
        current_step="input",
        pending_tool_calls=[],
        tool_results=[],
        error=None,
        tool_call_count=0,
        max_tool_calls=max_tool_calls,
        status="running",
        final_answer=None,
    )
