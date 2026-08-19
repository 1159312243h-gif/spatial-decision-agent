from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain import NonEmptyString


class EvidenceReviewStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class ReviewIssueSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


class EvidenceReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_code: NonEmptyString
    severity: ReviewIssueSeverity
    message: NonEmptyString
    parcel_id: NonEmptyString | None = None
    evidence_refs: list[NonEmptyString] = Field(default_factory=list)


class EvidenceReviewReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: NonEmptyString
    review_version: NonEmptyString
    status: EvidenceReviewStatus
    issues: list[EvidenceReviewIssue] = Field(default_factory=list)
    requires_human_review: bool

    @model_validator(mode="after")
    def status_matches_blockers(self) -> EvidenceReviewReport:
        has_blocker = any(
            issue.severity is ReviewIssueSeverity.BLOCKER
            for issue in self.issues
        )
        has_warning = any(
            issue.severity is ReviewIssueSeverity.WARNING
            for issue in self.issues
        )
        if (self.status is EvidenceReviewStatus.BLOCKED) != has_blocker:
            raise ValueError("证据审查状态必须与 blocker 一致")
        if self.requires_human_review != has_warning:
            raise ValueError("human review requirement must match warning issues")
        return self
