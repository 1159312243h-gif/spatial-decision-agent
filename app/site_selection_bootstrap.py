from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from shapely.geometry import shape
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.services.site_selection_artifacts import FileSystemSiteSelectionReportStore
from app.services.site_selection_explanation import (
    OpenAISiteSelectionEvidenceExplainer,
    SiteSelectionEvidenceExplainer,
)
from app.services.site_selection_service import (
    SiteSelectionRuntime,
    SiteSelectionRuntimeRegistry,
)
from practice.site_selection import (
    ConstraintLayerSpec,
    ConstraintLayerType,
    DatasetManifest,
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
    load_rule_pack,
)
from practice.site_selection.mcp_server import create_site_selection_mcp_server
from practice.site_selection.mcp_tools import create_site_selection_tool_registry
from practice.site_selection.poi_adapters import FixturePOIAdapter, FixturePOIDataset
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
from practice.site_selection.storage import RedisSiteSelectionRuntimeStore
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


@dataclass(frozen=True)
class SiteSelectionBootstrap:
    runtime_provider: SiteSelectionRuntimeRegistry
    run_store: RedisSiteSelectionRuntimeStore
    report_store: FileSystemSiteSelectionReportStore
    mcp_server: Any
    engine: Engine
    redis_client: Any
    explainer: SiteSelectionEvidenceExplainer | None = None

    def close(self) -> None:
        close = getattr(self.redis_client, "close", None)
        if callable(close):
            close()
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
) -> SiteSelectionRuntimeRegistry:
    root = Path(fixture_root)
    spatial_seed = load_fixture_spatial_seed(root / "spatial_layers.json")
    poi_adapter = FixturePOIAdapter.from_json(root / "poi.json")
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
            poi_adapter=poi_adapter,
            spatial_seed=spatial_seed,
        ),
        ProjectType.LOGISTICS_PARK: _build_fixture_runtime(
            ProjectType.LOGISTICS_PARK,
            candidate_layer=layer_by_id["demo-logistics-candidates"],
            constraint_layer=layer_by_id["demo-logistics-constraints"],
            constraint_id="sensitive-receptor-observation",
            constraint_type=ConstraintLayerType.SENSITIVE_RECEPTOR,
            rule_path=root / "rules.logistics_park.yaml",
            gateway=gateway,
            poi_adapter=poi_adapter,
            spatial_seed=spatial_seed,
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
    migration_applier: Callable[[Engine], None] = apply_migration,
    fixture_root: str | Path = FIXTURE_ROOT,
) -> SiteSelectionBootstrap | None:
    values = os.environ if environ is None else environ
    mode = values.get("SITE_SELECTION_RUNTIME_MODE", "").strip().lower()
    if not mode:
        return None
    if mode != "fixture":
        raise SiteSelectionBootstrapError(
            f"不支持的 SITE_SELECTION_RUNTIME_MODE：{mode}"
        )

    database_url = _required_environment(values, "DATABASE_URL")
    redis_url = _required_environment(values, "REDIS_URL")
    report_dir = _required_environment(values, "SITE_SELECTION_REPORT_DIR")
    if redis_factory is None:
        from redis import Redis

        redis_factory = Redis.from_url

    engine = engine_factory(
        database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    redis_client = None
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
        run_store = RedisSiteSelectionRuntimeStore(
            redis_client,
            namespace=values.get(
                "SITE_SELECTION_REDIS_NAMESPACE",
                "site_selection:fixture",
            ),
        )
        return SiteSelectionBootstrap(
            runtime_provider=build_fixture_runtime_registry(
                engine,
                fixture_root=root,
            ),
            run_store=run_store,
            report_store=FileSystemSiteSelectionReportStore(report_dir),
            mcp_server=build_fixture_mcp_server(engine, fixture_root=root),
            engine=engine,
            redis_client=redis_client,
            explainer=_build_optional_explainer(values),
        )
    except Exception as exc:
        if redis_client is not None:
            close = getattr(redis_client, "close", None)
            if callable(close):
                close()
        engine.dispose()
        raise SiteSelectionBootstrapError(
            "fixture 选址运行时初始化失败："
            f"error_type={type(exc).__name__}"
        ) from exc


def _build_fixture_runtime(
    project_type: ProjectType,
    *,
    candidate_layer: FixtureLayerSeed,
    constraint_layer: FixtureLayerSeed,
    constraint_id: str,
    constraint_type: ConstraintLayerType,
    rule_path: Path,
    gateway: StoredPostGISSpatialDatasetGateway,
    poi_adapter: FixturePOIAdapter,
    spatial_seed: FixtureSpatialSeed,
) -> SiteSelectionRuntime:
    manifests = [
        _fixture_manifest(candidate_layer, spatial_seed),
        _fixture_manifest(constraint_layer, spatial_seed),
    ]
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
        required_fields=layer.required_fields,
        updated_at=seed.updated_at,
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
                        direction=(
                            ScoreDirection.LOWER_IS_BETTER
                            if metric
                            in {
                                POIMetric.NEAREST_DISTANCE_M,
                                POIMetric.AVERAGE_DISTANCE_M,
                            }
                            else ScoreDirection.HIGHER_IS_BETTER
                        ),
                        lower_bound=0,
                        upper_bound=(
                            float(group.query_radius_m)
                            if metric
                            in {
                                POIMetric.NEAREST_DISTANCE_M,
                                POIMetric.AVERAGE_DISTANCE_M,
                            }
                            else 10.0
                        ),
                        weight=metric_weight,
                        missing_policy=MissingMetricPolicy.ZERO,
                    )
                    for metric in group.metrics
                ],
            )
        )
    return POIScoringConfig(
        project_type=project_type,
        version="fixture-poi-score-2026.08.24.1",
        groups=groups,
    )


def _fixture_site_scoring_config(project_type: ProjectType) -> SiteScoringConfig:
    return SiteScoringConfig(
        project_type=project_type,
        version="fixture-site-score-2026.08.24.1",
        gis_weight=0.4,
        poi_weight=0.6,
        gis_metric_rules=[
            GISMetricScoringRule(
                metric_key="area_hectares",
                direction=ScoreDirection.HIGHER_IS_BETTER,
                lower_bound=0,
                upper_bound=2,
                weight=1,
                missing_policy=MissingMetricPolicy.BLOCK,
            )
        ],
    )


def _required_environment(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise SiteSelectionBootstrapError(f"缺少环境变量：{name}")
    return value


def _build_optional_explainer(
    values: Mapping[str, str],
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
    from openai import OpenAI

    client = OpenAI(
        api_key=configured["LLM_API_KEY"],
        base_url=configured["LLM_BASE_URL"],
        timeout=60.0,
    )
    return OpenAISiteSelectionEvidenceExplainer(
        client,
        configured["LLM_MODEL"],
    )
