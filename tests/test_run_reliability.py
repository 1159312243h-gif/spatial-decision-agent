from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from practice.site_selection import (
    EvidenceReviewIssue,
    EvidenceReviewReport,
    EvidenceReviewStatus,
    HumanReviewState,
    HumanReviewStatus,
    ReviewIssueSeverity,
    RunStageStatus,
    RunStageTrace,
    build_human_review_state,
)


NOW = datetime(2026, 8, 25, 13, 0, tzinfo=timezone.utc)


def test_warning_creates_pending_human_review_without_approval_semantics() -> None:
    report = EvidenceReviewReport(
        request_id="request-001",
        review_version="review-v1",
        status=EvidenceReviewStatus.READY,
        requires_human_review=True,
        issues=[
            EvidenceReviewIssue(
                issue_code="poi_fixture_fallback",
                severity=ReviewIssueSeverity.WARNING,
                message="Fixture fallback was used.",
            )
        ],
    )

    review = build_human_review_state(report, updated_at=NOW)

    assert review.status is HumanReviewStatus.PENDING
    assert review.reason_codes == ["poi_fixture_fallback"]
    assert review.note is None


def test_not_required_review_rejects_note_and_reasons() -> None:
    with pytest.raises(ValidationError, match="not_required"):
        HumanReviewState(
            status=HumanReviewStatus.NOT_REQUIRED,
            reason_codes=["unexpected"],
            updated_at=NOW,
            note="must not exist",
        )


def test_failed_trace_requires_sanitized_error_type() -> None:
    with pytest.raises(ValidationError, match="failed trace"):
        RunStageTrace(
            stage="workflow",
            status=RunStageStatus.FAILED,
            elapsed_ms=1.25,
        )


def test_review_contract_rejects_inconsistent_human_review_flag() -> None:
    with pytest.raises(ValidationError, match="human review requirement"):
        EvidenceReviewReport(
            request_id="request-001",
            review_version="review-v1",
            status=EvidenceReviewStatus.READY,
            requires_human_review=True,
            issues=[],
        )


def test_blocked_evidence_cannot_be_downgraded_to_acknowledgement() -> None:
    report = EvidenceReviewReport(
        request_id="request-001",
        review_version="review-v1",
        status=EvidenceReviewStatus.BLOCKED,
        requires_human_review=False,
        issues=[
            EvidenceReviewIssue(
                issue_code="gis_lineage_incomplete",
                severity=ReviewIssueSeverity.BLOCKER,
                message="Required GIS lineage is incomplete.",
            )
        ],
    )

    with pytest.raises(ValueError, match="blocked evidence review"):
        build_human_review_state(report, updated_at=NOW)
