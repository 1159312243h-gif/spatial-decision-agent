from __future__ import annotations

from collections.abc import Mapping

from .domain import ProjectRequest, ProjectType
from .evidence import AgentState, AnalysisStatus
from .poi import POIQuery
from .profiles import PROJECT_PROFILES, ProjectProfile


class UnsupportedProjectTypeError(ValueError):
    """Raised when no project profile is registered for a project type."""


class ProfileRegistry:
    """Read-only lookup boundary for validated project profiles."""

    def __init__(
        self,
        profiles: Mapping[ProjectType, ProjectProfile] | None = None,
    ) -> None:
        source = PROJECT_PROFILES if profiles is None else profiles
        if not source:
            raise ValueError("ProfileRegistry 至少需要一个项目 Profile")

        self._profiles: dict[ProjectType, ProjectProfile] = {}
        for project_type, profile in source.items():
            if project_type != profile.project_type:
                raise ValueError("Profile 注册键必须与 Profile 项目类型一致")
            self._profiles[project_type] = profile.model_copy(deep=True)

    @property
    def supported_types(self) -> tuple[ProjectType, ...]:
        return tuple(self._profiles)

    def get(self, project_type: ProjectType | str) -> ProjectProfile:
        try:
            normalized_type = ProjectType(project_type)
            profile = self._profiles[normalized_type]
        except (TypeError, ValueError, KeyError) as exc:
            raise UnsupportedProjectTypeError(
                f"不支持的项目类型：{project_type}"
            ) from exc
        return profile.model_copy(deep=True)


class ProjectTypeRouter:
    """Route a validated request to its project-specific profile."""

    def __init__(self, registry: ProfileRegistry | None = None) -> None:
        self._registry = registry or ProfileRegistry()

    def route(self, request: ProjectRequest) -> ProjectProfile:
        return self._registry.get(request.project_type)


def build_poi_queries(
    request: ProjectRequest,
    profile: ProjectProfile,
    *,
    limit: int = 100,
) -> list[POIQuery]:
    """Derive deterministic POI queries for every parcel and profile group."""

    if request.project_type != profile.project_type:
        raise ValueError("项目请求类型必须与 ProjectProfile 类型一致")

    return [
        POIQuery(
            query_id=(
                f"{request.request_id}:{parcel.parcel_id}:{group.group_key}"
            ),
            parcel_id=parcel.parcel_id,
            group_key=group.group_key,
            longitude=parcel.longitude,
            latitude=parcel.latitude,
            categories=list(group.categories),
            radius_m=group.query_radius_m,
            limit=limit,
        )
        for parcel in request.candidate_parcels
        for group in profile.poi_groups
    ]


class ProjectIntakeSkill:
    """Create the first business state without calling GIS, POI, or an LLM."""

    def __init__(self, router: ProjectTypeRouter | None = None) -> None:
        self._router = router or ProjectTypeRouter()

    def run(self, request: ProjectRequest) -> AgentState:
        profile = self._router.route(request)
        queries = build_poi_queries(request, profile)
        return AgentState(
            request=request,
            profile=profile,
            poi_queries=queries,
            status=AnalysisStatus.DATA_PENDING,
        )
