from scripts.smoke_site_selection_redis_runtime import build_redis_client


def test_build_redis_client_prefers_explicit_url(monkeypatch) -> None:
    monkeypatch.setenv(
        "SITE_SELECTION_REDIS_URL",
        "redis://:fixture-secret@127.0.0.1:6380/3",
    )

    client = build_redis_client()
    connection = client.connection_pool.connection_kwargs

    assert connection["host"] == "127.0.0.1"
    assert connection["port"] == 6380
    assert connection["db"] == 3
    assert connection["password"] == "fixture-secret"


def test_build_redis_client_loads_compose_credentials_from_env_file(
    monkeypatch,
    tmp_path,
) -> None:
    env_file = tmp_path / "redis-smoke.env"
    env_file.write_text(
        "REDIS_HOST=127.0.0.2\n"
        "REDIS_PORT=6381\n"
        "REDIS_DB=4\n"
        "REDIS_PASSWORD=fixture-password\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("SITE_SELECTION_REDIS_URL", raising=False)
    for name in ("REDIS_HOST", "REDIS_PORT", "REDIS_DB", "REDIS_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENV_FILE", str(env_file))

    client = build_redis_client()
    connection = client.connection_pool.connection_kwargs

    assert connection["host"] == "127.0.0.2"
    assert connection["port"] == 6381
    assert connection["db"] == 4
    assert connection["password"] == "fixture-password"
