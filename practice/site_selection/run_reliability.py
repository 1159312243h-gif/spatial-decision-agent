from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain import NonEmptyString
from .review_contracts import (
    EvidenceReviewReport,
    EvidenceReviewStatus,
    ReviewIssueSeverity,
)


class RunStageStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunStageTrace(BaseModel):
    """Sanitized timing for one application-level run stage."""

    model_config = ConfigDict(extra="forbid")

    stage: NonEmptyString
    status: RunStageStatus
    elapsed_ms: float = Field(ge=0)
    error_type: NonEmptyString | None = None

    @model_validator(mode="after")
    def error_matches_status(self) -> RunStageTrace:
        if (self.status is RunStageStatus.FAILED) != (
            self.error_type is not None
        ):
            raise ValueError("failed trace must contain only a sanitized error type")
        return self


class HumanReviewStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"


class HumanReviewState(BaseModel):
    """HITL acknowledgement state; it is never a compliance approval."""

    model_config = ConfigDict(extra="forbid")

    status: HumanReviewStatus
    reason_codes: list[NonEmptyString] = Field(default_factory=list)
    updated_at: datetime
    note: NonEmptyString | None = None

    @model_validator(mode="after")
    def state_is_consistent(self) -> HumanReviewState:
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("human review update time must include a timezone")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("human review reason codes must be unique")
        if self.status is HumanReviewStatus.NOT_REQUIRED:
            if self.reason_codes or self.note is not None:
                raise ValueError("not_required human review cannot contain reasons or note")
        elif not self.reason_codes:
            raise ValueError("pending or acknowledged review requires reason codes")
        if self.status is not HumanReviewStatus.ACKNOWLEDGED and self.note is not None:
            raise ValueError("only acknowledged review can contain a note")
        return self


def build_human_review_state(
    report: EvidenceReviewReport,
    *,
    updated_at: datetime,
) -> HumanReviewState:
    if report.status is EvidenceReviewStatus.BLOCKED:
        raise ValueError("blocked evidence review cannot enter acknowledgement")
    reason_codes = sorted(
        {
            issue.issue_code
            for issue in report.issues
            if issue.severity is ReviewIssueSeverity.WARNING
        }
    )
    return HumanReviewState(
        status=(
            HumanReviewStatus.PENDING
            if report.requires_human_review
            else HumanReviewStatus.NOT_REQUIRED
        ),
        reason_codes=reason_codes,
        updated_at=updated_at,
    )
