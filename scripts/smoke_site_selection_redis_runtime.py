from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import redis
from dotenv import load_dotenv

from practice.site_selection import FixturePOIAdapter, POIQuery
from practice.site_selection.storage import (
    RedisSiteSelectionRuntimeStore,
    RunEvent,
    RunEventType,
    RunStatus,
)


def required_environment(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"缺少环境变量：{name}")
    return value


def build_redis_client() -> redis.Redis:
    load_dotenv(os.getenv("ENV_FILE", PROJECT_ROOT / ".env"))
    redis_url = os.getenv("SITE_SELECTION_REDIS_URL")
    if redis_url:
        return redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    try:
        port = int(os.getenv("REDIS_PORT", "6379"))
        database = int(os.getenv("REDIS_DB", "0"))
    except ValueError as exc:
        raise RuntimeError("REDIS_PORT 和 REDIS_DB 必须是整数") from exc
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=port,
        db=database,
        password=required_environment("REDIS_PASSWORD"),
        socket_connect_timeout=5,
        socket_timeout=5,
    )


def run_smoke() -> None:
    client = build_redis_client()
    if client.ping() is not True:
        raise RuntimeError("Redis PING 未返回成功")

    namespace = f"site_selection:smoke:{uuid4().hex}"
    store = RedisSiteSelectionRuntimeStore(
        client,
        namespace=namespace,
        run_ttl_seconds=60,
        idempotency_ttl_seconds=60,
        poi_cache_ttl_seconds=60,
        event_ttl_seconds=60,
    )
    now = datetime.now(timezone.utc)
    run_id = "run-smoke-001"
    store.run_states.update(
        run_id,
        RunStatus.RUNNING,
        details={"project_type": "shopping_mall"},
        updated_at=now,
    )

    fingerprint = "a" * 64
    first_claim = store.claim_idempotency(
        "smoke-request-001",
        run_id,
        request_fingerprint=fingerprint,
    )
    replay_claim = store.claim_idempotency(
        "smoke-request-001",
        "run-smoke-002",
        request_fingerprint=fingerprint,
    )
    if not first_claim.created or replay_claim.run_id != run_id:
        raise RuntimeError("Redis 幂等键烟雾检查失败")

    query = POIQuery(
        query_id="redis-smoke-query",
        parcel_id="redis-smoke",
        group_key="redis-smoke",
        longitude=121.47,
        latitude=31.23,
        categories=["地铁站"],
        radius_m=2_000,
        limit=20,
    )
    adapter = FixturePOIAdapter.from_json(
        PROJECT_ROOT / "data" / "fixtures" / "poi.json",
        clock=lambda: now,
    )
    feature_set = adapter.search(query)
    store.save_cached_poi(feature_set, cache_scope="fixture:2026.08.1")
    if store.get_cached_poi(
        query,
        cache_scope="fixture:2026.08.1",
    ) != feature_set:
        raise RuntimeError("Redis POI 缓存烟雾检查失败")

    for event_type in (RunEventType.CREATED, RunEventType.STARTED):
        store.append_event(
            RunEvent(
                run_id=run_id,
                event_type=event_type,
                occurred_at=now,
            )
        )
    event_types = [event.event_type for event in store.list_events(run_id)]
    if event_types != [RunEventType.CREATED, RunEventType.STARTED]:
        raise RuntimeError("Redis 运行事件顺序烟雾检查失败")

    ttls = {
        "run": store.run_states.ttl(run_id),
        "idempotency": store.idempotency_ttl("smoke-request-001"),
        "poi_cache": store.poi_cache_ttl(
            query,
            cache_scope="fixture:2026.08.1",
        ),
        "events": store.events_ttl(run_id),
    }
    if any(ttl <= 0 for ttl in ttls.values()):
        raise RuntimeError(f"Redis TTL 烟雾检查失败：{ttls}")

    print(
        "Site-selection Redis runtime smoke OK: "
        f"records={feature_set.source.record_count}, "
        f"events={len(event_types)}, idempotent=true, ttl=true"
    )
    client.close()


def main() -> int:
    try:
        run_smoke()
    except Exception as exc:
        print(
            "Site-selection Redis runtime smoke FAILED: "
            f"error_type={type(exc).__name__}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
