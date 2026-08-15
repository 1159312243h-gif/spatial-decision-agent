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


def test_request_exposes_all_three_registered_tools() -> None:
    client = fake_client(text_response("resp_001", "你好。"))

    run_tool_calling("你好", client, "test-model")

    names = {tool["name"] for tool in client.responses.requests[0]["tools"]}
    assert names == {"calculator", "current_date", "project_type_profile"}


def test_project_type_tool_result_is_returned_to_model() -> None:
    client = fake_client(
        tool_response(
            '{"project_type":"logistics_park"}',
            name="project_type_profile",
        ),
        text_response("resp_002", "系统支持物流园项目类型。"),
    )

    answer = run_tool_calling("是否支持物流园？", client, "test-model")

    assert answer == "系统支持物流园项目类型。"
    tool_result = client.responses.requests[1]["input"][2]
    payload = json.loads(tool_result["output"])
    assert payload["ok"] is True
    assert payload["result"]["project_type"] == "logistics_park"
