from __future__ import annotations

import json
import os
import sys
from math import pi
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pyproj import CRS
from shapely.geometry import shape
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.services.site_selection_artifacts import FileSystemSiteSelectionReportStore
from app.services.site_selection_explanation import (
    OpenAISiteSelectionEvidenceExplainer,
    SiteSelectionEvidenceExplainer,
)
from app.services.site_selection_queue import (
    RQQueueSettings,
    RQSiteSelectionJobQueue,
    SiteSelectionJobQueue,
)
from app.services.site_selection_poi_provider import (
    ConfiguredPOIProvider,
    build_configured_poi_provider,
)
from app.services.site_selection_land_use_provider import (
    ConfiguredLandUseProvider,
    build_configured_land_use_provider,
)
from app.services.site_selection_service import (
    SiteSelectionRuntime,
    SiteSelectionRuntimeRegistry,
)
from practice.site_selection import (
    AgentRole,
    CollaborationBudget,
    ConstraintLayerSpec,
    ConstraintLayerType,
    DatasetManifest,
    DatasetEvidenceLevel,
    DatasetSource,
    GISMetricScoringRule,
    MissingMetricPolicy,
    POIGroupScoringConfig,
    POIMetric,
    POIMetricScoringRule,
    POIScoringConfig,
    ProjectType,
    ScoreDirection,
    SiteScoringConfig,
    SiteSelectionWorkflowDependencies,
    SpatialConstraintRelation,
    get_project_profile,
    build_region_resolver,
    OpenAIScenarioInterpreter,
    OpenAIStructuredAgentModel,
    RedisAgentMemoryStore,
    RegionCatalogEntry,
    load_rule_pack,
    AgentRoster,
    AgentHarness,
    AgentHarnessConfig,
    MultiAgentReviewRuntime,
    PromptBundle,
    PromptVersionRegistry,
    RoleAgent,
    default_agent_profiles,
)
from practice.site_selection.mcp_server import create_site_selection_mcp_server
from practice.site_selection.mcp_tools import create_site_selection_tool_registry
from practice.site_selection.poi_adapters import (
    FixturePOIAdapter,
    FixturePOIDataset,
    POISourceAdapter,
)
from practice.site_selection.poi_normalizer import POINormalizer, RawPOI
from practice.site_selection.policy_rag import (
    PolicyHybridRetriever,
    chunk_policy_documents,
    load_policy_corpus,
)
from practice.site_selection.spatial import (
    PostGISSpatialQueryEngine,
    StoredPostGISSpatialDatasetGateway,
)
from practice.site_selection.storage import (
    PostgresScenarioMemoryStore,
    RedisSiteSelectionRuntimeStore,
    RedisSupervisorSessionCoordinator,
)
from practice.site_selection.storage.poi_repository import PostgresPOIRepository
from practice.site_selection.storage.postgres import (
    PostgresSpatialRepository,
    ProjectStorageRecord,
    SpatialLayerWrite,
)
from scripts.apply_postgis_migrations import apply_migration


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "data" / "fixtures"


class SiteSelectionBootstrapError(RuntimeError):
    """Raised when an explicitly requested runtime cannot start safely."""


class FixtureProjectSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    project_type: ProjectType
    name: str = Field(min_length=1)


class FixtureFeatureSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_feature_id: str = Field(min_length=1)
    properties: dict[str, Any]
    geometry: dict[str, Any]


class FixtureLayerSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    layer_type: str = Field(min_length=1)
    source_id_field: str = Field(min_length=1)
    required_fields: list[str] = Field(min_length=1)
    features: list[FixtureFeatureSeed] = Field(min_length=1)

    @model_validator(mode="after")
    def feature_ids_match_properties(self) -> FixtureLayerSeed:
        for feature in self.features:
            if str(feature.properties.get(self.source_id_field, "")).strip() != (
                feature.source_feature_id
            ):
                raise ValueError("Fixture 要素编号必须与 source_id_field 一致")
        return self


class FixtureSpatialSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_fixture: bool
    version: str = Field(min_length=1)
    updated_at: datetime
    crs: str = Field(min_length=1)
    projects: list[FixtureProjectSeed] = Field(min_length=2)
    layers: list[FixtureLayerSeed] = Field(min_length=4)

    @field_validator("updated_at")
    @classmethod
    def updated_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Fixture 空间数据时间必须包含时区")
        return value

    @model_validator(mode="after")
    def fixture_contract_is_consistent(self) -> FixtureSpatialSeed:
        if not self.is_fixture:
            raise ValueError("演示运行时只接受显式 fixture 空间数据")
        project_ids = {project.project_id for project in self.projects}
        if len(project_ids) != len(self.projects):
            raise ValueError("Fixture 项目编号不能重复")
        layer_ids = {layer.layer_id for layer in self.layers}
        if len(layer_ids) != len(self.layers):
            raise ValueError("Fixture 图层编号不能重复")
        if any(layer.project_id not in project_ids for layer in self.layers):
            raise ValueError("Fixture 图层引用了不存在的项目")
        return self


class _FixtureEmbeddingProvider:
    """Small deterministic embedding used only by the synthetic policy corpus."""

    _terms = ("生态", "轨道", "物流", "人工复核")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [
            [1.0, *(float(text.count(term)) for term in self._terms)]
            for text in texts
        ]


class _EngineSpatialQueryBackend:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def analyze(self, **kwargs):
        with self._engine.connect() as connection:
            return PostGISSpatialQueryEngine(connection).analyze(**kwargs)


class _EnginePOIReader:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def search_nearby(self, **kwargs):
        with self._engine.connect() as connection:
            return PostgresPOIRepository(connection).search_nearby(**kwargs)


@dataclass
class SiteSelectionBootstrap:
    runtime_provider: SiteSelectionRuntimeRegistry
    run_store: RedisSiteSelectionRuntimeStore
    report_store: FileSystemSiteSelectionReportStore
    mcp_server: Any | None
    engine: Engine
    redis_client: Any
    memory_store: PostgresScenarioMemoryStore
    explainer: SiteSelectionEvidenceExplainer | None = None
    job_queue: SiteSelectionJobQueue | None = None
    poi_provider: ConfiguredPOIProvider | None = None
    land_use_provider: ConfiguredLandUseProvider | None = None
    supervisor_checkpointer: Any | None = None
    supervisor_checkpointer_context: Any | None = None
    supervisor_coordinator: RedisSupervisorSessionCoordinator | None = None
    scenario_interpreter: Any | None = None
    region_resolver: Any | None = None
    multi_agent_runtime: MultiAgentReviewRuntime | AgentHarness | None = None
    run_mode: str = "sync"
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.job_queue is not None:
                self.job_queue.close()
        finally:
            try:
                if self.supervisor_checkpointer_context is not None:
                    self.supervisor_checkpointer_context.__exit__(
                        None,
                        None,
                        None,
                    )
            finally:
                try:
                    if self.poi_provider is not None:
                        self.poi_provider.close()
                finally:
                    try:
                        if self.land_use_provider is not None:
                            self.land_use_provider.close()
                    finally:
                        try:
                            close = getattr(self.redis_client, "close", None)
                            if callable(close):
                                close()
                        finally:
                            self.engine.dispose()


def load_fixture_spatial_seed(
    path: str | Path = FIXTURE_ROOT / "spatial_layers.json",
) -> FixtureSpatialSeed:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return FixtureSpatialSeed.model_validate(payload)


def seed_fixture_storage(
    connection: Any,
    spatial_seed: FixtureSpatialSeed,
    poi_dataset: FixturePOIDataset,
) -> None:
    spatial_repository = PostgresSpatialRepository(connection)
    projects = {project.project_id: project for project in spatial_seed.projects}
    for project in spatial_seed.projects:
        spatial_repository.upsert_project(
            ProjectStorageRecord(
                project_id=project.project_id,
                project_type=project.project_type,
                name=project.name,
                created_at=spatial_seed.updated_at,
                updated_at=spatial_seed.updated_at,
            )
        )

    for layer in spatial_seed.layers:
        frame = gpd.GeoDataFrame(
            [feature.properties for feature in layer.features],
            geometry=[shape(feature.geometry) for feature in layer.features],
            crs=spatial_seed.crs,
        )
        spatial_repository.replace_layer(
            SpatialLayerWrite(
                layer_id=layer.layer_id,
                project_id=layer.project_id,
                name=layer.name,
                layer_type=layer.layer_type,
                source=DatasetSource.FILE,
                version=spatial_seed.version,
                required_fields=layer.required_fields,
                updated_at=spatial_seed.updated_at,
                metadata={
                    "is_fixture": True,
                    "project_type": projects[layer.project_id].project_type.value,
                },
            ),
            frame,
            source_id_field=layer.source_id_field,
        )

    normalizer = POINormalizer()
    normalized = normalizer.normalize_many(
        RawPOI(
            source="fixture",
            source_id=record.poi_id,
            name=record.name,
            category=record.category,
            longitude=record.longitude,
            latitude=record.latitude,
            source_crs="EPSG:4326",
            fetched_at=poi_dataset.updated_at,
            raw_payload={
                "fixture_dataset_id": poi_dataset.dataset_id,
                "fixture_version": poi_dataset.version,
                **record.attributes,
            },
        )
        for record in poi_dataset.records
    )
    PostgresPOIRepository(connection).upsert_many(normalized)


def build_fixture_runtime_registry(
    engine: Engine,
    *,
    fixture_root: str | Path = FIXTURE_ROOT,
    spatial_gateway: Any | None = None,
    poi_adapter: POISourceAdapter | None = None,
    authoritative_land_manifest: DatasetManifest | None = None,
    multi_agent_runtime: MultiAgentReviewRuntime | AgentHarness | None = None,
) -> SiteSelectionRuntimeRegistry:
    root = Path(fixture_root)
    spatial_seed = load_fixture_spatial_seed(root / "spatial_layers.json")
    active_poi_adapter = poi_adapter or FixturePOIAdapter.from_json(
        root / "poi.json"
    )
    gateway = spatial_gateway or StoredPostGISSpatialDatasetGateway(engine)
    layer_by_id = {layer.layer_id: layer for layer in spatial_seed.layers}

    runtimes = {
        ProjectType.SHOPPING_MALL: _build_fixture_runtime(
            ProjectType.SHOPPING_MALL,
            candidate_layer=layer_by_id["demo-mall-candidates"],
            constraint_layer=layer_by_id["demo-mall-constraints"],
            constraint_id="ecology-observation",
            constraint_type=ConstraintLayerType.ECOLOGICAL_PROTECTION,
            rule_path=root / "rules.shopping_mall.yaml",
            gateway=gateway,
            poi_adapter=active_poi_adapter,
            spatial_seed=spatial_seed,
            multi_agent_runtime=multi_agent_runtime,
        ),
        ProjectType.LOGISTICS_PARK: _build_fixture_runtime(
            ProjectType.LOGISTICS_PARK,
            candidate_layer=layer_by_id["demo-logistics-candidates"],
            constraint_layer=layer_by_id["demo-logistics-constraints"],
            constraint_id="sensitive-receptor-observation",
            constraint_type=ConstraintLayerType.SENSITIVE_RECEPTOR,
            rule_path=root / "rules.logistics_park.yaml",
            gateway=gateway,
            poi_adapter=active_poi_adapter,
            spatial_seed=spatial_seed,
            multi_agent_runtime=multi_agent_runtime,
        ),
        ProjectType.COFFEE_SHOP: _build_fixture_runtime(
            ProjectType.COFFEE_SHOP,
            candidate_layer=layer_by_id["demo-coffee-candidates"],
            constraint_layer=layer_by_id["demo-coffee-constraints"],
            constraint_id="retail-land-use-observation",
            constraint_type=ConstraintLayerType.LAND_USE,
            rule_path=root / "rules.coffee_shop.yaml",
            gateway=gateway,
            poi_adapter=active_poi_adapter,
            spatial_seed=spatial_seed,
            discovery_layer=(
                None
                if authoritative_land_manifest is not None
                else layer_by_id["demo-coffee-discovery-pool"]
            ),
            discovery_manifest=authoritative_land_manifest,
            multi_agent_runtime=multi_agent_runtime,
        ),
        ProjectType.CONVENIENCE_STORE: _build_fixture_runtime(
            ProjectType.CONVENIENCE_STORE,
            candidate_layer=layer_by_id["demo-convenience-candidates"],
            constraint_layer=layer_by_id["demo-convenience-constraints"],
            constraint_id="retail-land-use-observation",
            constraint_type=ConstraintLayerType.LAND_USE,
            rule_path=root / "rules.convenience_store.yaml",
            gateway=gateway,
            poi_adapter=active_poi_adapter,
            spatial_seed=spatial_seed,
            discovery_layer=(
                None
                if authoritative_land_manifest is not None
                else layer_by_id["demo-convenience-discovery-pool"]
            ),
            discovery_manifest=authoritative_land_manifest,
            multi_agent_runtime=multi_agent_runtime,
        ),
    }
    return SiteSelectionRuntimeRegistry(runtimes)


def build_fixture_mcp_server(
    engine: Engine,
    *,
    fixture_root: str | Path = FIXTURE_ROOT,
):
    root = Path(fixture_root)
    corpus = load_policy_corpus(root / "policies.json")
    retriever = PolicyHybridRetriever(
        chunk_policy_documents(corpus.documents),
        _FixtureEmbeddingProvider(),
    )
    registry = create_site_selection_tool_registry(
        _EngineSpatialQueryBackend(engine),
        _EnginePOIReader(engine),
        policy_retriever=retriever,
    )
    return create_site_selection_mcp_server(registry)


def build_site_selection_bootstrap_from_environment(
    environ: Mapping[str, str] | None = None,
    *,
    engine_factory: Callable[..., Engine] = create_engine,
    redis_factory: Callable[..., Any] | None = None,
    job_queue_factory: Callable[
        [str, RQQueueSettings], SiteSelectionJobQueue
    ] = RQSiteSelectionJobQueue.from_url,
    migration_applier: Callable[[Engine], None] = apply_migration,
    fixture_root: str | Path = FIXTURE_ROOT,
    include_mcp: bool = True,
    supervisor_checkpointer_factory: Callable[
        [str], tuple[Any, Any]
    ] | None = None,
) -> SiteSelectionBootstrap | None:
    values = os.environ if environ is None else environ
    mode = values.get("SITE_SELECTION_RUNTIME_MODE", "").strip().lower()
    if not mode:
        return None
    if mode != "fixture":
        raise SiteSelectionBootstrapError(
            f"不支持的 SITE_SELECTION_RUNTIME_MODE：{mode}"
        )

    run_mode = values.get("SITE_SELECTION_RUN_MODE", "sync").strip().lower()
    if run_mode not in {"sync", "async"}:
        raise SiteSelectionBootstrapError(
            "SITE_SELECTION_RUN_MODE 只能是 sync 或 async"
        )

    database_url = _required_environment(values, "DATABASE_URL")
    redis_url = _required_environment(values, "REDIS_URL")
    report_dir = _required_environment(values, "SITE_SELECTION_REPORT_DIR")
    runtime_namespace = values.get(
        "SITE_SELECTION_REDIS_NAMESPACE",
        "site_selection:fixture",
    )
    run_ttl_seconds = _positive_int_environment(
        values,
        "SITE_SELECTION_RUN_TTL_SECONDS",
        86_400,
    )
    idempotency_ttl_seconds = _positive_int_environment(
        values,
        "SITE_SELECTION_IDEMPOTENCY_TTL_SECONDS",
        86_400,
    )
    poi_cache_ttl_seconds = _positive_int_environment(
        values,
        "SITE_SELECTION_POI_CACHE_TTL_SECONDS",
        21_600,
    )
    land_use_cache_ttl_seconds = _positive_int_environment(
        values,
        "SITE_SELECTION_LAND_USE_CACHE_TTL_SECONDS",
        3_600,
    )
    discovery_snapshot_ttl_seconds = _positive_int_environment(
        values,
        "SITE_SELECTION_DISCOVERY_SNAPSHOT_TTL_SECONDS",
        7_200,
    )
    event_ttl_seconds = _positive_int_environment(
        values,
        "SITE_SELECTION_EVENT_TTL_SECONDS",
        86_400,
    )
    scenario_session_ttl_seconds = _positive_int_environment(
        values,
        "SITE_SELECTION_SCENARIO_SESSION_TTL_SECONDS",
        86_400,
    )
    supervisor_enabled = _boolean_environment(
        values,
        "SITE_SELECTION_SUPERVISOR_ENABLED",
        False,
    )
    supervisor_session_ttl_seconds = _positive_int_environment(
        values,
        "SITE_SELECTION_SUPERVISOR_SESSION_TTL_SECONDS",
        7_200,
    )
    supervisor_lock_ttl_seconds = _positive_int_environment(
        values,
        "SITE_SELECTION_SUPERVISOR_LOCK_TTL_SECONDS",
        120,
    )
    if redis_factory is None:
        from redis import Redis

        redis_factory = Redis.from_url

    engine = engine_factory(
        database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    redis_client = None
    job_queue = None
    configured_poi_provider = None
    configured_land_use_provider = None
    supervisor_checkpointer = None
    supervisor_checkpointer_context = None
    multi_agent_runtime = None
    try:
        migration_applier(engine)
        root = Path(fixture_root)
        spatial_seed = load_fixture_spatial_seed(root / "spatial_layers.json")
        poi_dataset = FixturePOIDataset.model_validate_json(
            (root / "poi.json").read_text(encoding="utf-8")
        )
        with engine.begin() as connection:
            seed_fixture_storage(connection, spatial_seed, poi_dataset)

        redis_client = redis_factory(redis_url, decode_responses=True)
        redis_client.ping()
        multi_agent_runtime = _build_optional_multi_agent_runtime(
            values,
            redis_client,
            runtime_namespace=runtime_namespace,
        )
        run_store = RedisSiteSelectionRuntimeStore(
            redis_client,
            namespace=runtime_namespace,
            run_ttl_seconds=run_ttl_seconds,
            idempotency_ttl_seconds=idempotency_ttl_seconds,
            poi_cache_ttl_seconds=poi_cache_ttl_seconds,
            land_use_cache_ttl_seconds=land_use_cache_ttl_seconds,
            discovery_snapshot_ttl_seconds=(
                discovery_snapshot_ttl_seconds
            ),
            event_ttl_seconds=event_ttl_seconds,
            scenario_session_ttl_seconds=scenario_session_ttl_seconds,
        )
        supervisor_coordinator = None
        if supervisor_enabled:
            factory = (
                supervisor_checkpointer_factory
                or open_postgres_supervisor_checkpointer
            )
            (
                supervisor_checkpointer,
                supervisor_checkpointer_context,
            ) = factory(database_url)
            supervisor_coordinator = RedisSupervisorSessionCoordinator(
                redis_client,
                namespace=runtime_namespace,
                session_ttl_seconds=supervisor_session_ttl_seconds,
                lock_ttl_seconds=supervisor_lock_ttl_seconds,
            )
        configured_poi_provider = build_configured_poi_provider(
            values,
            FixturePOIAdapter.from_json(root / "poi.json"),
            cache_store=run_store,
            engine=engine,
        )
        configured_land_use_provider = build_configured_land_use_provider(
            values,
            cache_store=run_store,
        )
        authoritative_land_manifest = (
            _configured_authoritative_land_manifest(engine, values)
        )
        region_payload = json.loads(
            (root / "regions.json").read_text(encoding="utf-8")
        )
        region_resolver = build_region_resolver(
            values,
            [
                RegionCatalogEntry.model_validate(item)
                for item in region_payload["entries"]
            ],
        )
        if run_mode == "async":
            queue_settings = RQQueueSettings(
                queue_name=values.get(
                    "SITE_SELECTION_QUEUE_NAME",
                    "site-selection",
                ),
                job_timeout_seconds=_positive_int_environment(
                    values,
                    "SITE_SELECTION_JOB_TIMEOUT_SECONDS",
                    180,
                ),
                result_ttl_seconds=_positive_int_environment(
                    values,
                    "SITE_SELECTION_JOB_RESULT_TTL_SECONDS",
                    3_600,
                ),
                failure_ttl_seconds=_positive_int_environment(
                    values,
                    "SITE_SELECTION_JOB_FAILURE_TTL_SECONDS",
                    86_400,
                ),
                runtime_namespace=runtime_namespace,
                run_ttl_seconds=run_ttl_seconds,
                event_ttl_seconds=event_ttl_seconds,
            )
            job_queue = job_queue_factory(redis_url, queue_settings)
        return SiteSelectionBootstrap(
            runtime_provider=build_fixture_runtime_registry(
                engine,
                fixture_root=root,
                poi_adapter=configured_poi_provider.adapter,
                authoritative_land_manifest=authoritative_land_manifest,
                multi_agent_runtime=multi_agent_runtime,
            ),
            run_store=run_store,
            report_store=FileSystemSiteSelectionReportStore(report_dir),
            mcp_server=(
                build_fixture_mcp_server(engine, fixture_root=root)
                if include_mcp
                else None
            ),
            engine=engine,
            redis_client=redis_client,
            memory_store=PostgresScenarioMemoryStore(engine),
            explainer=_build_optional_explainer(values),
            job_queue=job_queue,
            poi_provider=configured_poi_provider,
            land_use_provider=configured_land_use_provider,
            supervisor_checkpointer=supervisor_checkpointer,
            supervisor_checkpointer_context=supervisor_checkpointer_context,
            supervisor_coordinator=supervisor_coordinator,
            scenario_interpreter=_build_optional_scenario_interpreter(values),
            region_resolver=region_resolver,
            multi_agent_runtime=multi_agent_runtime,
            run_mode=run_mode,
        )
    except Exception as exc:
        if supervisor_checkpointer_context is not None:
            try:
                supervisor_checkpointer_context.__exit__(
                    *sys.exc_info(),
                )
            except Exception:
                pass
        _close_quietly(job_queue)
        _close_quietly(configured_poi_provider)
        _close_quietly(configured_land_use_provider)
        _close_quietly(redis_client)
        try:
            engine.dispose()
        except Exception:
            pass
        raise SiteSelectionBootstrapError(
            "fixture 选址运行时初始化失败："
            f"error_type={type(exc).__name__}"
        ) from exc


def open_postgres_supervisor_checkpointer(database_url: str) -> tuple[Any, Any]:
    """Open and initialize the official durable LangGraph Postgres saver."""

    from langgraph.checkpoint.postgres import PostgresSaver

    connection_string = database_url.replace(
        "postgresql+psycopg://",
        "postgresql://",
        1,
    )
    context = PostgresSaver.from_conn_string(connection_string)
    saver = context.__enter__()
    try:
        saver.setup()
    except Exception:
        context.__exit__(*sys.exc_info())
        raise
    return saver, context


def _build_fixture_runtime(
    project_type: ProjectType,
    *,
    candidate_layer: FixtureLayerSeed,
    constraint_layer: FixtureLayerSeed,
    constraint_id: str,
    constraint_type: ConstraintLayerType,
    rule_path: Path,
    gateway: StoredPostGISSpatialDatasetGateway,
    poi_adapter: POISourceAdapter,
    spatial_seed: FixtureSpatialSeed,
    discovery_layer: FixtureLayerSeed | None = None,
    discovery_manifest: DatasetManifest | None = None,
    multi_agent_runtime: MultiAgentReviewRuntime | AgentHarness | None = None,
) -> SiteSelectionRuntime:
    manifests = [
        _fixture_manifest(candidate_layer, spatial_seed),
        _fixture_manifest(constraint_layer, spatial_seed),
    ]
    if discovery_layer is not None:
        manifests.append(_fixture_manifest(discovery_layer, spatial_seed))
    if discovery_manifest is not None:
        manifests.append(discovery_manifest.model_copy(deep=True))
    rule_pack = load_rule_pack(rule_path)
    return SiteSelectionRuntime(
        project_type=project_type,
        datasets=manifests,
        dependencies=SiteSelectionWorkflowDependencies(
            poi_gateway=poi_adapter,
            poi_scoring_config=_fixture_poi_scoring_config(project_type),
            spatial_gateway=gateway,
            constraint_specs=[
                ConstraintLayerSpec(
                    constraint_id=constraint_id,
                    display_name=constraint_layer.name,
                    layer_type=constraint_type,
                    dataset_id=constraint_layer.layer_id,
                    relation=SpatialConstraintRelation.INTERSECTS,
                    applicable_project_types=[project_type],
                    required_fields=constraint_layer.required_fields,
                )
            ],
            rules=rule_pack.rules,
            buffer_distance_m=500,
            site_scoring_config=_fixture_site_scoring_config(project_type),
            multi_agent_runtime=multi_agent_runtime,
        ),
    )


def _fixture_manifest(
    layer: FixtureLayerSeed,
    seed: FixtureSpatialSeed,
) -> DatasetManifest:
    return DatasetManifest(
        dataset_id=layer.layer_id,
        name=layer.name,
        source=DatasetSource.POSTGIS,
        location=layer.layer_id,
        version=seed.version,
        crs=seed.crs,
        evidence_level=DatasetEvidenceLevel.SYNTHETIC,
        source_uri="data/fixtures/spatial_layers.json",
        license="项目内置合成演示数据",
        required_fields=layer.required_fields,
        updated_at=seed.updated_at,
    )


def _configured_authoritative_land_manifest(
    engine: Engine,
    values: Mapping[str, str],
) -> DatasetManifest | None:
    layer_id = values.get(
        "SITE_SELECTION_AUTHORITATIVE_LAND_LAYER_ID",
        "",
    ).strip()
    if not layer_id:
        return None
    with engine.connect() as connection:
        stored = PostgresSpatialRepository(connection).get_layer(layer_id)
    if stored is None:
        raise ValueError(f"权威用地图层不存在：{layer_id}")
    required = {
        "parcel_id",
        "name",
        "land_use_class",
        "suitability",
        "area_hectares",
    }
    if not required.issubset(stored.required_fields):
        missing = sorted(required - set(stored.required_fields))
        raise ValueError("权威用地图层缺少字段：" + ", ".join(missing))
    if stored.metadata.get("is_fixture") is True:
        raise ValueError("权威用地图层不能标记为 Fixture")
    if stored.metadata.get("evidence_level") != "authoritative":
        raise ValueError("权威用地图层必须显式标记 evidence_level=authoritative")
    analysis_crs = str(stored.metadata.get("analysis_crs", "")).strip()
    if not analysis_crs:
        analysis_crs = stored.source_crs
    crs = CRS.from_user_input(analysis_crs)
    if crs.is_geographic:
        raise ValueError("权威用地图层必须配置米制 analysis_crs")
    source_uri = str(stored.metadata.get("source_uri", "")).strip()
    license_value = str(stored.metadata.get("license", "")).strip()
    if not source_uri or not license_value:
        raise ValueError("权威用地图层必须记录 source_uri 和 license")
    return DatasetManifest(
        dataset_id=stored.layer_id,
        name=stored.name,
        source=DatasetSource.POSTGIS,
        location=stored.layer_id,
        version=stored.version,
        crs=analysis_crs,
        evidence_level=DatasetEvidenceLevel.AUTHORITATIVE,
        source_uri=source_uri,
        license=license_value,
        required_fields=stored.required_fields,
        updated_at=stored.updated_at,
    )


def _fixture_poi_scoring_config(project_type: ProjectType) -> POIScoringConfig:
    profile = get_project_profile(project_type)
    groups = []
    for group in profile.poi_groups:
        metric_weight = 1 / len(group.metrics)
        groups.append(
            POIGroupScoringConfig(
                group_key=group.group_key,
                metric_rules=[
                    POIMetricScoringRule(
                        metric=metric,
                        direction=_fixture_metric_direction(group, metric),
                        lower_bound=0,
                        upper_bound=_fixture_metric_upper_bound(group, metric),
                        weight=metric_weight,
                        missing_policy=MissingMetricPolicy.ZERO,
                    )
                    for metric in group.metrics
                ],
            )
        )
    return POIScoringConfig(
        project_type=project_type,
        version="fixture-poi-score-rich-v1",
        groups=groups,
    )


def _fixture_site_scoring_config(project_type: ProjectType) -> SiteScoringConfig:
    return SiteScoringConfig(
        project_type=project_type,
        version="fixture-site-score-rich-v1",
        gis_weight=0.4,
        poi_weight=0.6,
        gis_metric_rules=[
            GISMetricScoringRule(
                metric_key="area_hectares",
                direction=ScoreDirection.HIGHER_IS_BETTER,
                lower_bound=0,
                upper_bound=_fixture_area_upper_bound(project_type),
                weight=1,
                missing_policy=MissingMetricPolicy.BLOCK,
            )
        ],
    )


def _fixture_metric_upper_bound(group: Any, metric: POIMetric) -> float:
    target_count = 20.0
    if metric is POIMetric.COUNT:
        return target_count
    if metric is POIMetric.DENSITY_PER_SQ_KM:
        radius_km = group.query_radius_m / 1_000
        return target_count / (pi * radius_km * radius_km)
    return float(group.query_radius_m)


def _fixture_metric_direction(group: Any, metric: POIMetric) -> ScoreDirection:
    distance_metrics = {
        POIMetric.NEAREST_DISTANCE_M,
        POIMetric.AVERAGE_DISTANCE_M,
    }
    is_competition = group.group_key == "competitor" or group.group_key.endswith(
        "_competition"
    )
    if is_competition:
        return (
            ScoreDirection.HIGHER_IS_BETTER
            if metric in distance_metrics
            else ScoreDirection.LOWER_IS_BETTER
        )
    return (
        ScoreDirection.LOWER_IS_BETTER
        if metric in distance_metrics
        else ScoreDirection.HIGHER_IS_BETTER
    )


def _fixture_area_upper_bound(project_type: ProjectType) -> float:
    return {
        ProjectType.SHOPPING_MALL: 2.0,
        ProjectType.LOGISTICS_PARK: 5.0,
        ProjectType.COFFEE_SHOP: 0.18,
        ProjectType.CONVENIENCE_STORE: 0.12,
    }[project_type]


def _required_environment(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise SiteSelectionBootstrapError(f"缺少环境变量：{name}")
    return value


def _positive_int_environment(
    values: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw_value = values.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise SiteSelectionBootstrapError(
            f"环境变量 {name} 必须是正整数"
        ) from exc
    if value <= 0:
        raise SiteSelectionBootstrapError(
            f"环境变量 {name} 必须是正整数"
        )
    return value


def _boolean_environment(
    values: Mapping[str, str],
    name: str,
    default: bool,
) -> bool:
    raw_value = values.get(name, str(default)).strip().lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise SiteSelectionBootstrapError(
        f"环境变量 {name} 必须是 true 或 false"
    )


def _positive_float_environment(
    values: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    raw_value = values.get(name, str(default)).strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise SiteSelectionBootstrapError(
            f"环境变量 {name} 必须是正数"
        ) from exc
    if value <= 0:
        raise SiteSelectionBootstrapError(
            f"环境变量 {name} 必须是正数"
        )
    return value


def _non_negative_int_environment(
    values: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw_value = values.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise SiteSelectionBootstrapError(
            f"环境变量 {name} 必须是非负整数"
        ) from exc
    if value < 0:
        raise SiteSelectionBootstrapError(
            f"环境变量 {name} 必须是非负整数"
        )
    return value


def _close_quietly(resource: Any | None) -> None:
    if resource is None:
        return
    close = getattr(resource, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        pass


def _build_optional_multi_agent_runtime(
    values: Mapping[str, str],
    redis_client: Any,
    *,
    runtime_namespace: str,
    client_factory: Callable[..., Any] | None = None,
) -> AgentHarness | None:
    if not _boolean_environment(
        values,
        "SITE_SELECTION_MULTI_AGENT_ENABLED",
        False,
    ):
        return None
    names = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")
    configured = {name: values.get(name, "").strip() for name in names}
    missing = [name for name, value in configured.items() if not value]
    if missing:
        raise SiteSelectionBootstrapError(
            "多 Agent 配置不完整：" + ", ".join(missing)
        )
    if client_factory is None:
        from openai import OpenAI

        client_factory = OpenAI
    client = client_factory(
        api_key=configured["LLM_API_KEY"],
        base_url=configured["LLM_BASE_URL"],
        timeout=_positive_float_environment(
            values,
            "SITE_SELECTION_MULTI_AGENT_TIMEOUT_SECONDS",
            15,
        ),
        max_retries=_non_negative_int_environment(
            values,
            "SITE_SELECTION_MULTI_AGENT_MAX_RETRIES",
            0,
        ),
    )
    role_model_variables = {
        AgentRole.SUPERVISOR: "SITE_SELECTION_SUPERVISOR_MODEL",
        AgentRole.POI: "SITE_SELECTION_POI_AGENT_MODEL",
        AgentRole.SPATIAL: "SITE_SELECTION_SPATIAL_AGENT_MODEL",
        AgentRole.POLICY: "SITE_SELECTION_POLICY_AGENT_MODEL",
        AgentRole.REVIEW: "SITE_SELECTION_REVIEW_AGENT_MODEL",
    }
    profiles = default_agent_profiles(
        configured["LLM_MODEL"],
        model_overrides={
            role: values.get(name, "").strip() or configured["LLM_MODEL"]
            for role, name in role_model_variables.items()
        },
    )
    memory_ttl_seconds = _positive_int_environment(
        values,
        "SITE_SELECTION_AGENT_MEMORY_TTL_SECONDS",
        2_592_000,
    )
    models = {
        role: OpenAIStructuredAgentModel(client) for role in profiles
    }
    memory_stores = {
        role: RedisAgentMemoryStore(
            redis_client,
            namespace=f"{runtime_namespace}:agent-memory",
            ttl_seconds=memory_ttl_seconds,
        )
        for role in profiles
    }
    budget = CollaborationBudget(
            max_delegations=_positive_int_environment(
                values,
                "SITE_SELECTION_MULTI_AGENT_MAX_DELEGATIONS",
                6,
            ),
            max_reflection_rounds=_non_negative_int_environment(
                values,
                "SITE_SELECTION_MULTI_AGENT_MAX_REFLECTION_ROUNDS",
                2,
            ),
            max_llm_calls=_positive_int_environment(
                values,
                "SITE_SELECTION_MULTI_AGENT_MAX_LLM_CALLS",
                12,
            ),
        )
    bundle = PromptBundle(
        version=(
            values.get(
                "SITE_SELECTION_AGENT_PROMPT_VERSION",
                "multi-agent-prompts-v1",
            ).strip()
            or "multi-agent-prompts-v1"
        ),
        change_summary="Configured production multi-Agent prompts",
        created_at=datetime.now(UTC),
        profiles=profiles,
    )

    def runtime_factory(active_bundle: PromptBundle) -> MultiAgentReviewRuntime:
        roster = AgentRoster(
            agents={
                role: RoleAgent(
                    profile=profile,
                    model=models[role],
                    memory_store=memory_stores[role],
                )
                for role, profile in active_bundle.profiles.items()
            }
        )
        return MultiAgentReviewRuntime(roster, budget=budget)

    return AgentHarness(
        PromptVersionRegistry(bundle),
        runtime_factory,
        config=AgentHarnessConfig(
            harness_version=(
                values.get(
                    "SITE_SELECTION_AGENT_HARNESS_VERSION",
                    "site-selection-harness-v1",
                ).strip()
                or "site-selection-harness-v1"
            ),
            max_context_characters=_positive_int_environment(
                values,
                "SITE_SELECTION_AGENT_MAX_CONTEXT_CHARACTERS",
                120_000,
            ),
            max_evidence_references=_positive_int_environment(
                values,
                "SITE_SELECTION_AGENT_MAX_EVIDENCE_REFERENCES",
                2_000,
            ),
        ),
    )


def _build_optional_explainer(
    values: Mapping[str, str],
    *,
    client_factory: Callable[..., Any] | None = None,
) -> SiteSelectionEvidenceExplainer | None:
    names = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")
    configured = {name: values.get(name, "").strip() for name in names}
    if not any(configured.values()):
        return None
    missing = [name for name, value in configured.items() if not value]
    if missing:
        raise SiteSelectionBootstrapError(
            "LLM 解释配置不完整：" + ", ".join(missing)
        )
    if client_factory is None:
        from openai import OpenAI

        client_factory = OpenAI

    client = client_factory(
        api_key=configured["LLM_API_KEY"],
        base_url=configured["LLM_BASE_URL"],
        timeout=_positive_float_environment(
            values,
            "SITE_SELECTION_EXPLANATION_TIMEOUT_SECONDS",
            15,
        ),
        max_retries=_non_negative_int_environment(
            values,
            "SITE_SELECTION_EXPLANATION_MAX_RETRIES",
            0,
        ),
    )
    return OpenAISiteSelectionEvidenceExplainer(
        client,
        configured["LLM_MODEL"],
    )


def _build_optional_scenario_interpreter(
    values: Mapping[str, str],
    *,
    client_factory: Callable[..., Any] | None = None,
):
    if not _boolean_environment(
        values,
        "SITE_SELECTION_CONVERSATION_LLM_ENABLED",
        False,
    ):
        return None
    names = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")
    configured = {name: values.get(name, "").strip() for name in names}
    missing = [name for name, value in configured.items() if not value]
    if missing:
        raise SiteSelectionBootstrapError(
            "LLM 对话解析配置不完整：" + ", ".join(missing)
        )
    if client_factory is None:
        from openai import OpenAI

        client_factory = OpenAI
    client = client_factory(
        api_key=configured["LLM_API_KEY"],
        base_url=configured["LLM_BASE_URL"],
        timeout=_positive_float_environment(
            values,
            "SITE_SELECTION_CONVERSATION_TIMEOUT_SECONDS",
            12,
        ),
        max_retries=_non_negative_int_environment(
            values,
            "SITE_SELECTION_CONVERSATION_MAX_RETRIES",
            0,
        ),
    )
    return OpenAIScenarioInterpreter(client, configured["LLM_MODEL"])
