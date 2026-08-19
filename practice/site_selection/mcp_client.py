from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .domain import NonEmptyString


class MCPClientConfigurationError(RuntimeError):
    """Raised when the server tool set differs from the reviewed whitelist."""


class MCPToolCallError(RuntimeError):
    """Raised when an MCP call fails, times out, or returns unstructured data."""


class MCPToolCallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: NonEmptyString
    data: dict[str, Any] = Field(default_factory=dict)


class SiteSelectionMCPClient:
    """Context-managed MCP client with exact tool whitelist and timeout."""

    def __init__(
        self,
        server_or_transport: Any,
        *,
        allowed_tools: set[str] | frozenset[str],
        timeout_seconds: float = 5,
        client_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        normalized_tools = frozenset(tool.strip() for tool in allowed_tools)
        if not normalized_tools or "" in normalized_tools:
            raise ValueError("MCP Client 工具白名单不能为空")
        if timeout_seconds <= 0:
            raise ValueError("MCP Client 超时必须大于 0")
        self._transport = server_or_transport
        self._allowed_tools = normalized_tools
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory or _default_client_factory
        self._context = None
        self._session = None

    async def __aenter__(self) -> SiteSelectionMCPClient:
        self._context = self._client_factory(self._transport)
        self._session = await self._context.__aenter__()
        try:
            async with asyncio.timeout(self._timeout_seconds):
                listed = await self._session.list_tools()
        except Exception:
            await self._context.__aexit__(None, None, None)
            self._session = None
            self._context = None
            raise
        actual = frozenset(tool.name for tool in listed.tools)
        if actual != self._allowed_tools:
            await self._context.__aexit__(None, None, None)
            self._session = None
            self._context = None
            raise MCPClientConfigurationError(
                "MCP Server 工具集与白名单不一致："
                f"missing={sorted(self._allowed_tools - actual)}, "
                f"unexpected={sorted(actual - self._allowed_tools)}"
            )
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self._context is not None:
            await self._context.__aexit__(exc_type, exc, traceback)
        self._session = None
        self._context = None

    async def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> MCPToolCallResult:
        if self._session is None:
            raise MCPClientConfigurationError("MCP Client 尚未连接")
        if tool_name not in self._allowed_tools:
            raise MCPClientConfigurationError(
                f"MCP 工具不在白名单：{tool_name}"
            )
        try:
            async with asyncio.timeout(self._timeout_seconds):
                result = await self._session.call_tool(
                    tool_name,
                    dict(arguments),
                )
        except TimeoutError as exc:
            raise MCPToolCallError(f"MCP 工具调用超时：{tool_name}") from exc
        except Exception as exc:
            raise MCPToolCallError(
                f"MCP 工具调用失败：{tool_name}, error={type(exc).__name__}"
            ) from exc
        if getattr(result, "is_error", False):
            raise MCPToolCallError(f"MCP 工具返回错误结果：{tool_name}")
        structured = getattr(result, "structured_content", None)
        if not isinstance(structured, dict):
            raise MCPToolCallError(f"MCP 工具未返回结构化对象：{tool_name}")
        return MCPToolCallResult(tool_name=tool_name, data=structured)


def _default_client_factory(server_or_transport: Any) -> Any:
    try:
        from mcp import Client
    except ImportError as exc:
        raise RuntimeError("缺少 MCP SDK，请先安装 requirements.txt") from exc
    return Client(server_or_transport)
