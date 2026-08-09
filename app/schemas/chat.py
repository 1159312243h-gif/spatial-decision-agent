from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]

ProjectType = Literal[
    "shopping_mall",
    "logistics_park",
]


class CandidateParcel(BaseModel):
    parcel_id: NonEmptyString
    name: NonEmptyString


class ChatRequest(BaseModel):
    question: NonEmptyString
    project_type: ProjectType
    candidate_parcels: list[CandidateParcel] = Field(min_length=1)


class ChatResponse(BaseModel):
    answer: str
    status: Literal["stub"]
    received_candidates: int