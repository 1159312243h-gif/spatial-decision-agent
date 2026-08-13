from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CalculatorArguments(BaseModel):
    """Validated arguments accepted by the calculator tool."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["add", "subtract", "multiply", "divide"] = Field(
        description="要执行的运算：加、减、乘、除",
    )
    a: float = Field(description="第一个操作数")
    b: float = Field(description="第二个操作数")


CALCULATOR_TOOL = {
    "type": "function",
    "name": "calculator",
    "description": "对两个数字执行加、减、乘、除运算。",
    "parameters": CalculatorArguments.model_json_schema(),
    "strict": True,
}


def calculator(operation: str, a: float, b: float) -> float:
    """Execute one allowed arithmetic operation without using eval()."""

    operations: dict[str, Callable[[float, float], float]] = {
        "add": lambda left, right: left + right,
        "subtract": lambda left, right: left - right,
        "multiply": lambda left, right: left * right,
        "divide": lambda left, right: left / right,
    }

    if operation not in operations:
        raise ValueError(f"不支持的运算：{operation}")

    if operation == "divide" and b == 0:
        raise ValueError("除数不能为 0")

    return operations[operation](a, b)


def execute_tool(tool_name: str, arguments: str | dict[str, Any]) -> float:
    """Validate a tool request and execute only a registered tool."""

    if tool_name != CALCULATOR_TOOL["name"]:
        raise ValueError(f"未注册的工具：{tool_name}")

    if isinstance(arguments, str):
        validated = CalculatorArguments.model_validate_json(arguments)
    else:
        validated = CalculatorArguments.model_validate(arguments)

    return calculator(**validated.model_dump())
