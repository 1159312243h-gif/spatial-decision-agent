from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    from redis import Redis
    from rq import Queue, Worker

    redis_url = _required_environment("REDIS_URL")
    queue_name = os.getenv(
        "SITE_SELECTION_QUEUE_NAME",
        "site-selection",
    ).strip()
    if not queue_name:
        raise RuntimeError("SITE_SELECTION_QUEUE_NAME cannot be blank")

    connection = Redis.from_url(redis_url)
    connection.ping()
    queue = Queue(queue_name, connection=connection)
    Worker([queue], connection=connection).work(with_scheduler=False)


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing environment variable: {name}")
    return value


if __name__ == "__main__":
    main()
