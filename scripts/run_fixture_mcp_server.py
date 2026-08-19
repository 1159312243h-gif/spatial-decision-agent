from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text

from app.site_selection_bootstrap import build_fixture_mcp_server


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量：{name}")
    return value


def main() -> int:
    if os.getenv("SITE_SELECTION_RUNTIME_MODE", "").strip().lower() != "fixture":
        print("MCP server FAILED: fixture runtime mode is not enabled")
        return 1
    try:
        port = int(os.getenv("MCP_PORT", "8001"))
    except ValueError:
        print("MCP server FAILED: MCP_PORT must be an integer")
        return 1
    if not 1 <= port <= 65535:
        print("MCP server FAILED: MCP_PORT is out of range")
        return 1

    engine = create_engine(
        _required_environment("DATABASE_URL"),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        server = build_fixture_mcp_server(engine)
        server.run(
            transport="streamable-http",
            host=os.getenv("MCP_HOST", "127.0.0.1"),
            port=port,
            streamable_http_path="/mcp",
            stateless_http=True,
        )
    except Exception as exc:
        print(f"MCP server FAILED: error_type={type(exc).__name__}")
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
