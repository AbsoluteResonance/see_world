import hashlib
import json
import sys
from pathlib import Path

# Ensure tools package is importable
_tools_dir = Path(__file__).resolve().parent.parent.parent.parent / "tools"  # see_world/tools/
if str(_tools_dir) not in sys.path:
    sys.path.insert(0, str(_tools_dir))

from backend.config import settings


_cache_dir = Path(settings.upload_dir) / ".cache"
_cache_dir.mkdir(parents=True, exist_ok=True)

_client = None


def _get_client():
    global _client
    if _client is None:
        from tools.kimi.kimi_client import KimiClient
        _client = KimiClient(api_key=settings.kimi_api_key, model=settings.kimi_model)
    return _client


def _cache_key(file_id: str, prompt: str) -> str:
    h = hashlib.md5(prompt.encode()).hexdigest()[:12]
    return f"{file_id}_{h}"


def _get_cached(file_id: str, prompt: str) -> dict | None:
    path = _cache_dir / f"{_cache_key(file_id, prompt)}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def _set_cache(file_id: str, prompt: str, data: dict):
    path = _cache_dir / f"{_cache_key(file_id, prompt)}.json"
    path.write_text(json.dumps(data, ensure_ascii=False))


async def analyze(file_path: str, prompt: str, file_id: str | None = None) -> dict:
    if file_id:
        cached = _get_cached(file_id, prompt)
        if cached:
            return cached

    path = Path(file_path)
    ext = path.suffix.lower()
    image_exts = {".jpg", ".jpeg", ".png", ".webp"}
    video_exts = {".mp4", ".mov", ".avi"}

    try:
        client = _get_client()
        if ext in image_exts:
            result = client.understand_image(str(path), prompt)
        elif ext in video_exts:
            result = client.understand_video(str(path), prompt)
        else:
            return {"content": f"Unsupported file type: {ext}", "error": True}
    except Exception as e:
        return {"content": str(e), "error": True}

    result["model"] = settings.kimi_model
    if file_id:
        _set_cache(file_id, prompt, result)
    return result


async def analyze_batch(file_paths: list[str], prompt: str) -> list[dict]:
    results = []
    for fp in file_paths:
        res = await analyze(fp, prompt)
        results.append({"file": fp, "result": res})
    return results
