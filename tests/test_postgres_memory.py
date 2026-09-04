from contextlib import contextmanager
from datetime import datetime, timezone

from practice.site_selection import (
    CandidateDiscoveryFallbackMode,
    ProjectType,
    ScenarioPreferenceProfile,
)
from practice.site_selection.storage import PostgresScenarioMemoryStore
from tests.storage_fakes import FakeConnection, FakeResult


NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    @contextmanager
    def begin(self):
        yield self.connection


def preference() -> ScenarioPreferenceProfile:
    return ScenarioPreferenceProfile(
        actor_id="planner-001",
        project_type=ProjectType.CONVENIENCE_STORE,
        discovery_radius_km=3,
        max_candidates=10,
        minimum_separation_m=900,
        fallback_mode=CandidateDiscoveryFallbackMode.MARKET_EXPLORATION,
        source_session_id="conversation-001",
        source_version_id="scenario-version-001",
        created_at=NOW,
        updated_at=NOW,
    )


def test_preference_upsert_uses_bound_parameters() -> None:
    connection = FakeConnection()
    store = PostgresScenarioMemoryStore(FakeEngine(connection))

    store.save_preference(preference())

    sql, parameters = connection.calls[0]
    assert ":actor_id" in sql
    assert "planner-001" not in sql
    assert parameters["actor_id"] == "planner-001"
    assert parameters["project_type"] == "convenience_store"


def test_preference_can_be_read_by_actor_and_project_type() -> None:
    expected = preference()
    connection = FakeConnection([FakeResult([expected.model_dump(mode="json")])])
    store = PostgresScenarioMemoryStore(FakeEngine(connection))

    result = store.get_preference("planner-001", ProjectType.CONVENIENCE_STORE)

    assert result == expected
    assert connection.calls[0][1] == {
        "actor_id": "planner-001",
        "project_type": "convenience_store",
    }
