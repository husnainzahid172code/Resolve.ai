"""FastAPI application entry point.  Run:  uvicorn app.main:app --reload"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings
from app.database.db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("resolveai")


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    init_db()
    info = s.public_runtime_info()
    log.info("ResolveAI starting | planner=%s | data=%s", info["planner_label"], info["data_source_label"])
    if s.admin_password == "change-me":
        log.warning("ADMIN_PASSWORD is the default 'change-me' - set it in backend/.env")
    yield


app = FastAPI(title="ResolveAI", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(router)

# Serve the built frontend (frontend/dist) if present, so one process can run the whole demo.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = _dist / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(_dist / "index.html")
