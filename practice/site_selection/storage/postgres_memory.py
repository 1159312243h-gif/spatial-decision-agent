from __future__ import annotations

import json
from typing import Any, Protocol

from sqlalchemy import text

from ..domain import ProjectType
from ..memory import (
    ScenarioEpisode,
    ScenarioMemoryDeleteResult,
    ScenarioPreferenceProfile,
)


class TransactionalEngine(Protocol):
    def begin(self) -> Any: ...


class PostgresScenarioMemoryStore:
    """Durable, actor-scoped preferences and confirmed scenario episodes."""

    def __init__(self, engine: TransactionalEngine) -> None:
        if engine is None:
            raise ValueError("场景记忆存储必须配置数据库 Engine")
        self._engine = engine

    def get_preference(
        self,
        actor_id: str,
        project_type: ProjectType,
    ) -> ScenarioPreferenceProfile | None:
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        actor_id, project_type, discovery_radius_km,
                        max_candidates, minimum_separation_m, fallback_mode,
                        source_session_id, source_version_id, created_at, updated_at
                    FROM site_selection.user_site_preferences
                    WHERE actor_id = :actor_id AND project_type = :project_type
                    """
                ),
                {"actor_id": actor_id, "project_type": project_type.value},
            ).mappings().first()
        return ScenarioPreferenceProfile.model_validate(row) if row else None

    def list_preferences(self, actor_id: str) -> list[ScenarioPreferenceProfile]:
        with self._engine.begin() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        actor_id, project_type, discovery_radius_km,
                        max_candidates, minimum_separation_m, fallback_mode,
                        source_session_id, source_version_id, created_at, updated_at
                    FROM site_selection.user_site_preferences
                    WHERE actor_id = :actor_id
                    ORDER BY project_type
                    """
                ),
                {"actor_id": actor_id},
            ).mappings().all()
        return [ScenarioPreferenceProfile.model_validate(row) for row in rows]

    def save_preference(self, preference: ScenarioPreferenceProfile) -> None:
        with self._engine.begin() as connection:
            self._save_preference(connection, preference)

    def _save_preference(
        self,
        connection: Any,
        preference: ScenarioPreferenceProfile,
    ) -> None:
        parameters = preference.model_dump()
        parameters["project_type"] = preference.project_type.value
        parameters["fallback_mode"] = preference.fallback_mode
        connection.execute(
            text(
                """
                INSERT INTO site_selection.user_site_preferences (
                    actor_id, project_type, discovery_radius_km,
                    max_candidates, minimum_separation_m, fallback_mode,
                    source_session_id, source_version_id, created_at, updated_at
                ) VALUES (
                    :actor_id, :project_type, :discovery_radius_km,
                    :max_candidates, :minimum_separation_m, :fallback_mode,
                    :source_session_id, :source_version_id, :created_at, :updated_at
                )
                ON CONFLICT (actor_id, project_type) DO UPDATE SET
                    discovery_radius_km = EXCLUDED.discovery_radius_km,
                    max_candidates = EXCLUDED.max_candidates,
                    minimum_separation_m = EXCLUDED.minimum_separation_m,
                    fallback_mode = EXCLUDED.fallback_mode,
                    source_session_id = EXCLUDED.source_session_id,
                    source_version_id = EXCLUDED.source_version_id,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            parameters,
        )

    def save_episode(self, episode: ScenarioEpisode) -> None:
        with self._engine.begin() as connection:
            self._save_episode(connection, episode)

    def _save_episode(self, connection: Any, episode: ScenarioEpisode) -> None:
        parameters = episode.model_dump(exclude={"scenario"})
        parameters["project_type"] = episode.project_type.value
        parameters["scenario"] = json.dumps(
            episode.scenario,
            ensure_ascii=False,
            sort_keys=True,
        )
        connection.execute(
            text(
                """
                INSERT INTO site_selection.scenario_memory_episodes (
                    episode_id, actor_id, project_type, session_id,
                    scenario_id, version_id, region_text, summary,
                    scenario, confirmed_at, created_at
                ) VALUES (
                    :episode_id, :actor_id, :project_type, :session_id,
                    :scenario_id, :version_id, :region_text, :summary,
                    CAST(:scenario AS jsonb), :confirmed_at, :created_at
                )
                ON CONFLICT (actor_id, version_id) DO NOTHING
                """
            ),
            parameters,
        )

    def save_confirmed_memory(
        self,
        preference: ScenarioPreferenceProfile,
        episode: ScenarioEpisode,
    ) -> None:
        with self._engine.begin() as connection:
            self._save_preference(connection, preference)
            self._save_episode(connection, episode)

    def list_episodes(
        self,
        actor_id: str,
        *,
        project_type: ProjectType | None = None,
        limit: int = 5,
    ) -> list[ScenarioEpisode]:
        if limit <= 0 or limit > 50:
            raise ValueError("情景记忆返回数量必须在 1 到 50 之间")
        filters = "actor_id = :actor_id"
        parameters: dict[str, Any] = {"actor_id": actor_id, "limit": limit}
        if project_type is not None:
            filters += " AND project_type = :project_type"
            parameters["project_type"] = project_type.value
        with self._engine.begin() as connection:
            rows = connection.execute(
                text(
                    f"""
                    SELECT
                        episode_id, actor_id, project_type, session_id,
                        scenario_id, version_id, region_text, summary,
                        scenario, confirmed_at, created_at
                    FROM site_selection.scenario_memory_episodes
                    WHERE {filters}
                    ORDER BY confirmed_at DESC
                    LIMIT :limit
                    """
                ),
                parameters,
            ).mappings().all()
        return [
            ScenarioEpisode.model_validate(_mapping_with_json(row)) for row in rows
        ]

    def delete_actor_memory(self, actor_id: str) -> ScenarioMemoryDeleteResult:
        with self._engine.begin() as connection:
            episodes = connection.execute(
                text(
                    "DELETE FROM site_selection.scenario_memory_episodes "
                    "WHERE actor_id = :actor_id"
                ),
                {"actor_id": actor_id},
            )
            preferences = connection.execute(
                text(
                    "DELETE FROM site_selection.user_site_preferences "
                    "WHERE actor_id = :actor_id"
                ),
                {"actor_id": actor_id},
            )
        return ScenarioMemoryDeleteResult(
            actor_id=actor_id,
            deleted_preferences=max(0, int(preferences.rowcount or 0)),
            deleted_episodes=max(0, int(episodes.rowcount or 0)),
        )


def _mapping_with_json(row: Any) -> dict[str, Any]:
    result = dict(row)
    if isinstance(result.get("scenario"), str):
        result["scenario"] = json.loads(result["scenario"])
    return result
