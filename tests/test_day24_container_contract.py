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
    assert services["api"]["environment"]["SITE_SELECTION_POI_PROVIDER"] == (
        "${SITE_SELECTION_POI_PROVIDER:-fixture}"
    )
    assert services["worker"]["environment"]["SITE_SELECTION_POI_PROVIDER"] == (
        "${SITE_SELECTION_POI_PROVIDER:-fixture}"
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
