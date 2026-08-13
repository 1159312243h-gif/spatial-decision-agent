import pytest
from pydantic import ValidationError

from practice.llm_api.calculator import execute_tool


def test_multiply_success() -> None:
    assert execute_tool(
        "calculator",
        {"operation": "multiply", "a": 6, "b": 7},
    ) == 42


def test_missing_argument_is_rejected() -> None:
    with pytest.raises(ValidationError):
        execute_tool("calculator", {"operation": "add", "a": 1})


def test_invalid_operation_is_rejected() -> None:
    with pytest.raises(ValidationError):
        execute_tool(
            "calculator",
            {"operation": "power", "a": 2, "b": 3},
        )


def test_division_by_zero_is_rejected() -> None:
    with pytest.raises(ValueError, match="除数不能为 0"):
        execute_tool(
            "calculator",
            {"operation": "divide", "a": 10, "b": 0},
        )


def test_extra_argument_is_rejected() -> None:
    with pytest.raises(ValidationError):
        execute_tool(
            "calculator",
            {"operation": "add", "a": 1, "b": 2, "unit": "元"},
        )


def test_unregistered_tool_is_rejected() -> None:
    with pytest.raises(ValueError, match="未注册的工具"):
        execute_tool("python", {"operation": "add", "a": 1, "b": 2})
