"""Launcher: pre-load MASt3R model, start server with working lifespan."""

import sys
from pathlib import Path

_see_world = Path(__file__).resolve().parent.parent  # see_world/
for p in [str(_see_world)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import os
os.environ["OMP_NUM_THREADS"] = "4"

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from backend.config import settings
from backend.routes import upload, model, slam_routes, slam3r_routes, calibrate, test_routes


# Middleware to prevent caching of HTML and JS
class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response: Response = await call_next(request)
        path = request.url.path
        if path in ("/",) or path.endswith(".html") or path.endswith(".js") or path.endswith(".css"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

# ── Pre-load MASt3R model before accepting connections ──
print("[startup] Pre-loading MASt3R model...")
ok = False
try:
    from backend.services.mast3r_slam_service import start_inference
    ok = start_inference()
    if ok:
        print("[startup] MASt3R inference subprocess started, model loading in background...")
except Exception as e:
    print(f"[startup] MASt3R pre-load failed: {e}")
    import traceback
    traceback.print_exc()
print(f"[startup] MASt3R pre-load: {'OK' if ok else 'FAILED'}")

# ── FastAPI app ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Minimal startup (dirs only, skip SLAM3R + VINS)
    for sub in ["images", "videos", ".cache"]:
        (Path(settings.upload_dir) / sub).mkdir(parents=True, exist_ok=True)
    print("[startup] Server ready (SLAM3R model loading skipped)")
    yield
    print("[shutdown] Server stopped")

app = FastAPI(title="See World", version="0.1.0", lifespan=lifespan)
app.add_middleware(NoCacheMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

uploads_path = Path(settings.upload_dir)
uploads_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_path)), name="uploads")

frontend_path = Path(__file__).resolve().parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_path), html=True), name="static")

app.include_router(upload.router)
app.include_router(model.router)
app.include_router(slam_routes.router)
app.include_router(calibrate.router)
app.include_router(slam3r_routes.router)
app.include_router(test_routes.router)

@app.get("/api/health")
async def health():
    return {"code": 0, "message": "success", "data": {"status": "ok"}}

@app.get("/")
async def root():
    from fastapi.responses import FileResponse
    return FileResponse(str(frontend_path / "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
