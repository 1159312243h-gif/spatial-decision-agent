"""Typed contracts for the site-selection analysis workflow."""

from .constraints import (
    ConstraintLayerSpec,
    ConstraintLayerType,
    ConstraintObservation,
    SpatialConstraintRelation,
)
from .domain import (
    CandidateParcel,
    DatasetManifest,
    DatasetSource,
    ProjectRequest,
    ProjectType,
)
from .evidence import (
    AgentState,
    AnalysisResult,
    AnalysisStatus,
    EvidenceStatus,
    GISEvidence,
    POIEvidence,
    PolicyEvidence,
)
from .intake import (
    ProfileRegistry,
    ProjectIntakeSkill,
    ProjectTypeRouter,
    UnsupportedProjectTypeError,
    build_poi_queries,
)
from .poi import (
    POIFeatureSet,
    POIMetric,
    POIProvider,
    POIQuery,
    POIRecord,
    POISourceMeta,
)
from .poi_service import (
    MockPOIGateway,
    POIGateway,
    calculate_poi_metrics,
    execute_poi_queries,
)
from .profiles import (
    PROJECT_PROFILES,
    POICategoryConfig,
    ProjectProfile,
    get_project_profile,
)
from .rule_engine import (
    RuleConfigurationError,
    RuleEvaluationBlockedError,
    evaluate_policy_rules,
)
from .rules import (
    PolicyFinding,
    PolicyReference,
    RuleDefinition,
    RuleOutcome,
)

__all__ = [
    "AgentState",
    "AnalysisResult",
    "AnalysisStatus",
    "CandidateParcel",
    "ConstraintLayerSpec",
    "ConstraintLayerType",
    "ConstraintObservation",
    "DatasetManifest",
    "DatasetSource",
    "EvidenceStatus",
    "GISEvidence",
    "MockPOIGateway",
    "POICategoryConfig",
    "POIEvidence",
    "POIFeatureSet",
    "POIGateway",
    "POIMetric",
    "POIProvider",
    "POIQuery",
    "POIRecord",
    "POISourceMeta",
    "PROJECT_PROFILES",
    "PolicyEvidence",
    "PolicyFinding",
    "PolicyReference",
    "ProfileRegistry",
    "ProjectIntakeSkill",
    "ProjectProfile",
    "ProjectRequest",
    "ProjectType",
    "ProjectTypeRouter",
    "RuleConfigurationError",
    "RuleDefinition",
    "RuleEvaluationBlockedError",
    "RuleOutcome",
    "SpatialConstraintRelation",
    "UnsupportedProjectTypeError",
    "build_poi_queries",
    "calculate_poi_metrics",
    "evaluate_policy_rules",
    "execute_poi_queries",
    "get_project_profile",
]
