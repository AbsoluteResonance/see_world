from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    kimi_api_key: str = ""
    upload_dir: str = str(Path(__file__).resolve().parent.parent / "uploads")
    host: str = "0.0.0.0"
    port: int = 8080
    max_image_size_mb: int = 20
    max_video_size_mb: int = 200
    kimi_model: str = "kimi-k2.6"
    tunnel_token: str = ""

    class Config:
        env_prefix = "SEE_WORLD_"
        env_file = ".env"


settings = Settings()
