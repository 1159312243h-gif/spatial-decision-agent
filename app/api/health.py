from fastapi import APIRouter


router = APIRouter(tags=["system"])


@router.get("/health")
def get_health() -> dict[str, str]:
    return {
        "status": "ok",
        "version": "0.1.0",
    }