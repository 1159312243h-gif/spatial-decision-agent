import json
from types import SimpleNamespace

from practice.llm_api.tool_calling import run_tool_calling


def text_response(response_id: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(id=response_id, output=[], output_text=text)


def tool_response(
    arguments: str,
    name: str = "calculator",
) -> SimpleNamespace:
    call = SimpleNamespace(
        type="function_call",
        name=name,
        arguments=arguments,
        call_id="call_001",
    )
    return SimpleNamespace(id="resp_001", output=[call], output_text="")


class FakeResponses:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = iter(responses)
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return next(self._responses)


def fake_client(*responses: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(responses=FakeResponses(list(responses)))


def test_calculation_runs_tool_and_returns_final_answer() -> None:
    client = fake_client(
        tool_response('{"operation":"multiply","a":18.5,"b":4}'),
        text_response("resp_002", "18.5 乘以 4 等于 74。"),
    )

    answer = run_tool_calling("请计算 18.5 乘以 4。", client, "test-model")

    assert answer == "18.5 乘以 4 等于 74。"
    assert len(client.responses.requests) == 2
    second_request = client.responses.requests[1]
    assert "previous_response_id" not in second_request
    assert second_request["input"][0] == {
        "role": "user",
        "content": "请计算 18.5 乘以 4。",
    }
    assert second_request["input"][1] == {
        "type": "function_call",
        "name": "calculator",
        "arguments": '{"operation":"multiply","a":18.5,"b":4}',
        "call_id": "call_001",
    }
    tool_result = second_request["input"][2]
    assert tool_result["type"] == "function_call_output"
    assert tool_result["call_id"] == "call_001"
    payload = json.loads(tool_result["output"])
    assert payload["ok"] is True
    assert payload["status"] == "success"
    assert payload["result"] == 74.0
    assert payload["error_type"] is None
    assert payload["elapsed_ms"] >= 0


def test_ordinary_chat_does_not_run_tool() -> None:
    client = fake_client(text_response("resp_001", "你好，我可以帮助你。"))

    answer = run_tool_calling("你好", client, "test-model")

    assert answer == "你好，我可以帮助你。"
    assert len(client.responses.requests) == 1


def test_missing_argument_returns_error_to_model() -> None:
    client = fake_client(
        tool_response('{"operation":"add","a":10}'),
        text_response("resp_002", "还缺少第二个数字，请提供 b。"),
    )

    answer = run_tool_calling("帮我把 10 加上另一个数。", client, "test-model")

    assert answer == "还缺少第二个数字，请提供 b。"
    tool_result = client.responses.requests[1]["input"][2]
    payload = json.loads(tool_result["output"])
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error_type"] == "ValidationError"
    assert payload["elapsed_ms"] >= 0
    assert "b" in payload["error"]
    assert "input_value" not in payload["error"]


def test_unknown_tool_returns_safe_error_record() -> None:
    client = fake_client(
        tool_response(
            '{"operation":"add","a":1,"b":2}',
            name="python",
        ),
        text_response("resp_002", "请求的工具不可用。"),
    )

    answer = run_tool_calling("请调用 python 工具。", client, "test-model")

    assert answer == "请求的工具不可用。"
    tool_result = client.responses.requests[1]["input"][2]
    payload = json.loads(tool_result["output"])
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error_type"] == "ValueError"
    assert payload["error"] == "未注册的工具：python"
    assert payload["elapsed_ms"] >= 0


def test_blank_message_is_rejected_before_api_call() -> None:
    client = fake_client()

    try:
        run_tool_calling("   ", client, "test-model")
    except ValueError as exc:
        assert str(exc) == "用户消息不能为空"
    else:
        raise AssertionError("空消息应被拒绝")

    assert client.responses.requests == []
