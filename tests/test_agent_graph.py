import json
from types import SimpleNamespace

from practice.llm_api.agent_graph import run_agent_graph


def text_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(output=[], output_text=text)


def tool_response(
    arguments: str,
    name: str = "calculator",
    call_id: str = "call_001",
) -> SimpleNamespace:
    call = SimpleNamespace(
        type="function_call",
        name=name,
        arguments=arguments,
        call_id=call_id,
    )
    return SimpleNamespace(output=[call], output_text="")


class FakeResponses:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = iter(responses)
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return next(self._responses)


def fake_client(*responses: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(responses=FakeResponses(list(responses)))


def tool_payload(client: SimpleNamespace, request_index: int = 1) -> dict:
    messages = client.responses.requests[request_index]["input"]
    output_message = next(
        message
        for message in messages
        if message.get("type") == "function_call_output"
    )
    return json.loads(output_message["output"])


def test_ordinary_chat_routes_directly_to_final() -> None:
    client = fake_client(text_response("你好，我可以帮助你。"))

    result = run_agent_graph("你好", client, "test-model")

    assert result["status"] == "completed"
    assert result["current_step"] == "done"
    assert result["final_answer"] == "你好，我可以帮助你。"
    assert result["tool_call_count"] == 0
    assert result["tool_results"] == []
    assert len(client.responses.requests) == 1


def test_correct_tool_call_uses_existing_registry() -> None:
    client = fake_client(
        tool_response('{"operation":"multiply","a":6,"b":7}'),
        text_response("6 乘以 7 等于 42。"),
    )

    result = run_agent_graph("请计算 6 乘以 7", client, "test-model")

    assert result["status"] == "completed"
    assert result["final_answer"] == "6 乘以 7 等于 42。"
    assert result["tool_call_count"] == 1
    assert result["tool_results"] == [
        {
            "name": "calculator",
            "call_id": "call_001",
            "ok": True,
            "output": 42.0,
            "error": None,
        }
    ]
    assert tool_payload(client)["result"] == 42.0


def test_unknown_tool_is_recorded_without_execution() -> None:
    client = fake_client(
        tool_response("{}", name="python"),
        text_response("请求的工具不可用。"),
    )

    result = run_agent_graph("请调用 python", client, "test-model")

    assert result["status"] == "completed"
    assert result["tool_call_count"] == 1
    assert result["tool_results"][0]["ok"] is False
    assert result["tool_results"][0]["error"] == "未注册的工具：python"
    payload = tool_payload(client)
    assert payload["error_type"] == "ValueError"


def test_invalid_arguments_are_recorded_safely() -> None:
    client = fake_client(
        tool_response('{"operation":"add","a":10}'),
        text_response("还缺少第二个数字。"),
    )

    result = run_agent_graph("帮我加两个数字", client, "test-model")

    assert result["status"] == "completed"
    assert result["tool_results"][0]["ok"] is False
    assert "b" in result["tool_results"][0]["error"]
    payload = tool_payload(client)
    assert payload["error_type"] == "ValidationError"
    assert "input_value" not in payload["error"]


def test_tool_loop_stops_before_exceeding_limit() -> None:
    client = fake_client(
        tool_response('{"operation":"add","a":1,"b":1}', call_id="call_1"),
        tool_response('{"operation":"add","a":2,"b":2}', call_id="call_2"),
    )

    result = run_agent_graph(
        "请不断计算",
        client,
        "test-model",
        max_tool_calls=1,
    )

    assert result["status"] == "limit_reached"
    assert result["current_step"] == "done"
    assert result["error"] == "工具调用次数达到上限"
    assert result["tool_call_count"] == 1
    assert len(result["tool_results"]) == 1
    assert result["pending_tool_calls"] == []
    assert len(client.responses.requests) == 2
