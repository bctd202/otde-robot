import asyncio
import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
app = FastAPI(title=settings.app_name)
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
