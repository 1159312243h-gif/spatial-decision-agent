from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine


MIGRATION_ROOT = PROJECT_ROOT / "deploy" / "migrations"
MIGRATION_PATH = MIGRATION_ROOT / "001_initial.sql"


def migration_paths() -> tuple[Path, ...]:
    paths = tuple(sorted(MIGRATION_ROOT.glob("[0-9][0-9][0-9]_*.sql")))
    if not paths:
        raise RuntimeError("未找到 PostGIS migration")
    return paths


def required_environment(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"缺少环境变量：{name}")
    return value


def build_host_database_url() -> URL:
    try:
        port = int(os.getenv("POSTGRES_PORT", "5432"))
    except ValueError as exc:
        raise RuntimeError("POSTGRES_PORT 必须是整数") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("POSTGRES_PORT 超出有效范围")
    return URL.create(
        drivername="postgresql+psycopg",
        username=os.getenv("POSTGRES_USER", "agent"),
        password=required_environment("POSTGRES_PASSWORD"),
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=port,
        database=os.getenv("POSTGRES_DB", "site_selection"),
    )


def load_environment() -> None:
    load_dotenv(os.getenv("ENV_FILE", PROJECT_ROOT / ".env"))


def apply_migration(engine: Engine) -> None:
    raw_connection = engine.raw_connection()
    try:
        with raw_connection.cursor() as cursor:
            for path in migration_paths():
                cursor.execute(path.read_text(encoding="utf-8"), prepare=False)
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        raw_connection.close()


def main() -> int:
    load_environment()
    engine = create_engine(
        build_host_database_url(),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    try:
        apply_migration(engine)
    except Exception as exc:
        print(f"PostGIS migration FAILED: error_type={type(exc).__name__}")
        return 1
    finally:
        engine.dispose()
    print(f"PostGIS migration OK: version={migration_paths()[-1].stem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
