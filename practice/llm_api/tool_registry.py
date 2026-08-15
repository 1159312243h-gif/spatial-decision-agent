from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as datetime_timezone
from typing import Any, Callable, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

from .calculator import CalculatorArguments, calculator


class ToolTimeoutError(TimeoutError):
    """Raised when one registered tool exceeds its execution deadline."""


@dataclass(frozen=True)
class ToolDefinition:
    """One allowlisted tool and the contract used to invoke it."""

    name: str
    description: str
    arguments_model: type[BaseModel]
    handler: Callable[..., Any]
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("工具名称不能为空")
        if self.timeout_seconds <= 0:
            raise ValueError("工具超时时间必须大于 0")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.arguments_model.model_json_schema(),
            "strict": True,
        }

    def validate_arguments(
        self,
        arguments: str | dict[str, Any],
    ) -> BaseModel:
        if isinstance(arguments, str):
            return self.arguments_model.model_validate_json(arguments)
        return self.arguments_model.model_validate(arguments)


class ToolRegistry:
    """Allowlist, validate, and execute tools through one stable interface."""

    def __init__(self, tools: Iterable[ToolDefinition] = ()) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具已注册：{tool.name}")
        self._tools[tool.name] = tool

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def get(self, tool_name: str) -> ToolDefinition:
        try:
            return self._tools[tool_name]
        except KeyError as exc:
            raise ValueError(f"未注册的工具：{tool_name}") from exc

    def execute(
        self,
        tool_name: str,
        arguments: str | dict[str, Any],
    ) -> Any:
        tool = self.get(tool_name)
        validated = tool.validate_arguments(arguments)

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(tool.handler, **validated.model_dump())
        try:
            return future.result(timeout=tool.timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise ToolTimeoutError(
                f"工具 {tool_name} 执行超时（{tool.timeout_seconds:g} 秒）"
            ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


class CurrentDateArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: Literal["Asia/Shanghai", "UTC"] = Field(
        description="日期所使用的时区",
    )


TIMEZONES = {
    "Asia/Shanghai": datetime_timezone(
        timedelta(hours=8),
        name="Asia/Shanghai",
    ),
    "UTC": datetime_timezone.utc,
}


def current_date(timezone: str = "Asia/Shanghai") -> dict[str, str]:
    now = datetime.now(TIMEZONES[timezone])
    return {
        "date": now.date().isoformat(),
        "timezone": timezone,
    }


class ProjectTypeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_type: Literal["shopping_mall", "logistics_park"] = Field(
        description="需要查询的建设项目类型",
    )


PROJECT_TYPE_PROFILES: dict[str, dict[str, Any]] = {
    "shopping_mall": {
        "display_name": "商场",
        "review_focus": ["规划用地性质", "交通可达性", "公共服务承载"],
    },
    "logistics_park": {
        "display_name": "物流园",
        "review_focus": ["规划用地性质", "货运交通条件", "生态与耕地约束"],
    },
}


def project_type_profile(project_type: str) -> dict[str, Any]:
    profile = PROJECT_TYPE_PROFILES[project_type]
    return {
        "project_type": project_type,
        "supported": True,
        **profile,
    }


CALCULATOR_DEFINITION = ToolDefinition(
    name="calculator",
    description="对两个数字执行加、减、乘、除运算。",
    arguments_model=CalculatorArguments,
    handler=calculator,
)

CURRENT_DATE_DEFINITION = ToolDefinition(
    name="current_date",
    description="查询 Asia/Shanghai 或 UTC 时区的当前日期。",
    arguments_model=CurrentDateArguments,
    handler=current_date,
)

PROJECT_TYPE_DEFINITION = ToolDefinition(
    name="project_type_profile",
    description=(
        "查询当前示例系统支持的项目类型及其基础审查重点；"
        "该工具不生成合规结论。"
    ),
    arguments_model=ProjectTypeArguments,
    handler=project_type_profile,
)


def create_default_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            CALCULATOR_DEFINITION,
            CURRENT_DATE_DEFINITION,
            PROJECT_TYPE_DEFINITION,
        ]
    )
