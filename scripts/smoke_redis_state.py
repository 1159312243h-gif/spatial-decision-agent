from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from redis import Redis

from practice.site_selection.storage.redis_state import (
    RedisRunStateStore,
    RunStatus,
)


RUN_ID = "redis-smoke-run"


def required_environment(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"缺少环境变量：{name}")
    return value


def run_smoke() -> None:
    load_dotenv(os.getenv("ENV_FILE", PROJECT_ROOT / ".env"))
    try:
        port = int(os.getenv("REDIS_PORT", "6379"))
    except ValueError as exc:
        raise RuntimeError("REDIS_PORT 必须是整数") from exc
    client = Redis(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=port,
        password=required_environment("REDIS_PASSWORD"),
        socket_connect_timeout=5,
        socket_timeout=5,
        decode_responses=False,
    )
    store = RedisRunStateStore(
        client,
        namespace="site_selection:smoke",
        ttl_seconds=300,
    )
    try:
        if client.ping() is not True:
            raise RuntimeError("Redis PING 未返回成功")
        expected = store.update(
            RUN_ID,
            RunStatus.RUNNING,
            details={"source": "smoke"},
        )
        actual = store.get(RUN_ID)
        ttl = store.ttl(RUN_ID)
        if actual != expected:
            raise RuntimeError("Redis 运行状态回读不一致")
        if not 0 < ttl <= 300:
            raise RuntimeError("Redis 运行状态 TTL 不在预期范围")
    finally:
        store.delete(RUN_ID)
        client.close()

    print("Redis state smoke OK: namespace=site_selection:smoke, ttl=300")


def main() -> int:
    try:
        run_smoke()
    except Exception as exc:
        print(f"Redis state smoke FAILED: error_type={type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
