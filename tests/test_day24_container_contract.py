from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_dockerfile_copies_all_runtime_assets() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    for path in ("app", "practice", "data", "deploy", "scripts", "workbench"):
        assert f"COPY {path} ./{path}" in dockerfile


def test_compose_explicitly_wires_api_mcp_workbench_and_storage() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert set(services) == {
        "api",
        "worker",
        "mcp",
        "workbench",
        "postgis",
        "redis",
    }
    assert services["api"]["environment"]["SITE_SELECTION_RUNTIME_MODE"] == "fixture"
    assert services["api"]["environment"]["SITE_SELECTION_RUN_MODE"] == "async"
    assert services["api"]["environment"][
        "SITE_SELECTION_SUPERVISOR_ENABLED"
    ] == "${SITE_SELECTION_SUPERVISOR_ENABLED:-true}"
    assert services["api"]["environment"][
        "SITE_SELECTION_SUPERVISOR_SESSION_TTL_SECONDS"
    ] == "${SITE_SELECTION_SUPERVISOR_SESSION_TTL_SECONDS:-7200}"
    assert services["api"]["environment"][
        "SITE_SELECTION_SUPERVISOR_LOCK_TTL_SECONDS"
    ] == "${SITE_SELECTION_SUPERVISOR_LOCK_TTL_SECONDS:-120}"
    assert services["api"]["environment"]["SITE_SELECTION_POI_PROVIDER"] == (
        "${SITE_SELECTION_POI_PROVIDER:-auto}"
    )
    assert services["worker"]["environment"]["SITE_SELECTION_POI_PROVIDER"] == (
        "${SITE_SELECTION_POI_PROVIDER:-auto}"
    )
    for service_name in ("api", "worker"):
        assert services[service_name]["environment"][
            "SITE_SELECTION_SUPERVISOR_ENABLED"
        ] == "${SITE_SELECTION_SUPERVISOR_ENABLED:-true}"
        assert services[service_name]["environment"][
            "SITE_SELECTION_SUPERVISOR_SESSION_TTL_SECONDS"
        ] == "${SITE_SELECTION_SUPERVISOR_SESSION_TTL_SECONDS:-7200}"
        assert services[service_name]["environment"][
            "SITE_SELECTION_SUPERVISOR_LOCK_TTL_SECONDS"
        ] == "${SITE_SELECTION_SUPERVISOR_LOCK_TTL_SECONDS:-120}"
    for service_name in ("api", "worker"):
        environment = services[service_name]["environment"]
        assert environment["SITE_SELECTION_POI_TIMEOUT_SECONDS"] == (
            "${SITE_SELECTION_POI_TIMEOUT_SECONDS:-15}"
        )
        assert environment["SITE_SELECTION_POI_MAX_ATTEMPTS"] == (
            "${SITE_SELECTION_POI_MAX_ATTEMPTS:-2}"
        )
        assert environment["SITE_SELECTION_POI_FAILURE_THRESHOLD"] == (
            "${SITE_SELECTION_POI_FAILURE_THRESHOLD:-12}"
        )
        assert environment["SITE_SELECTION_POI_REQUESTS_PER_SECOND"] == (
            "${SITE_SELECTION_POI_REQUESTS_PER_SECOND:-1}"
        )
        assert environment["SITE_SELECTION_POI_RETRY_BASE_SECONDS"] == (
            "${SITE_SELECTION_POI_RETRY_BASE_SECONDS:-2}"
        )
        assert environment["SITE_SELECTION_POI_RETRY_MAX_SECONDS"] == (
            "${SITE_SELECTION_POI_RETRY_MAX_SECONDS:-8}"
        )
        assert environment["SITE_SELECTION_POI_PROXY_URL"] == (
            "${SITE_SELECTION_POI_PROXY_URL:-}"
        )
        assert environment[
            "SITE_SELECTION_DISCOVERY_SNAPSHOT_TTL_SECONDS"
        ] == "${SITE_SELECTION_DISCOVERY_SNAPSHOT_TTL_SECONDS:-7200}"
        assert environment["SITE_SELECTION_AMAP_MAX_PAGES_PER_SEARCH"] == (
            "${SITE_SELECTION_AMAP_MAX_PAGES_PER_SEARCH:-2}"
        )
        assert environment[
            "SITE_SELECTION_AMAP_MAX_CATEGORIES_PER_QUERY"
        ] == "${SITE_SELECTION_AMAP_MAX_CATEGORIES_PER_QUERY:-3}"
        assert environment[
            "SITE_SELECTION_OVERPASS_MAX_CATEGORIES_PER_QUERY"
        ] == "${SITE_SELECTION_OVERPASS_MAX_CATEGORIES_PER_QUERY:-3}"
        assert environment["SITE_SELECTION_EXPLANATION_TIMEOUT_SECONDS"] == (
            "${SITE_SELECTION_EXPLANATION_TIMEOUT_SECONDS:-15}"
        )
        assert environment["SITE_SELECTION_EXPLANATION_MAX_RETRIES"] == (
            "${SITE_SELECTION_EXPLANATION_MAX_RETRIES:-0}"
        )
    assert services["api"]["environment"]["AMAP_API_KEY"] == (
        "${AMAP_API_KEY:-}"
    )
    assert services["worker"]["command"][-1] == (
        "scripts/run_site_selection_worker.py"
    )
    assert services["worker"]["volumes"] == [
        "report_artifacts:/app/artifacts/reports"
    ]
    assert services["workbench"]["environment"]["SITE_SELECTION_API_URL"] == (
        "http://api:8000"
    )
    assert services["workbench"]["environment"][
        "SITE_SELECTION_PUBLIC_API_URL"
    ] == "http://localhost:${API_PORT:-8000}"
    assert services["workbench"]["command"][:4] == [
        "python",
        "-m",
        "streamlit",
        "run",
    ]
    assert services["mcp"]["command"][-1] == "scripts/run_fixture_mcp_server.py"
    assert services["mcp"]["depends_on"]["api"]["condition"] == (
        "service_healthy"
    )


def test_requirements_include_official_postgres_checkpointer() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "langgraph-checkpoint-postgres>=3,<4" in requirements
