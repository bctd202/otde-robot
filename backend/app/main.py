import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings
from app.services.signal_engine import background_scan_once

logger = logging.getLogger(__name__)
startup_logger = logging.getLogger("uvicorn.error")
settings = get_settings()

SCANNER_JOB_ID = "parlay-signal-engine"


def add_scanner_job(scheduler: AsyncIOScheduler, scan_callable=background_scan_once):
    """Register one coalescing scan shortly after each one-minute candle closes."""
    second = max(0, min(settings.parlay_scan_second, 59))
    grace = max(1, settings.parlay_scan_misfire_grace_seconds)
    return scheduler.add_job(
        scan_callable,
        CronTrigger(minute="*", second=second, timezone=settings.timezone),
        id=SCANNER_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=grace,
    )


@asynccontextmanager
async def lifespan(application: FastAPI):
    scanner_scheduler = None
    if settings.parlay_background_scanner_enabled:
        scanner_scheduler = AsyncIOScheduler(timezone=settings.timezone)
        add_scanner_job(scanner_scheduler)
        scanner_scheduler.start()
        application.state.scanner_scheduler = scanner_scheduler
        startup_logger.info(
            "Parlay background signal engine started; schedule=every minute at second=%02d "
            "timezone=%s max_instances=1 coalesce=true misfire_grace_time=%ss",
            max(0, min(settings.parlay_scan_second, 59)), settings.timezone,
            max(1, settings.parlay_scan_misfire_grace_seconds),
        )
    try:
        yield
    finally:
        if scanner_scheduler is not None and scanner_scheduler.running:
            scanner_scheduler.shutdown(wait=False)
        application.state.scanner_scheduler = None


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")


@app.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket) -> None:
    await ws.accept()
    while True:
        await ws.send_text(json.dumps({"type": "heartbeat", "paper_only": True}))
        await asyncio.sleep(10)


def resolve_frontend_dist() -> Path:
    """Resolve bundled Docker output first, with explicit and local-dev fallbacks."""
    module_path = Path(__file__).resolve()
    candidates = [
        Path(os.environ["FRONTEND_DIST_DIR"]).resolve()
        if os.environ.get("FRONTEND_DIST_DIR") else None,
        module_path.parents[1] / "frontend" / "dist",  # /app/frontend/dist in production
        module_path.parents[2] / "frontend" / "dist",  # repository frontend/dist locally
    ]
    for candidate in candidates:
        if candidate is not None and (candidate / "index.html").is_file():
            return candidate
    return next(candidate for candidate in candidates if candidate is not None)


frontend_dist = resolve_frontend_dist()
frontend_index = frontend_dist / "index.html"
frontend_assets = frontend_dist / "assets"
logger.info(
    "Frontend build path=%s index_exists=%s assets_exists=%s",
    frontend_dist,
    frontend_index.is_file(),
    frontend_assets.is_dir(),
)

if frontend_index.is_file():
    if frontend_assets.is_dir():
        app.mount("/assets", StaticFiles(directory=frontend_assets), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    async def frontend_root() -> FileResponse:
        return FileResponse(frontend_index, media_type="text/html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend_spa(full_path: str) -> FileResponse:
        # Valid API/docs/WebSocket routes are registered before this fallback. Keep
        # unknown reserved paths as 404s rather than returning the React shell.
        reserved_root = full_path.split("/", 1)[0]
        if reserved_root in {"api", "docs", "redoc", "openapi.json", "ws"}:
            raise HTTPException(status_code=404, detail="Not Found")
        requested = (frontend_dist / full_path).resolve()
        if requested.is_relative_to(frontend_dist.resolve()) and requested.is_file():
            return FileResponse(requested)
        return FileResponse(frontend_index, media_type="text/html")
else:
    logger.warning("Compiled frontend not found; API remains available but GET / is not registered")
