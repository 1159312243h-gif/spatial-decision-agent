import json
from time import perf_counter
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from .calculator import CALCULATOR_TOOL, execute_tool
from .client import get_required_env


SYSTEM_MESSAGE = (
    "你是一个严谨的助手。需要进行四则运算时使用 calculator 工具；"
    "普通对话直接回答。工具失败时如实说明原因，不要编造结果。"
)


def _function_calls(response: Any) -> list[Any]:
    return [
        item
        for item in response.output
        if getattr(item, "type", None) == "function_call"
    ]


def _safe_error_message(error: ValidationError | ValueError) -> str:
    """Summarize an error without copying complete input values into records."""

    if isinstance(error, ValidationError):
        messages = []
        for item in error.errors():
            location = ".".join(str(part) for part in item["loc"]) or "input"
            messages.append(f"{location}: {item['msg']}")
        return "; ".join(messages)

    return str(error)


def _tool_output(function_call: Any) -> dict[str, str]:
    started_at = perf_counter()

    try:
        result = execute_tool(function_call.name, function_call.arguments)
        payload = {
            "ok": True,
            "status": "success",
            "result": result,
            "error_type": None,
        }
    except (ValidationError, ValueError) as exc:
        payload = {
            "ok": False,
            "status": "error",
            "error": _safe_error_message(exc),
            "error_type": type(exc).__name__,
        }

    payload["elapsed_ms"] = round((perf_counter() - started_at) * 1000, 3)

    return {
        "type": "function_call_output",
        "call_id": function_call.call_id,
        "output": json.dumps(payload, ensure_ascii=False),
    }


def _function_call_input(function_call: Any) -> dict[str, str]:
    """Convert a returned function call into a reusable input item."""

    return {
        "type": "function_call",
        "name": function_call.name,
        "arguments": function_call.arguments,
        "call_id": function_call.call_id,
    }


def run_tool_calling(
    user_message: str,
    client: Any,
    model: str,
    max_tool_rounds: int = 3,
) -> str:
    """Run a Responses API function-calling loop with a bounded tool depth."""

    if not user_message.strip():
        raise ValueError("用户消息不能为空")

    conversation_input: list[dict[str, Any]] = [
        {"role": "user", "content": user_message},
    ]
    response = client.responses.create(
        model=model,
        instructions=SYSTEM_MESSAGE,
        input=conversation_input,
        tools=[CALCULATOR_TOOL],
    )

    for _ in range(max_tool_rounds + 1):
        function_calls = _function_calls(response)

        if not function_calls:
            answer = response.output_text.strip()
            if not answer:
                raise RuntimeError("模型既没有返回工具调用，也没有返回文本")
            return answer

        conversation_input.extend(
            _function_call_input(call) for call in function_calls
        )
        conversation_input.extend(_tool_output(call) for call in function_calls)
        response = client.responses.create(
            model=model,
            instructions=SYSTEM_MESSAGE,
            input=conversation_input,
            tools=[CALCULATOR_TOOL],
        )

    raise RuntimeError("工具调用轮数超过限制")


def main() -> None:
    client = OpenAI(
        api_key=get_required_env("LLM_API_KEY"),
        base_url=get_required_env("LLM_BASE_URL"),
        timeout=60.0,
    )
    answer = run_tool_calling(
        "请计算 18.5 乘以 4。",
        client=client,
        model=get_required_env("LLM_MODEL"),
    )
    print(answer)


if __name__ == "__main__":
    main()
