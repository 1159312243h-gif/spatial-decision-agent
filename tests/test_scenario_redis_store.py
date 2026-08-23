from datetime import datetime, timezone

from practice.site_selection import ScenarioConversationSession
from practice.site_selection.storage import RedisSiteSelectionRuntimeStore
from tests.storage_fakes import FakeRedis


def test_redis_round_trips_scenario_session_with_ttl() -> None:
    redis = FakeRedis()
    store = RedisSiteSelectionRuntimeStore(
        redis,
        scenario_session_ttl_seconds=12_345,
    )
    session = ScenarioConversationSession(
        session_id="conversation-001",
        scenario_id="scenario-001",
        created_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
    )

    store.save_scenario_session(session)

    assert store.get_scenario_session(session.session_id) == session
    assert store.scenario_session_ttl(session.session_id) == 12_345
