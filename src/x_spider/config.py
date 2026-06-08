from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    return Settings()
