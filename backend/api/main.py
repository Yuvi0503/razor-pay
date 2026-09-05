from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.db.engine import database_url
from backend.logging_filters import install_secret_redaction_filter
from backend.runtime import build_runtime_scheduler, sync_scheduled_actions

from .operations import router as operations_router
from .webhooks import router as webhook_router

install_secret_redaction_filter()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start action execution only when this process has database configuration."""
    try:
        database_url()
    except RuntimeError:
        # Keep the health endpoint and isolated API tests usable without a DB.
        yield
        return

    scheduler = build_runtime_scheduler()
    scheduler.start()
    app.state.recovery_scheduler = scheduler
    sync_scheduled_actions()
    scheduler.add_job(
        sync_scheduled_actions,
        IntervalTrigger(seconds=30),
        id="recovery-action-reconciler",
        replace_existing=True,
        misfire_grace_time=15 * 60,
    )
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)

app = FastAPI(title="Revenue Recovery", version="0.1.0", lifespan=lifespan)
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
