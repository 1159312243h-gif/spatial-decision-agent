from pathlib import Path
from datetime import datetime, timezone

import geopandas as gpd
import pytest
from shapely.geometry import shape

from app.site_selection_bootstrap import (
    SiteSelectionBootstrapError,
    build_fixture_runtime_registry,
    build_site_selection_bootstrap_from_environment,
    load_fixture_spatial_seed,
    seed_fixture_storage,
)
from practice.site_selection import (
    AnalysisStatus,
    CandidateParcel,
    ProjectRequest,
    ProjectType,
    run_parallel_site_selection_workflow,
)
from practice.site_selection.poi_adapters import FixturePOIDataset
from practice.site_selection.spatial import MockSpatialDatasetGateway
from tests.storage_fakes import FakeConnection, FakeRedis
from tests.test_site_selection_async_queue import FakeJobQueue


FIXTURE_ROOT = Path(__file__).parents[1] / "data" / "fixtures"


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


def test_spatial_fixture_declares_both_projects_and_expected_layers() -> None:
    seed = load_fixture_spatial_seed(FIXTURE_ROOT / "spatial_layers.json")

    assert {project.project_type for project in seed.projects} == {
        ProjectType.SHOPPING_MALL,
        ProjectType.LOGISTICS_PARK,
    }
    assert {layer.layer_id for layer in seed.layers} == {
        "demo-mall-candidates",
        "demo-mall-constraints",
        "demo-logistics-candidates",
        "demo-logistics-constraints",
    }
    assert seed.crs == "EPSG:32651"


def test_fixture_registry_exposes_both_reviewed_project_types() -> None:
    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
    )

    assert registry.configured_types == (
        ProjectType.SHOPPING_MALL,
        ProjectType.LOGISTICS_PARK,
    )
    for project_type in registry.configured_types:
        runtime = registry.resolve(project_type)
        assert runtime.project_type is project_type
        assert len(runtime.datasets) == 2
        assert runtime.dependencies.site_scoring_config is not None
        assert runtime.dependencies.poi_scoring_config.version.startswith("fixture-")
        assert all(
            rule.policy.source_uri.startswith("fixture://")
            for rule in runtime.dependencies.rules
        )


def test_both_fixture_project_types_complete_full_workflow() -> None:
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
    candidates = {
        ProjectType.SHOPPING_MALL: [
            CandidateParcel(
                parcel_id="MALL-A01",
                longitude=121.4700,
                latitude=31.2300,
                geometry_dataset_id="demo-mall-candidates",
            ),
            CandidateParcel(
                parcel_id="MALL-A02",
                longitude=121.4850,
                latitude=31.2350,
                geometry_dataset_id="demo-mall-candidates",
            ),
        ],
        ProjectType.LOGISTICS_PARK: [
            CandidateParcel(
                parcel_id="LOG-A01",
                longitude=121.5200,
                latitude=31.2400,
                geometry_dataset_id="demo-logistics-candidates",
            ),
            CandidateParcel(
                parcel_id="LOG-A02",
                longitude=121.5600,
                latitude=31.2550,
                geometry_dataset_id="demo-logistics-candidates",
            ),
        ],
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
        assert len(result.results) == 2
        assert len(result.comparison_report.candidates) == 2
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
