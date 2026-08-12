from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class SiteSelectionRequirement(BaseModel):
    """Structured fields extracted from a site-selection request."""

    model_config = ConfigDict(extra="forbid")

    project_type: NonEmptyString = Field(
        description="建设项目类型",
        examples=["logistics_park"],
    )
    land_area_hectares: float | None = Field(
        default=None,
        gt=0,
        description="项目占地面积，单位为公顷；未提供时为 null",
        examples=[30.0],
    )
    candidate_sites: list[NonEmptyString] = Field(
        description="用户明确提供的候选地块编号或名称",
        examples=[["A01", "B01"]],
    )
    review_items: list[NonEmptyString] = Field(
        description="用户要求比较或核查的事项",
        examples=[["交通条件", "生态保护红线", "永久基本农田"]],
    )
