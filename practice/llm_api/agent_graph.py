from __future__ import annotations

import json
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from openai import OpenAI
from pydantic import ValidationError

from .agent_state import (
    AgentState,
    ToolCallRecord,
    ToolResultRecord,
    create_initial_state,
)
from .client import get_required_env
from .tool_registry import ToolRegistry, ToolTimeoutError, create_default_registry


SYSTEM_MESSAGE = (
    "你是一个严谨的助手。需要四则运算时使用 calculator；"
    "需要确认当前日期时使用 current_date；"
    "需要查询示例项目类型时使用 project_type_profile。"
    "普通对话直接回答。工具失败时如实说明，不要编造结果。"
)

RouteName = Literal["tool", "final"]


def _safe_error_message(error: Exception) -> str:
    if isinstance(error, ValidationError):
        messages = []
        for item in error.errors():
            location = ".".join(str(part) for part in item["loc"]) or "input"
            messages.append(f"{location}: {item['msg']}")
        return "; ".join(messages)

    if isinstance(error, (ValueError, ToolTimeoutError)):
        return str(error)

    return "工具执行失败，请稍后重试"


def _returned_function_calls(response: Any) -> list[ToolCallRecord]:
    calls: list[ToolCallRecord] = []
    for item in response.output:
        if getattr(item, "type", None) != "function_call":
            continue
        calls.append(
            {
                "type": "function_call",
                "name": item.name,
                "arguments": item.arguments,
                "call_id": item.call_id,
            }
        )
    return calls


def input_node(state: AgentState) -> dict[str, Any]:
    """Mark a validated initial state as ready for model execution."""

    if not state["messages"]:
        return {
            "current_step": "done",
            "status": "failed",
            "error": "消息列表不能为空",
        }

    return {
        "current_step": "model",
        "error": None,
    }


def make_model_node(client: Any, model: str, registry: ToolRegistry):
    """Create a model node bound to one provider client and tool registry."""

    def model_node(state: AgentState) -> dict[str, Any]:
        try:
            response = client.responses.create(
                model=model,
                instructions=SYSTEM_MESSAGE,
                input=state["messages"],
                tools=registry.schemas(),
            )
        except Exception as exc:
            return {
                "current_step": "final",
                "pending_tool_calls": [],
                "status": "failed",
                "error": f"模型调用失败：{type(exc).__name__}",
            }

        function_calls = _returned_function_calls(response)
        if function_calls:
            return {
                "messages": function_calls,
                "current_step": "model",
                "pending_tool_calls": function_calls,
                "error": None,
            }

        answer = response.output_text.strip()
        if not answer:
            return {
                "current_step": "final",
                "pending_tool_calls": [],
                "status": "failed",
                "error": "模型既没有返回工具调用，也没有返回文本",
            }

        return {
            "messages": [{"role": "assistant", "content": answer}],
            "current_step": "final",
            "pending_tool_calls": [],
            "final_answer": answer,
            "error": None,
        }

    return model_node


def _execute_tool_call(
    registry: ToolRegistry,
    call: ToolCallRecord,
) -> tuple[dict[str, str], ToolResultRecord]:
    try:
        result = registry.execute(call["name"], call["arguments"])
        payload = {
            "ok": True,
            "status": "success",
            "result": result,
            "error": None,
            "error_type": None,
        }
    except (ValidationError, ValueError, ToolTimeoutError) as exc:
        payload = {
            "ok": False,
            "status": "error",
            "result": None,
            "error": _safe_error_message(exc),
            "error_type": type(exc).__name__,
        }
    except Exception as exc:
        payload = {
            "ok": False,
            "status": "error",
            "result": None,
            "error": _safe_error_message(exc),
            "error_type": type(exc).__name__,
        }

    output_message = {
        "type": "function_call_output",
        "call_id": call["call_id"],
        "output": json.dumps(payload, ensure_ascii=False, default=str),
    }
    result_record: ToolResultRecord = {
        "name": call["name"],
        "call_id": call["call_id"],
        "ok": bool(payload["ok"]),
        "output": payload["result"],
        "error": payload["error"],
    }
    return output_message, result_record


def make_tool_node(registry: ToolRegistry):
    """Create a node that delegates all tool validation and execution."""

    def tool_node(state: AgentState) -> dict[str, Any]:
        output_messages: list[dict[str, str]] = []
        result_records: list[ToolResultRecord] = []

        for call in state["pending_tool_calls"]:
            output_message, result_record = _execute_tool_call(registry, call)
            output_messages.append(output_message)
            result_records.append(result_record)

        return {
            "messages": output_messages,
            "current_step": "tool",
            "pending_tool_calls": [],
            "tool_results": result_records,
            "tool_call_count": (
                state["tool_call_count"] + len(state["pending_tool_calls"])
            ),
        }

    return tool_node


def route_after_model(state: AgentState) -> RouteName:
    """Choose a deterministic next node from the current state."""

    if state["status"] != "running":
        return "final"

    pending_count = len(state["pending_tool_calls"])
    if not pending_count:
        return "final"

    if state["tool_call_count"] + pending_count > state["max_tool_calls"]:
        return "final"

    return "tool"


def final_node(state: AgentState) -> dict[str, Any]:
    """Normalize completion, failure, and loop-limit terminal states."""

    updates: dict[str, Any] = {
        "current_step": "done",
        "pending_tool_calls": [],
    }

    if state["status"] != "running":
        return updates

    if state["final_answer"] is not None:
        updates["status"] = "completed"
        return updates

    if (
        state["pending_tool_calls"]
        and state["tool_call_count"] + len(state["pending_tool_calls"])
        > state["max_tool_calls"]
    ):
        updates.update(
            {
                "status": "limit_reached",
                "error": "工具调用次数达到上限",
            }
        )
        return updates

    updates.update(
        {
            "status": "failed",
            "error": state["error"] or "Agent 未生成最终回答",
        }
    )
    return updates


def build_agent_graph(
    client: Any,
    model: str,
    registry: ToolRegistry | None = None,
):
    """Compile the minimal State -> Model -> Tool/Final graph."""

    active_registry = registry or create_default_registry()
    builder = StateGraph(AgentState)
    builder.add_node("input", input_node)
    builder.add_node("model", make_model_node(client, model, active_registry))
    builder.add_node("tool", make_tool_node(active_registry))
    builder.add_node("final", final_node)

    builder.add_edge(START, "input")
    builder.add_edge("input", "model")
    builder.add_conditional_edges(
        "model",
        route_after_model,
        {
            "tool": "tool",
            "final": "final",
        },
    )
    builder.add_edge("tool", "model")
    builder.add_edge("final", END)
    return builder.compile()


def run_agent_graph(
    user_message: str,
    client: Any,
    model: str,
    registry: ToolRegistry | None = None,
    max_tool_calls: int = 3,
) -> AgentState:
    graph = build_agent_graph(client, model, registry)
    initial_state = create_initial_state(user_message, max_tool_calls)
    return graph.invoke(initial_state)


def main() -> None:
    client = OpenAI(
        api_key=get_required_env("LLM_API_KEY"),
        base_url=get_required_env("LLM_BASE_URL"),
        timeout=60.0,
    )
    result = run_agent_graph(
        "请查询今天的日期。",
        client=client,
        model=get_required_env("LLM_MODEL"),
    )
    print(result["final_answer"] or result["error"])


if __name__ == "__main__":
    main()
