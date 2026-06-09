from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from playwright.async_api import BrowserContext, async_playwright

from x_spider.config import Settings


@asynccontextmanager
async def persistent_context(settings: Settings) -> AsyncIterator[BrowserContext]:
    settings.resolved_browser_profile_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        if settings.cdp_endpoint:
            browser = await playwright.chromium.connect_over_cdp(
                settings.cdp_endpoint,
                no_defaults=True,
            )
            if not browser.contexts:
                raise RuntimeError("Connected Chrome has no default browser context.")
            yield browser.contexts[0]
            return

        launch_options = {
            "user_data_dir": str(settings.resolved_browser_profile_dir),
            "headless": settings.headless,
            "chromium_sandbox": settings.chromium_sandbox,
            "viewport": {
                "width": settings.viewport_width,
                "height": settings.viewport_height,
            },
        }
        browser_executable_path = settings.resolved_browser_executable_path
        if browser_executable_path:
            if not browser_executable_path.is_file():
                raise RuntimeError(
                    f"Configured Chrome executable does not exist: {browser_executable_path}"
                )
            launch_options["executable_path"] = str(browser_executable_path)
        elif settings.browser_channel:
            launch_options["channel"] = settings.browser_channel

        context = await playwright.chromium.launch_persistent_context(
            **launch_options,
        )

        try:
            yield context
        finally:
            if settings.close_browser_on_finish:
                await context.close()
