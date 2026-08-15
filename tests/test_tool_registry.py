from datetime import date
from time import sleep

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from practice.llm_api.tool_registry import (
    CALCULATOR_DEFINITION,
    ToolDefinition,
    ToolRegistry,
    ToolTimeoutError,
    create_default_registry,
)


def test_default_registry_contains_three_tools() -> None:
    registry = create_default_registry()

    assert registry.names == (
        "calculator",
        "current_date",
        "project_type_profile",
    )
    assert {schema["name"] for schema in registry.schemas()} == set(
        registry.names
    )


def test_calculator_uses_unified_execute_interface() -> None:
    registry = create_default_registry()

    result = registry.execute(
        "calculator",
        {"operation": "multiply", "a": 6, "b": 7},
    )

    assert result == 42


def test_current_date_uses_requested_timezone() -> None:
    registry = create_default_registry()

    result = registry.execute("current_date", {"timezone": "Asia/Shanghai"})

    date.fromisoformat(result["date"])
    assert result["timezone"] == "Asia/Shanghai"


def test_project_type_profile_returns_supported_profile() -> None:
    registry = create_default_registry()

    result = registry.execute(
        "project_type_profile",
        {"project_type": "logistics_park"},
    )

    assert result["project_type"] == "logistics_park"
    assert result["display_name"] == "物流园"
    assert result["supported"] is True
    assert result["review_focus"]


def test_invalid_project_type_is_rejected_before_execution() -> None:
    registry = create_default_registry()

    with pytest.raises(ValidationError):
        registry.execute(
            "project_type_profile",
            {"project_type": "hospital"},
        )


def test_unknown_tool_is_rejected() -> None:
    registry = create_default_registry()

    with pytest.raises(ValueError, match="未注册的工具：python"):
        registry.execute("python", {})


def test_duplicate_tool_registration_is_rejected() -> None:
    registry = ToolRegistry([CALCULATOR_DEFINITION])

    with pytest.raises(ValueError, match="工具已注册：calculator"):
        registry.register(CALCULATOR_DEFINITION)


def test_tool_timeout_is_mapped_to_explicit_error() -> None:
    class EmptyArguments(BaseModel):
        model_config = ConfigDict(extra="forbid")

    def slow_tool() -> str:
        sleep(0.05)
        return "late"

    registry = ToolRegistry(
        [
            ToolDefinition(
                name="slow_tool",
                description="测试超时处理。",
                arguments_model=EmptyArguments,
                handler=slow_tool,
                timeout_seconds=0.001,
            )
        ]
    )

    with pytest.raises(ToolTimeoutError, match="工具 slow_tool 执行超时"):
        registry.execute("slow_tool", {})
