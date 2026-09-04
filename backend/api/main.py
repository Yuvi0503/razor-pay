from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.logging_filters import install_secret_redaction_filter

from .operations import router as operations_router
from .webhooks import router as webhook_router

install_secret_redaction_filter()

app = FastAPI(title="Revenue Recovery", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(webhook_router)
app.include_router(operations_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "simulator-first"}


