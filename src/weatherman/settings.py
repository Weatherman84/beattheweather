from __future__ import annotations

import json
import os
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(os.getenv("WEATHERMAN_HOME", Path.cwd())).resolve()
load_dotenv(ROOT / ".env")

DEFAULT_METEOBLUE_URL = (
    "https://my.meteoblue.com/packages/basic-1h_basic-day?lat={lat}&lon={lon}"
    "&apikey={apikey}&asl={elevation}&format=json"
)


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///data/weatherman.db")
    meteoblue_api_key: str = os.getenv("METEOBLUE_API_KEY", "")
    meteoblue_url_template: str = os.getenv("METEOBLUE_URL_TEMPLATE", DEFAULT_METEOBLUE_URL)
    timeout: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))


def airports() -> dict[str, dict]:
    # Allow repository users to edit config/airports.json. The packaged copy is
    # the reliable fallback when Weatherman is installed by GitHub Actions.
    local_config = ROOT / "config" / "airports.json"
    resource = (
        local_config
        if local_config.exists()
        else files("weatherman").joinpath("data/airports.json")
    )
    with resource.open(encoding="utf-8") as handle:
        return json.load(handle)


settings = Settings()
