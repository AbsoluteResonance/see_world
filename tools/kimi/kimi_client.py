import base64
import os
from pathlib import Path

from openai import OpenAI

VALID_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VALID_VIDEO_EXT = {".mp4", ".mov", ".avi", ".webm"}
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100MB


class KimiAPIError(Exception):
    def __init__(self, message: str, original_error: Exception | None = None):
        self.original_error = original_error
        super().__init__(message)


class KimiClient:
    def __init__(self, api_key: str | None = None, model: str = "kimi-k2.6"):
        self.api_key = api_key or os.getenv("KIMI_API_KEY")
        if not self.api_key:
            raise KimiAPIError(
                "KIMI_API_KEY is not set. Pass api_key or set the KIMI_API_KEY env var."
            )
        self.model = model
        self._client = OpenAI(api_key=self.api_key, base_url="https://api.moonshot.cn/v1")

    def _encode_image(self, image_path: str) -> str:
        path = Path(image_path)
        if not path.exists():
            raise KimiAPIError(f"Image not found: {image_path}")
        ext = path.suffix.lower()
        if ext not in VALID_IMAGE_EXT:
            raise KimiAPIError(f"Unsupported image format: {ext}")
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}[ext.lstrip(".")]
        data = path.read_bytes()
        return f"data:image/{mime};base64,{base64.b64encode(data).decode('utf-8')}"

    def _build_content(self, image_paths: list[str], prompt: str) -> list[dict]:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for path in image_paths:
            b64 = self._encode_image(path)
            content.insert(0, {"type": "image_url", "image_url": {"url": b64}})
        return content

    def _call(self, messages: list[dict], stream: bool = False, **kwargs) -> dict:
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=stream,
                **kwargs,
            )
            if stream:
                content_parts: list[str] = []
                for chunk in resp:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        content_parts.append(delta.content)
                content = "".join(content_parts)
                return {"content": content, "usage": {}}
            choice = resp.choices[0]
            usage = resp.usage
            return {
                "content": choice.message.content or "",
                "usage": {
                    "input": usage.prompt_tokens if usage else 0,
                    "output": usage.completion_tokens if usage else 0,
                },
            }
        except Exception as e:
            raise KimiAPIError(f"Kimi API call failed: {e}", original_error=e) from e

    def understand_image(self, image_path: str, prompt: str | None = None) -> dict:
        if prompt is None:
            prompt = "请详细描述这张图片的内容，包括场景、物体、人物、颜色、位置关系等"
        content = self._build_content([image_path], prompt)
        messages = [{"role": "user", "content": content}]
        return self._call(messages)

    def understand_images(self, image_paths: list[str], prompt: str) -> dict:
        content = self._build_content(image_paths, prompt)
        messages = [{"role": "user", "content": content}]
        return self._call(messages)

    def describe_image(self, image_path: str) -> dict:
        return self.understand_image(image_path)

    def chat(self, messages: list[dict], stream: bool = False) -> dict:
        return self._call(messages, stream=stream)

    def understand_video(self, video_path: str, prompt: str) -> dict:
        path = Path(video_path)
        if not path.exists():
            raise KimiAPIError(f"Video not found: {video_path}")
        size = path.stat().st_size
        if size > MAX_VIDEO_SIZE:
            raise KimiAPIError(f"Video too large ({size / 1024 / 1024:.1f}MB). Max {MAX_VIDEO_SIZE / 1024 / 1024:.0f}MB.")
        b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
        ext = path.suffix.lower().lstrip(".")
        mime = ext if ext in {"mp4", "mov", "avi", "webm"} else "mp4"
        content: list[dict] = [
            {"type": "image_url", "image_url": {"url": f"data:video/{mime};base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]
        messages = [{"role": "user", "content": content}]
        return self._call(messages)
