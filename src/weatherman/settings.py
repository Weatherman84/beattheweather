from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DEFAULT_METEOBLUE_URL = (
    "https://my.meteoblue.com/packages/basic-1h?lat={lat}&lon={lon}"
    "&apikey={apikey}&asl={elevation}&format=json"
)


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///data/weatherman.db")
    meteoblue_api_key: str = os.getenv("METEOBLUE_API_KEY", "")
    meteoblue_url_template: str = os.getenv("METEOBLUE_URL_TEMPLATE", DEFAULT_METEOBLUE_URL)
    timeout: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))


def airports() -> dict[str, dict]:
    with (ROOT / "config" / "airports.json").open(encoding="utf-8") as handle:
        return json.load(handle)


settings = Settings()
