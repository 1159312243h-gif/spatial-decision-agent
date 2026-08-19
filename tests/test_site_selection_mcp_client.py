from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from practice.site_selection import (
    MCPClientConfigurationError,
    MCPToolCallError,
    MCPToolCallResult,
    SiteSelectionMCPClient,
)
from practice.site_selection.mcp_server import create_site_selection_mcp_server
from tests.test_site_selection_mcp_tools import registry


def test_real_mcp_client_wrapper_verifies_and_calls_whitelist() -> None:
    async def scenario() -> None:
        tools = registry()
        server = create_site_selection_mcp_server(tools)
        async with SiteSelectionMCPClient(
            server,
            allowed_tools=set(tools.names),
        ) as client:
            result = await client.call_tool(
                "gis_feature_area",
                {"layer_id": "candidate", "source_feature_id": "A01"},
            )
            assert isinstance(result, MCPToolCallResult)
            assert result.data["area_hectares"] == 1

    asyncio.run(scenario())


def test_client_rejects_server_tool_set_different_from_whitelist() -> None:
    async def scenario() -> None:
        tools = registry()
        server = create_site_selection_mcp_server(tools)
        with pytest.raises(MCPClientConfigurationError, match="unexpected"):
            async with SiteSelectionMCPClient(
                server,
                allowed_tools={"gis_feature_area"},
            ):
                pass

    asyncio.run(scenario())


def test_client_blocks_unknown_tool_before_transport_call() -> None:
    async def scenario() -> None:
        tools = registry()
        server = create_site_selection_mcp_server(tools)
        async with SiteSelectionMCPClient(
            server,
            allowed_tools=set(tools.names),
        ) as client:
            with pytest.raises(MCPClientConfigurationError, match="白名单"):
                await client.call_tool("unknown_tool", {})

    asyncio.run(scenario())


def test_client_maps_timeout_without_leaking_transport_details() -> None:
    class SlowSession:
        async def list_tools(self):
            return SimpleNamespace(
                tools=[SimpleNamespace(name="slow_tool")]
            )

        async def call_tool(self, name, arguments):
            await asyncio.sleep(0.05)

    class SlowContext:
        async def __aenter__(self):
            return SlowSession()

        async def __aexit__(self, *args):
            return None

    async def scenario() -> None:
        async with SiteSelectionMCPClient(
            object(),
            allowed_tools={"slow_tool"},
            timeout_seconds=0.01,
            client_factory=lambda transport: SlowContext(),
        ) as client:
            with pytest.raises(MCPToolCallError, match="超时"):
                await client.call_tool("slow_tool", {})

    asyncio.run(scenario())
