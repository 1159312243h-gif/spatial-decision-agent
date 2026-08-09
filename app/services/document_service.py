from uuid import uuid4

from app.schemas.documents import DocumentCreate, DocumentResponse


def register_document(document: DocumentCreate) -> DocumentResponse:
    return DocumentResponse(
        document_id=str(uuid4()),
        status="accepted",
        metadata=document,
    )