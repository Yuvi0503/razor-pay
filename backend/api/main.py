from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .webhooks import router as webhook_router

app = FastAPI(title="Revenue Recovery", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(webhook_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "simulator-first"}


@app.get("/api/cases")
def cases() -> list[dict]:
    return []


@app.get("/api/evaluation")
def evaluation() -> dict:
    return {
        "message": "Run python -m eval.run --arms all --split test --seed 42 to generate a report."
    }
