import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Config:
    data_dir: Path
    model_base_url: str = ""
    model_name: str = ""
    api_key: str = ""
    memory_model: str = ""
    context_chars: int = 14000
    recent_chars: int = 8000
    memory_chars: int = 2500
    max_reply_chars: int = 24000

    @classmethod
    def load(cls):
        load_dotenv(ROOT / ".env", override=False)
        data_dir = Path(os.getenv("YF_DATA_DIR", ".local"))
        if not data_dir.is_absolute():
            data_dir = ROOT / data_dir
        return cls(
            data_dir=data_dir.resolve(),
            model_base_url=os.getenv("YF_MODEL_BASE_URL", "").rstrip("/"),
            model_name=os.getenv("YF_MODEL_NAME", ""),
            api_key=os.getenv("YF_MODEL_API_KEY", ""),
            memory_model=os.getenv("YF_MEMORY_MODEL", ""),
        )
