from pathlib import Path
from datetime import datetime, timezone
import sys
import types

import geopandas as gpd
import pytest
from shapely.geometry import shape

from app.site_selection_bootstrap import (
    SiteSelectionBootstrapError,
    _build_optional_explainer,
    _build_optional_multi_agent_runtime,
    build_fixture_runtime_registry,
    build_site_selection_bootstrap_from_environment,
    load_fixture_spatial_seed,
    open_postgres_supervisor_checkpointer,
    seed_fixture_storage,
)
from practice.site_selection import (
    AgentRole,
    AnalysisStatus,
    CandidateParcel,
    ProjectRequest,
    ProjectType,
    load_fixture_candidate_catalog,
    run_parallel_site_selection_workflow,
)
from practice.site_selection.poi_adapters import FixturePOIDataset
from practice.site_selection.spatial import MockSpatialDatasetGateway
from tests.storage_fakes import FakeConnection, FakeRedis
from tests.test_site_selection_async_queue import FakeJobQueue


FIXTURE_ROOT = Path(__file__).parents[1] / "data" / "fixtures"


def test_optional_multi_agent_runtime_is_explicit_and_role_configurable() -> None:
    assert (
        _build_optional_multi_agent_runtime(
            {},
            object(),
            runtime_namespace="fixture",
        )
        is None
    )
    calls = []

    def client_factory(**kwargs):
        calls.append(kwargs)
        return object()

    runtime = _build_optional_multi_agent_runtime(
        {
            "SITE_SELECTION_MULTI_AGENT_ENABLED": "true",
            "LLM_API_KEY": "fixture-key",
            "LLM_BASE_URL": "https://llm.example/v1",
            "LLM_MODEL": "default-model",
            "SITE_SELECTION_REVIEW_AGENT_MODEL": "critic-model",
            "SITE_SELECTION_MULTI_AGENT_MAX_DELEGATIONS": "4",
            "SITE_SELECTION_MULTI_AGENT_MAX_REFLECTION_ROUNDS": "1",
            "SITE_SELECTION_MULTI_AGENT_MAX_LLM_CALLS": "9",
        },
        object(),
        runtime_namespace="fixture",
        client_factory=client_factory,
    )

    assert runtime is not None
    assert calls == [
        {
            "api_key": "fixture-key",
            "base_url": "https://llm.example/v1",
            "timeout": 15.0,
            "max_retries": 0,
        }
    ]
    active_runtime = runtime.runtime_for_active_version()
    assert active_runtime.roster.get(AgentRole.REVIEW).profile.model == "critic-model"
    assert active_runtime.roster.get(AgentRole.POI).profile.model == "default-model"
    assert active_runtime.budget.max_delegations == 4
    assert active_runtime.budget.max_reflection_rounds == 1
    assert active_runtime.budget.max_llm_calls == 9
    assert runtime.registry.active_version == "multi-agent-prompts-v1"


def test_optional_multi_agent_runtime_requires_complete_llm_config() -> None:
    with pytest.raises(SiteSelectionBootstrapError, match="LLM_BASE_URL"):
        _build_optional_multi_agent_runtime(
            {
                "SITE_SELECTION_MULTI_AGENT_ENABLED": "true",
                "LLM_API_KEY": "fixture-key",
                "LLM_MODEL": "fixture-model",
            },
            object(),
            runtime_namespace="fixture",
        )


def test_optional_explainer_has_bounded_timeout_and_no_default_retries() -> None:
    calls = []

    def client_factory(**kwargs):
        calls.append(kwargs)
        return object()

    explainer = _build_optional_explainer(
        {
            "LLM_API_KEY": "fixture-key",
            "LLM_BASE_URL": "https://llm.example/v1",
            "LLM_MODEL": "fixture-model",
        },
        client_factory=client_factory,
    )

    assert explainer is not None
    assert calls == [
        {
            "api_key": "fixture-key",
            "base_url": "https://llm.example/v1",
            "timeout": 15.0,
            "max_retries": 0,
        }
    ]


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("SITE_SELECTION_EXPLANATION_TIMEOUT_SECONDS", "0", "必须是正数"),
        ("SITE_SELECTION_EXPLANATION_MAX_RETRIES", "-1", "必须是非负整数"),
    ],
)
def test_optional_explainer_rejects_unbounded_retry_configuration(
    name,
    value,
    message,
) -> None:
    values = {
        "LLM_API_KEY": "fixture-key",
        "LLM_BASE_URL": "https://llm.example/v1",
        "LLM_MODEL": "fixture-model",
        name: value,
    }

    with pytest.raises(SiteSelectionBootstrapError, match=message):
        _build_optional_explainer(values, client_factory=lambda **kwargs: object())


def test_runtime_is_fail_closed_when_mode_is_not_enabled() -> None:
    def forbidden_factory(*args, **kwargs):
        raise AssertionError("未启用 fixture 时不能连接外部服务")

    result = build_site_selection_bootstrap_from_environment(
        {},
        engine_factory=forbidden_factory,
        redis_factory=forbidden_factory,
    )

    assert result is None


def test_explicit_runtime_mode_and_required_connections_are_validated() -> None:
    with pytest.raises(SiteSelectionBootstrapError, match="不支持"):
        build_site_selection_bootstrap_from_environment(
            {"SITE_SELECTION_RUNTIME_MODE": "production"}
        )

    with pytest.raises(SiteSelectionBootstrapError, match="DATABASE_URL"):
        build_site_selection_bootstrap_from_environment(
            {"SITE_SELECTION_RUNTIME_MODE": "fixture"}
        )

    with pytest.raises(SiteSelectionBootstrapError, match="sync 或 async"):
        build_site_selection_bootstrap_from_environment(
            {
                "SITE_SELECTION_RUNTIME_MODE": "fixture",
                "SITE_SELECTION_RUN_MODE": "inline",
            }
        )


def test_spatial_fixture_declares_all_projects_and_expected_layers() -> None:
    seed = load_fixture_spatial_seed(FIXTURE_ROOT / "spatial_layers.json")

    assert {project.project_type for project in seed.projects} == {
        ProjectType.SHOPPING_MALL,
        ProjectType.LOGISTICS_PARK,
        ProjectType.COFFEE_SHOP,
        ProjectType.CONVENIENCE_STORE,
    }
    assert {layer.layer_id for layer in seed.layers} == {
        "demo-mall-candidates",
        "demo-mall-constraints",
        "demo-logistics-candidates",
        "demo-logistics-constraints",
        "demo-coffee-candidates",
        "demo-coffee-constraints",
        "demo-coffee-discovery-pool",
        "demo-convenience-candidates",
        "demo-convenience-constraints",
        "demo-convenience-discovery-pool",
    }
    assert seed.crs == "EPSG:32651"
    layers = {layer.layer_id: layer for layer in seed.layers}
    assert len(layers["demo-mall-candidates"].features) == 6
    assert len(layers["demo-logistics-candidates"].features) == 6
    assert len(layers["demo-coffee-candidates"].features) == 6
    assert len(layers["demo-convenience-candidates"].features) == 6
    assert len(layers["demo-coffee-discovery-pool"].features) == 25
    assert len(layers["demo-convenience-discovery-pool"].features) == 25


def test_fixture_registry_exposes_all_reviewed_project_types() -> None:
    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
    )

    assert registry.configured_types == (
        ProjectType.SHOPPING_MALL,
        ProjectType.LOGISTICS_PARK,
        ProjectType.COFFEE_SHOP,
        ProjectType.CONVENIENCE_STORE,
    )
    for project_type in registry.configured_types:
        runtime = registry.resolve(project_type)
        assert runtime.project_type is project_type
        assert len(runtime.datasets) == (
            3
            if project_type in {
                ProjectType.COFFEE_SHOP,
                ProjectType.CONVENIENCE_STORE,
            }
            else 2
        )
        assert runtime.dependencies.site_scoring_config is not None
        assert runtime.dependencies.poi_scoring_config.version.startswith("fixture-")
        assert all(
            rule.policy.source_uri.startswith("fixture://")
            for rule in runtime.dependencies.rules
        )


def test_all_fixture_project_types_complete_full_workflow() -> None:
    seed = load_fixture_spatial_seed(FIXTURE_ROOT / "spatial_layers.json")
    frames = {
        layer.layer_id: gpd.GeoDataFrame(
            [feature.properties for feature in layer.features],
            geometry=[shape(feature.geometry) for feature in layer.features],
            crs=seed.crs,
        )
        for layer in seed.layers
    }
    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=MockSpatialDatasetGateway(frames),
    )
    catalog = load_fixture_candidate_catalog(FIXTURE_ROOT / "candidates.json")
    candidates = {
        project_type: [item.to_candidate() for item in items]
        for project_type, items in catalog.project_candidates.items()
    }

    for project_type, project_candidates in candidates.items():
        runtime = registry.resolve(project_type)
        result = run_parallel_site_selection_workflow(
            ProjectRequest(
                request_id=f"fixture-{project_type.value}",
                project_type=project_type,
                candidate_parcels=project_candidates,
                requested_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
            ),
            runtime.datasets,
            runtime.dependencies,
        )

        assert result.status is AnalysisStatus.COMPLETED
        assert len(result.results) == 6
        assert len(result.comparison_report.candidates) == 6
        assert len(
            {round(item.overall_soft_score, 6) for item in result.results}
        ) >= 4
        assert all(item.gis_evidence.metrics for item in result.results)
        assert all(item.poi_evidence.feature_sets for item in result.results)
        assert all(
            item.policy_evidence.evaluated_rule_ids
            for item in result.results
        )


def test_seed_uses_parameterized_repositories_for_all_layers_and_pois() -> None:
    seed = load_fixture_spatial_seed(FIXTURE_ROOT / "spatial_layers.json")
    poi_dataset = FixturePOIDataset.model_validate_json(
        (FIXTURE_ROOT / "poi.json").read_text(encoding="utf-8")
    )
    connection = FakeConnection()

    seed_fixture_storage(connection, seed, poi_dataset)

    sql = "\n".join(statement for statement, _ in connection.calls)
    assert "INSERT INTO site_selection.projects" in sql
    assert "INSERT INTO site_selection.spatial_features" in sql
    assert "INSERT INTO site_selection.pois" in sql
    assert "MALL-A01" not in sql
    assert "F001" not in sql


def test_async_bootstrap_builds_separate_queue_and_skips_mcp(tmp_path) -> None:
    class FakeEngine:
        def __init__(self) -> None:
            self.connection = FakeConnection()
            self.dispose_calls = 0

        def begin(self):
            connection = self.connection

            class Transaction:
                def __enter__(self):
                    return connection

                def __exit__(self, exc_type, exc_value, traceback):
                    return False

            return Transaction()

        def dispose(self) -> None:
            self.dispose_calls += 1

    class PingableRedis(FakeRedis):
        def __init__(self) -> None:
            super().__init__()
            self.close_calls = 0

        def ping(self) -> bool:
            return True

        def close(self) -> None:
            self.close_calls += 1

    engine = FakeEngine()
    redis_client = PingableRedis()
    queue = FakeJobQueue()
    captured = {}

    def queue_factory(redis_url, settings):
        captured["redis_url"] = redis_url
        captured["settings"] = settings
        return queue

    bootstrap = build_site_selection_bootstrap_from_environment(
        {
            "SITE_SELECTION_RUNTIME_MODE": "fixture",
            "SITE_SELECTION_RUN_MODE": "async",
            "DATABASE_URL": "postgresql+psycopg://fixture",
            "REDIS_URL": "redis://fixture/0",
            "SITE_SELECTION_REPORT_DIR": str(tmp_path / "reports"),
            "SITE_SELECTION_QUEUE_NAME": "test-queue",
        },
        engine_factory=lambda *args, **kwargs: engine,
        redis_factory=lambda *args, **kwargs: redis_client,
        job_queue_factory=queue_factory,
        migration_applier=lambda configured_engine: None,
        fixture_root=FIXTURE_ROOT,
        include_mcp=False,
    )

    assert bootstrap.run_mode == "async"
    assert bootstrap.mcp_server is None
    assert bootstrap.job_queue is queue
    assert captured["redis_url"] == "redis://fixture/0"
    assert captured["settings"].queue_name == "test-queue"

    bootstrap.close()
    bootstrap.close()

    assert queue.closed is True
    assert redis_client.close_calls == 1
    assert engine.dispose_calls == 1


def test_postgres_supervisor_checkpointer_normalizes_url_and_runs_setup(
    monkeypatch,
) -> None:
    calls = []

    class FakeSaver:
        def setup(self) -> None:
            calls.append("setup")

    class FakeContext:
        def __init__(self) -> None:
            self.saver = FakeSaver()

        def __enter__(self):
            calls.append("enter")
            return self.saver

        def __exit__(self, exc_type, exc_value, traceback):
            calls.append("exit")

    context = FakeContext()

    class FakePostgresSaver:
        @classmethod
        def from_conn_string(cls, value):
            calls.append(value)
            return context

    module = types.ModuleType("langgraph.checkpoint.postgres")
    module.PostgresSaver = FakePostgresSaver
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.postgres", module)

    saver, opened_context = open_postgres_supervisor_checkpointer(
        "postgresql+psycopg://agent:secret@postgis/site_selection"
    )

    assert saver is context.saver
    assert opened_context is context
    assert calls == [
        "postgresql://agent:secret@postgis/site_selection",
        "enter",
        "setup",
    ]

    opened_context.__exit__(None, None, None)
    assert calls[-1] == "exit"


def test_bootstrap_wires_durable_supervisor_without_memory_fallback(
    tmp_path,
) -> None:
    class FakeEngine:
        def __init__(self) -> None:
            self.connection = FakeConnection()
            self.dispose_calls = 0

        def begin(self):
            connection = self.connection

            class Transaction:
                def __enter__(self):
                    return connection

                def __exit__(self, exc_type, exc_value, traceback):
                    return False

            return Transaction()

        def dispose(self) -> None:
            self.dispose_calls += 1

    class PingableRedis(FakeRedis):
        def ping(self) -> bool:
            return True

        def close(self) -> None:
            pass

    class FakeContext:
        def __init__(self) -> None:
            self.exit_calls = 0

        def __exit__(self, exc_type, exc_value, traceback):
            self.exit_calls += 1

    engine = FakeEngine()
    context = FakeContext()
    saver = object()
    captured_urls = []

    bootstrap = build_site_selection_bootstrap_from_environment(
        {
            "SITE_SELECTION_RUNTIME_MODE": "fixture",
            "SITE_SELECTION_RUN_MODE": "sync",
            "SITE_SELECTION_SUPERVISOR_ENABLED": "true",
            "SITE_SELECTION_SUPERVISOR_SESSION_TTL_SECONDS": "900",
            "SITE_SELECTION_SUPERVISOR_LOCK_TTL_SECONDS": "30",
            "DATABASE_URL": "postgresql+psycopg://fixture",
            "REDIS_URL": "redis://fixture/0",
            "SITE_SELECTION_REPORT_DIR": str(tmp_path / "reports"),
        },
        engine_factory=lambda *args, **kwargs: engine,
        redis_factory=lambda *args, **kwargs: PingableRedis(),
        supervisor_checkpointer_factory=lambda url: (
            captured_urls.append(url) or saver,
            context,
        ),
        migration_applier=lambda configured_engine: None,
        fixture_root=FIXTURE_ROOT,
        include_mcp=False,
    )

    assert bootstrap.supervisor_checkpointer is saver
    assert bootstrap.supervisor_coordinator is not None
    assert captured_urls == ["postgresql+psycopg://fixture"]

    bootstrap.close()
    bootstrap.close()

    assert context.exit_calls == 1
    assert engine.dispose_calls == 1
