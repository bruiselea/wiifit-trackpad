"""Installed-resource and per-user data paths, following the SpaceMouse app."""

from __future__ import annotations

import os
from pathlib import Path


PRODUCT_DIRECTORY = "WiiFitGiantTrackpad"


def user_data_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / PRODUCT_DIRECTORY


def user_settings_path() -> Path:
    return user_data_directory() / "settings.json"


def user_log_path() -> Path:
    return user_data_directory() / "logs" / "app.log"

