from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class DocumentCreate(BaseModel):
    filename: NonEmptyString = Field(
        description="文档文件名",
        examples=["land_policy.pdf"],
    )
    source: NonEmptyString = Field(
        description="文档来源",
        examples=["自然资源部门"],
    )
    document_type: NonEmptyString = Field(
        description="文档类型",
        examples=["planning_policy"],
    )


class DocumentResponse(BaseModel):
    document_id: str
    status: Literal["accepted"]
    metadata: DocumentCreate