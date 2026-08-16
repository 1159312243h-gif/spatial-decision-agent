import pytest

from practice.llm_api.agent_state import create_initial_state


def test_initial_state_contains_all_required_fields() -> None:
    state = create_initial_state("请计算 6 乘以 7")

    assert state == {
        "messages": [{"role": "user", "content": "请计算 6 乘以 7"}],
        "current_step": "input",
        "pending_tool_calls": [],
        "tool_results": [],
        "error": None,
        "tool_call_count": 0,
        "max_tool_calls": 3,
        "status": "running",
        "final_answer": None,
    }


def test_user_message_is_trimmed() -> None:
    state = create_initial_state("  你好  ")

    assert state["messages"] == [{"role": "user", "content": "你好"}]


def test_custom_tool_call_limit_is_stored() -> None:
    state = create_initial_state("查询日期", max_tool_calls=5)

    assert state["max_tool_calls"] == 5


@pytest.mark.parametrize("message", ["", "   ", "\n\t"])
def test_blank_user_message_is_rejected(message: str) -> None:
    with pytest.raises(ValueError, match="用户消息不能为空"):
        create_initial_state(message)


@pytest.mark.parametrize("limit", [0, -1, True])
def test_invalid_tool_call_limit_is_rejected(limit: int) -> None:
    with pytest.raises(ValueError, match="最大工具调用次数必须是正整数"):
        create_initial_state("你好", max_tool_calls=limit)


def test_each_state_has_independent_mutable_lists() -> None:
    first = create_initial_state("问题一")
    second = create_initial_state("问题二")

    first["messages"].append({"role": "assistant", "content": "回答一"})
    first["tool_results"].append(
        {
            "name": "calculator",
            "call_id": "call_001",
            "ok": True,
            "output": 42,
            "error": None,
        }
    )

    assert second["messages"] == [{"role": "user", "content": "问题二"}]
    assert second["tool_results"] == []
