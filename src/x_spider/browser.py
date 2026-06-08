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
            "args": [
                "--disable-blink-features=AutomationControlled",  # 关键：隐藏自动化标记
            ]
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

        # context.add_init_script(
        #     """
        #         // 隐藏webdriver属性
        #         Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        #         // 伪装Chrome对象
        #         window.chrome = {runtime: {}};
        #         // 伪装plugins
        #         Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
        #         // 伪装languages
        #         Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        #         // 伪装platform
        #         Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
        #         // 伪装userAgent
        #         Object.defineProperty(navigator, 'userAgent', {get: () => 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'});
        #     """
        # )

        try:
            yield context
        finally:
            await context.close()
