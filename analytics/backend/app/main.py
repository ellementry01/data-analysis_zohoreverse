import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import get_settings
from .db import get_engine, init_db
from .routers import analysis, data, workspaces

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.enable_scheduler:
        from .services import scheduler
        scheduler.start()
    yield
    if settings.enable_scheduler:
        from .services import scheduler
        scheduler.stop()


app = FastAPI(title="Ellementry Analytics", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(workspaces.router)
app.include_router(data.router)
app.include_router(analysis.router)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    # The built UI has no inline scripts; React/ECharts set inline styles; PNG export uses data: URLs.
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                               "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
                               "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    # Details go to the server log only; clients get an opaque reference.
    import uuid

    ref = uuid.uuid4().hex[:8]
    logging.getLogger("ellementry").exception("Unhandled error %s on %s", ref, request.url.path)
    return JSONResponse({"detail": f"Internal error (reference {ref}). See the server log for details."}, status_code=500)


@app.get("/api/health")
def health():
    with get_engine().connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ok"}


# Serve the built frontend (frontend/dist) when present, so one process runs the whole app.
_dist = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend", "dist")
if os.path.isdir(_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dist, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = os.path.join(_dist, path)
        if path and os.path.isfile(candidate) and os.path.commonpath([_dist, os.path.abspath(candidate)]) == _dist:
            return FileResponse(candidate)
        # The page shell must always be revalidated so a new build is picked up; hashed /assets/* can cache.
        return FileResponse(os.path.join(_dist, "index.html"), headers={"Cache-Control": "no-cache"})
