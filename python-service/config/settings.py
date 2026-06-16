import json
from pathlib import Path
from pydantic_settings import BaseSettings

CONFIG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CONFIG_DIR.parent

class Settings(BaseSettings):
    cookies_path: str = str(CONFIG_DIR / "cookies.json")
    download_dir: str = str(Path("/tmp/quark_downloads"))
    download_ttl_seconds: int = 300
    quark_base_url: str = "https://drive-pc.quark.cn"
    log_level: str = "INFO"

    class Config:
        env_prefix = "QUARK_"

settings = Settings()
Path(settings.download_dir).mkdir(parents=True, exist_ok=True)
