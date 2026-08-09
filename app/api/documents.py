from fastapi import APIRouter, status

from app.schemas.documents import DocumentCreate, DocumentResponse
from app.services.document_service import register_document


router = APIRouter(tags=["documents"])


@router.post(
    "/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_document(document: DocumentCreate) -> DocumentResponse:
    return register_document(document)