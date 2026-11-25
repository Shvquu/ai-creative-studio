"""FastAPI application: REST API, Server-Sent Events and the built dashboard."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import __version__
from backend.core.errors import AuthError, StudioError
from backend.orchestration.studio import Studio

from .routes import assets, generation, jobs, system, workflows

log = logging.getLogger("api")


def _token_from(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-token") or request.query_params.get("token")


def create_app(studio: Studio | None = None, *, start_queue: bool = True) -> FastAPI:
    studio = studio or Studio()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        if start_queue:
            await studio.start()
        log.info("AI Creative Studio API %s ready", __version__)
        yield
        if start_queue:
            await studio.stop()

    app = FastAPI(title="AI Creative Studio", version=__version__, lifespan=lifespan,
                  description="Lokale API für Bild-, Video-, Motion- und 3D-Produktion (ComfyUI, FFmpeg, Blender, Remotion).")
    app.state.studio = studio

    app.add_middleware(
        CORSMiddleware,
        allow_origins=studio.settings.server.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(StudioError)
    async def studio_error_handler(request: Request, exc: StudioError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content={"error": exc.to_dict()})

    async def require_token(request: Request) -> None:
        expected = studio.settings.api_token
        if expected and _token_from(request) != expected:
            raise AuthError("Ungültiges oder fehlendes API-Token (ACS_API_TOKEN)")

    @app.get("/api/health", tags=["system"])
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "auth_required": bool(studio.settings.api_token)}

    deps = [Depends(require_token)]
    for module in (system, generation, jobs, assets, workflows):
        app.include_router(module.router, prefix="/api", dependencies=deps)

    dist = studio.settings.project_root / "apps" / "dashboard" / "dist"
    if dist.is_dir() and (dist / "index.html").is_file():
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="dashboard-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                raise StudioError("Not found")
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        async def root() -> JSONResponse:
            return JSONResponse({"message": "AI Creative Studio API läuft. Dashboard nicht gebaut: "
                                            "cd apps/dashboard && npm install && npm run build", "docs": "/docs"})

    return app


def dashboard_dist(root: Path) -> Path:
    return root / "apps" / "dashboard" / "dist"
