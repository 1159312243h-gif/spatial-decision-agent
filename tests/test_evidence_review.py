from __future__ import annotations

from practice.site_selection import (
    EvidenceReviewStatus,
    ReviewIssueSeverity,
    run_parallel_site_selection_workflow,
)
from practice.site_selection.evidence_review import review_site_selection_evidence
from tests.test_site_scoring import composite_dependencies
from tests.test_site_selection_workflow import (
    dependencies,
    manifests,
    request,
)


def test_workflow_attaches_ready_evidence_review_report() -> None:
    result = run_parallel_site_selection_workflow(
        request(),
        manifests(),
        composite_dependencies(),
    )

    report = result.evidence_review_report
    assert report is not None
    assert report.status is EvidenceReviewStatus.READY
    assert report.requires_human_review is True
    assert any(
        issue.issue_code == "policy_rule_match"
        and issue.severity is ReviewIssueSeverity.WARNING
        for issue in report.issues
    )
    assert any(
        issue.issue_code == "gis_poi_soft_score"
        for issue in report.issues
    )


def test_review_marks_missing_poi_lineage_as_blocker() -> None:
    result = run_parallel_site_selection_workflow(
        request(),
        manifests(),
        dependencies(),
    )
    data = result.model_dump()
    data["poi_evidence"][0]["feature_sets"] = []
    data["results"][0]["poi_evidence"]["feature_sets"] = []
    data["evidence_review_report"] = None
    incomplete = type(result).model_validate(data)

    reviewed = review_site_selection_evidence(incomplete)

    assert reviewed.evidence_review_report.status is EvidenceReviewStatus.BLOCKED
    assert any(
        issue.issue_code == "poi_lineage_incomplete"
        and issue.severity is ReviewIssueSeverity.BLOCKER
        for issue in reviewed.evidence_review_report.issues
    )


def test_no_rule_match_is_not_reported_as_compliance() -> None:
    from shapely.geometry import Point

    from tests.test_site_selection_workflow import constraint_frame

    result = run_parallel_site_selection_workflow(
        request(),
        manifests(),
        dependencies(constraint=constraint_frame(Point(150, 50))),
    )

    report = result.evidence_review_report
    assert report.status is EvidenceReviewStatus.READY
    assert any(
        issue.issue_code == "no_rule_match_is_not_compliance"
        for issue in report.issues
    )
    assert result.results[0].conclusion is None
