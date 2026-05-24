"""Launcher: pre-load MASt3R model, start server."""
import sys
from pathlib import Path
_see_world = Path(__file__).resolve().parent.parent
for p in [str(_see_world)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import os
os.environ["OMP_NUM_THREADS"] = "4"

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from backend.config import settings
from backend.routes import upload, slam3r_routes

# Pre-load MASt3R model
print("[startup] Pre-loading MASt3R model...")
ok = False
try:
    from backend.services.mast3r_slam_service import start_inference
    ok = start_inference()
    if ok:
        print("[startup] MASt3R inference subprocess started, model loading in background...")
except Exception as e:
    print(f"[startup] MASt3R pre-load failed: {e}")
print(f"[startup] MASt3R pre-load: {'OK' if ok else 'FAILED'}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    for sub in ["images", "videos", ".cache"]:
        (Path(settings.upload_dir) / sub).mkdir(parents=True, exist_ok=True)
    print("[startup] Server ready")
    yield
    print("[shutdown] Server stopped")

app = FastAPI(title="See World", version="0.1.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

uploads_path = Path(settings.upload_dir)
uploads_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_path)), name="uploads")

frontend_path = Path(__file__).resolve().parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_path), html=True), name="static")

app.include_router(upload.router)
app.include_router(slam3r_routes.router)

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
