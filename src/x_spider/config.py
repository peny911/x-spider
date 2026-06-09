from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def find_env_file(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    candidates = [current, *current.parents]
    for directory in candidates:
        env_path = directory / ".env"
        if env_path.is_file():
            return env_path
    return None


def parse_env_value(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1]
    if " #" in cleaned:
        cleaned = cleaned.split(" #", 1)[0].rstrip()
    return cleaned


def load_project_env() -> None:
    env_path = find_env_file()
    if not env_path:
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key.startswith("X_SPIDER_"):
            continue
        os.environ[key] = parse_env_value(value)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="X_SPIDER_", env_file=".env", extra="ignore")

    data_dir: Path = Path(".data")
    browser_profile_dir: Path | None = None
    download_dir: Path | None = None
    db_path: Path | None = None
    cdp_endpoint: str | None = None
    browser_executable_path: str | None = None
    browser_channel: str | None = None
    chromium_sandbox: bool = True
    close_browser_on_finish: bool = True
    headless: bool = False
    viewport_width: int = 1280
    viewport_height: int = 900
    request_timeout_seconds: float = 45.0
    no_new_round_limit: int = 8
    scroll_step_min_px: int = 400
    scroll_step_max_px: int = 800
    scroll_pause_min_seconds: float = 1.0
    scroll_pause_max_seconds: float = 2.0
    scroll_steps_per_round: int = 2
    video_capture_seconds: float = 8.0

    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir

    @property
    def resolved_browser_profile_dir(self) -> Path:
        return self.browser_profile_dir or self.resolved_data_dir / "browser-profile"

    @property
    def resolved_download_dir(self) -> Path:
        return self.download_dir or self.resolved_data_dir / "downloads"

    @property
    def resolved_db_path(self) -> Path:
        return self.db_path or self.resolved_data_dir / "db" / "x_spider.sqlite3"

    @property
    def resolved_browser_executable_path(self) -> Path | None:
        value = (self.browser_executable_path or "").strip()
        if not value or value == ".":
            return None
        return Path(value).expanduser()


@lru_cache
def get_settings() -> Settings:
    load_project_env()
    return Settings()
