from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from .config import AppConfig, load_config


class RuntimeSettings(BaseModel):
    config_path: Path
    app_config: AppConfig


def build_runtime_settings() -> RuntimeSettings:
    """Load config path from env and parse the YAML file."""

    raw_path = os.environ.get("OPENCLAW_PROXY_CONFIG", "config.yaml")
    config_path = Path(raw_path).expanduser().resolve()

    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file '{config_path}' not found. Set OPENCLAW_PROXY_CONFIG to a valid path."
        )

    app_config = load_config(config_path)
    return RuntimeSettings(config_path=config_path, app_config=app_config)
