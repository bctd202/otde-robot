from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
from pathlib import Path

from app.api.routes import router
from app.core.config import get_settings
from fastapi.staticfiles import StaticFiles

settings=get_settings()
app=FastAPI(title=settings.app_name)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(',')], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router, prefix="/api")

@app.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket):
    await ws.accept()
    while True:
        await ws.send_text(json.dumps({"type":"heartbeat", "paper_only": True}))
        await asyncio.sleep(10)

frontend_dist = Path.cwd() / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
