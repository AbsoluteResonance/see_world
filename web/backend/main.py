import sys
from pathlib import Path

# Ensure see_world/ and tools/ are importable
_see_world = Path(__file__).resolve().parent.parent.parent  # see_world/
_tools_dir = _see_world / "tools"
for p in [str(_tools_dir), str(_see_world)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.routes import upload, model, slam_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    for sub in ["images", "videos", ".cache"]:
        (Path(settings.upload_dir) / sub).mkdir(parents=True, exist_ok=True)
    if settings.kimi_api_key:
        print(f"[startup] Kimi API key configured (model: {settings.kimi_model})")
    else:
        print("[startup] WARNING: KIMI_API_KEY not set. Analysis endpoints will fail.")
    yield
    # shutdown
    print("[shutdown] See World server stopped")


app = FastAPI(title="See World", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file serving
uploads_path = Path(settings.upload_dir)
uploads_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_path)), name="uploads")

frontend_path = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_path), html=True), name="static")

# Routes
app.include_router(upload.router)
app.include_router(model.router)
app.include_router(slam_routes.router)


@app.get("/api/health")
async def health():
    return {"code": 0, "message": "success", "data": {"status": "ok", "kimi_configured": bool(settings.kimi_api_key)}}


@app.get("/")
async def root():
    from fastapi.responses import FileResponse
    return FileResponse(str(frontend_path / "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, reload=True)
