"""Typed contracts for the site-selection analysis workflow."""

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

__all__ = [
    "AgentState",
    "AnalysisResult",
    "AnalysisStatus",
    "CandidateParcel",
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
    "ProfileRegistry",
    "ProjectIntakeSkill",
    "ProjectProfile",
    "ProjectRequest",
    "ProjectType",
    "ProjectTypeRouter",
    "UnsupportedProjectTypeError",
    "build_poi_queries",
    "calculate_poi_metrics",
    "execute_poi_queries",
    "get_project_profile",
]
