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
    slam3r_model_i2p: str = "siyan824/slam3r_i2p"
    slam3r_model_l2w: str = "siyan824/slam3r_l2w"
    slam3r_device: str = "cuda"
    slam3r_output_dir: str = ""
    slam3r_hf_cache: str = "/autodl-fs/data/projects/see_world/.hf_cache"

    class Config:
        env_prefix = "SEE_WORLD_"
        env_file = ".env"


settings = Settings()
