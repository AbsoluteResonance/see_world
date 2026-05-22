from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.services import kimi_service, slam_service
from backend.utils import is_allowed_ext

router = APIRouter()


@router.post("/api/analyze/{file_id}")
async def analyze_file(file_id: str, body: dict):
    prompt = body.get("prompt", "请详细描述这张图片的内容，包括场景、物体、人物、颜色、位置关系等")

    upload_dir = Path(settings.upload_dir)
    found_path = None
    for subdir in ["images", "videos"]:
        d = upload_dir / subdir
        if not d.exists():
            continue
        for f in d.iterdir():
            if file_id in f.name:
                found_path = f
                break

    if not found_path:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})

    if not is_allowed_ext(found_path.name):
        raise HTTPException(status_code=400, detail={"code": 40002, "message": "Unsupported file format"})

    result = await kimi_service.analyze(str(found_path), prompt, file_id=file_id)
    return {"code": 0, "message": "success", "data": result}


@router.post("/api/reconstruct")
async def reconstruct(body: dict):
    images_dir = body.get("images_dir", "")
    output_dir = body.get("output_dir", "")
    result = slam_service.reconstruct(images_dir, output_dir)
    return {"code": 0, "message": result.get("message", ""), "data": result}
