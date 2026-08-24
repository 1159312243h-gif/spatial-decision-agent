from shapely.geometry import Point

from practice.site_selection import (
    AmapPOIAdapter,
    FallbackPOIAdapter,
    FixturePOIAdapter,
    RetryingCircuitBreakerPOIAdapter,
)
from practice.site_selection.storage import RunStatus
from tests.test_online_poi_adapters import (
    FIXTURE_PATH,
    FakeHTTPClient,
    FakeResponse,
    OffsetTransformer,
)
from tests.test_site_selection_run_service import command, runtime, service
from tests.test_site_selection_workflow import (
    constraint_frame,
    dependencies,
    target_frame,
)


def test_normal_run_completes_without_human_review() -> None:
    configured = dependencies(
        constraint=constraint_frame(Point(10_000, 10_000)),
    )
    run_service = service(
        configured_runtime=runtime(configured_dependencies=configured)
    )

    state = run_service.create_run(command())

    assert state.status is RunStatus.COMPLETED
    assert state.details["human_review"]["status"] == "not_required"
    assert state.details["trace"][-1]["status"] == "succeeded"


def test_rule_conflict_completes_with_pending_human_review() -> None:
    state = service().create_run(command())

    assert state.status is RunStatus.COMPLETED
    assert state.details["human_review"]["status"] == "pending"
    assert "policy_rule_match" in state.details["human_review"]["reason_codes"]


def test_missing_required_spatial_field_fails_with_trace() -> None:
    invalid_target = target_frame().drop(columns=["land_use"])
    configured = dependencies(target=invalid_target)
    run_service = service(
        configured_runtime=runtime(configured_dependencies=configured)
    )

    state = run_service.create_run(command())

    assert state.status is RunStatus.FAILED
    assert state.details["trace"][0]["stage"] == "workflow"
    assert state.details["trace"][0]["status"] == "failed"
    assert state.details["trace"][-1]["status"] == "failed"
    assert "human_review" not in state.details


def test_poi_rate_limit_opens_circuit_and_uses_audited_fixture_fallback() -> None:
    client = FakeHTTPClient([FakeResponse(429, {})])
    primary = AmapPOIAdapter(
        "test-api-key",
        client,
        OffsetTransformer(),
    )
    reliable = RetryingCircuitBreakerPOIAdapter(
        primary,
        max_attempts=1,
        failure_threshold=1,
        recovery_timeout_seconds=60,
    )
    gateway = FallbackPOIAdapter(
        reliable,
        FixturePOIAdapter.from_json(FIXTURE_PATH),
    )
    configured = dependencies(active_poi_gateway=gateway)
    run_service = service(
        configured_runtime=runtime(configured_dependencies=configured)
    )

    state = run_service.create_run(command())

    assert state.status is RunStatus.COMPLETED
    feature_sets = state.details["analysis"]["poi_feature_sets"]
    assert len(client.get_calls) == 1
    assert all(item["source"]["provider"] == "mock" for item in feature_sets)
    assert all(item["source"]["fallback_from"] == "amap" for item in feature_sets)
    assert {
        item["source"]["fallback_reason"] for item in feature_sets
    } == {"POIRateLimitError", "POICircuitOpenError"}
    assert "poi_fixture_fallback" in (
        state.details["human_review"]["reason_codes"]
    )
