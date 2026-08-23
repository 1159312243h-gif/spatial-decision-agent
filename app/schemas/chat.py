from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from practice.site_selection import (
    ProjectType,
    ScenarioConversationReply,
    ScenarioConversationSession,
)


NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class CandidateParcel(BaseModel):
    """Legacy chat context retained for API compatibility."""

    model_config = ConfigDict(extra="forbid")

    parcel_id: NonEmptyString
    name: NonEmptyString


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: NonEmptyString
    session_id: NonEmptyString | None = None
    project_type: ProjectType | None = None
    candidate_parcels: list[CandidateParcel] = Field(default_factory=list)


class ChatConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: NonEmptyString
    confirmed_by: NonEmptyString


class ChatResponse(ScenarioConversationReply):
    received_candidates: int = Field(default=0, ge=0)

    @classmethod
    def from_reply(
        cls,
        reply: ScenarioConversationReply,
        *,
        received_candidates: int = 0,
    ) -> ChatResponse:
        return cls(
            **reply.model_dump(),
            received_candidates=received_candidates,
        )


ChatSessionResponse = ScenarioConversationSession
