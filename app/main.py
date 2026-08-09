from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router


app = FastAPI(
    title="AI Agent Learning API",
    version="0.1.0",
)

app.include_router(health_router)
app.include_router(documents_router)
app.include_router(chat_router)