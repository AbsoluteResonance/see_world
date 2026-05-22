import uuid
from datetime import datetime
from pathlib import Path

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_VIDEO_EXT = {".mp4", ".mov", ".avi"}
ALLOWED_EXT = ALLOWED_IMAGE_EXT | ALLOWED_VIDEO_EXT


def sanitize_filename(name: str) -> str:
    clean = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    return clean or "unnamed"


def generate_file_id() -> str:
    return uuid.uuid4().hex[:8]


def make_storage_filename(original: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid = generate_file_id()
    safe = sanitize_filename(original)
    return f"{ts}_{uid}_{safe}"


def is_allowed_ext(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_EXT


def is_image_ext(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_IMAGE_EXT


def is_video_ext(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_VIDEO_EXT
