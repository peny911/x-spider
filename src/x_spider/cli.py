from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

from x_spider.browser import persistent_context
from x_spider.config import get_settings
from x_spider.crawler import reset_stale_downloads, retry_failed_images, run_crawl
from x_spider.db import create_session_factory, session_scope
from x_spider.models import CrawlTask, MediaAsset, Tweet
from x_spider.scope import CrawlSpec, build_search_url, build_user_url, normalize_handle, normalize_handles

app = typer.Typer(no_args_is_help=True, help="X-Spider local media downloader.")
console = Console()


def parse_csv_handles(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(normalize_handles([item for item in value.split(",")]))


def ensure_image_capable(media_type: str) -> None:
    if media_type == "videos":
        raise typer.BadParameter("视频下载将在后续阶段实现。当前 MVP 支持 images，all 会先下载图片。")
    if media_type not in {"images", "all"}:
        raise typer.BadParameter("--media 只能是 images、videos 或 all。")


def warn_if_all_mode(media_type: str) -> None:
    if media_type == "all":
        console.print("当前 MVP 会在 all 模式下先下载图片；视频下载将在后续阶段实现。")


def print_result(seen: int, new: int, downloaded: int, skipped: int, failed: int) -> None:
    table = Table(title="Crawl Result")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Seen tweets", str(seen))
    table.add_row("New tweets", str(new))
    table.add_row("Downloaded", str(downloaded))
    table.add_row("Skipped", str(skipped))
    table.add_row("Failed", str(failed))
    console.print(table)


@app.command()
def doctor() -> None:
    """检查本地目录和数据库是否可用。"""

    settings = get_settings()
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_browser_profile_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_download_dir.mkdir(parents=True, exist_ok=True)
    factory = create_session_factory(settings)
    with session_scope(factory):
        pass

    table = Table(title="X-Spider Doctor")
    table.add_column("Item")
    table.add_column("Value")
    table.add_row("Data dir", str(settings.resolved_data_dir))
    table.add_row("Browser profile", str(settings.resolved_browser_profile_dir))
    table.add_row("Download dir", str(settings.resolved_download_dir))
    table.add_row("Database", str(settings.resolved_db_path))
    table.add_row("CDP endpoint", settings.cdp_endpoint or "")
    table.add_row("Browser executable", str(settings.resolved_browser_executable_path or ""))
    table.add_row("Browser channel", settings.browser_channel or "playwright chromium")
    table.add_row("Chromium sandbox", str(settings.chromium_sandbox))
    table.add_row("Headless", str(settings.headless))
    table.add_row(
        "Scroll step",
        f"{settings.scroll_step_min_px}-{settings.scroll_step_max_px}px",
    )
    table.add_row(
        "Scroll pause",
        f"{settings.scroll_pause_min_seconds}-{settings.scroll_pause_max_seconds}s",
    )
    table.add_row("Scroll steps/round", str(settings.scroll_steps_per_round))
    console.print(table)


@app.command()
def login() -> None:
    """打开持久化浏览器，让用户手动登录 X。"""

    async def _run() -> None:
        settings = get_settings()
        async with persistent_context(settings) as context:
            page = await context.new_page()
            await page.goto("https://x.com/home", wait_until="domcontentloaded")
            console.print("浏览器已打开。请手动登录 X，完成后回到终端按 Enter。")
            typer.prompt("登录完成后按 Enter 继续", default="", show_default=False)

    asyncio.run(_run())


@app.command("crawl-user")
def crawl_user(
    handle: Annotated[str, typer.Argument(help="作者 handle，例如 @authorA")],
    keyword: Annotated[str | None, typer.Option("--keyword", "-k", help="可选关键词")] = None,
    media: Annotated[
        str,
        typer.Option("--media", "-m", help="images / videos / all"),
    ] = "images",
    max_scrolls: Annotated[int, typer.Option("--max-scrolls", help="最大滚动轮数")] = 100,
    max_items: Annotated[int | None, typer.Option("--max-items", help="最多处理帖子数")] = None,
) -> None:
    """抓取作者主页，或作者范围内的关键词搜索结果。"""

    ensure_image_capable(media)
    warn_if_all_mode(media)
    normalized = normalize_handle(handle)
    spec = CrawlSpec(
        task_type="user",
        publishers=(normalized,),
        keyword=keyword,
        media_type=media,
    )
    url = build_search_url(spec) if keyword else build_user_url(normalized)

    async def _run() -> None:
        settings = get_settings()
        factory = create_session_factory(settings)
        async with persistent_context(settings) as context:
            page = await context.new_page()
            with session_scope(factory) as session:
                reset_stale_downloads(session)
                result = await run_crawl(
                    page=page,
                    session=session,
                    settings=settings,
                    spec=spec,
                    url=url,
                    max_scrolls=max_scrolls,
                    max_items=max_items,
                )
        print_result(
            result.seen_tweets,
            result.new_tweets,
            result.downloaded,
            result.skipped,
            result.failed,
        )

    asyncio.run(_run())


@app.command("crawl-search")
def crawl_search(
    mentions: Annotated[
        str | None,
        typer.Option("--mentions", help="正文提及账号，逗号分隔，例如 @a,@b"),
    ] = None,
    publishers: Annotated[
        str | None,
        typer.Option("--publishers", help="发布者账号，逗号分隔，例如 @a,@b"),
    ] = None,
    keyword: Annotated[str | None, typer.Option("--keyword", "-k", help="可选关键词")] = None,
    media: Annotated[
        str,
        typer.Option("--media", "-m", help="images / videos / all"),
    ] = "images",
    max_scrolls: Annotated[int, typer.Option("--max-scrolls", help="最大滚动轮数")] = 100,
    max_items: Annotated[int | None, typer.Option("--max-items", help="最多处理帖子数")] = None,
) -> None:
    """抓取 X 搜索页，支持发布者、提及和关键词组合。"""

    ensure_image_capable(media)
    warn_if_all_mode(media)
    parsed_mentions = parse_csv_handles(mentions)
    parsed_publishers = parse_csv_handles(publishers)
    if not parsed_mentions and not parsed_publishers and not keyword:
        raise typer.BadParameter("至少提供 --mentions、--publishers 或 --keyword 之一。")

    spec = CrawlSpec(
        task_type="search",
        publishers=parsed_publishers,
        mentions=parsed_mentions,
        keyword=keyword,
        media_type=media,
    )
    url = build_search_url(spec)

    async def _run() -> None:
        settings = get_settings()
        factory = create_session_factory(settings)
        async with persistent_context(settings) as context:
            page = await context.new_page()
            with session_scope(factory) as session:
                reset_stale_downloads(session)
                result = await run_crawl(
                    page=page,
                    session=session,
                    settings=settings,
                    spec=spec,
                    url=url,
                    max_scrolls=max_scrolls,
                    max_items=max_items,
                )
        print_result(
            result.seen_tweets,
            result.new_tweets,
            result.downloaded,
            result.skipped,
            result.failed,
        )

    asyncio.run(_run())


@app.command("retry-failed")
def retry_failed() -> None:
    """重试下载失败或待处理的图片。"""

    async def _run() -> None:
        settings = get_settings()
        factory = create_session_factory(settings)
        with session_scope(factory) as session:
            result = await retry_failed_images(session, settings)
        print_result(0, 0, result.downloaded, result.skipped, result.failed)

    asyncio.run(_run())


@app.command()
def stats() -> None:
    """查看本地数据库统计。"""

    settings = get_settings()
    factory = create_session_factory(settings)
    with session_scope(factory) as session:
        tweet_count = session.scalar(select(func.count()).select_from(Tweet)) or 0
        asset_count = session.scalar(select(func.count()).select_from(MediaAsset)) or 0
        downloaded_count = (
            session.scalar(
                select(func.count())
                .select_from(MediaAsset)
                .where(MediaAsset.download_status == "downloaded")
            )
            or 0
        )
        failed_count = (
            session.scalar(
                select(func.count())
                .select_from(MediaAsset)
                .where(MediaAsset.download_status == "failed")
            )
            or 0
        )
        task_count = session.scalar(select(func.count()).select_from(CrawlTask)) or 0

    table = Table(title="X-Spider Stats")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Tasks", str(task_count))
    table.add_row("Tweets", str(tweet_count))
    table.add_row("Assets", str(asset_count))
    table.add_row("Downloaded", str(downloaded_count))
    table.add_row("Failed", str(failed_count))
    console.print(table)


if __name__ == "__main__":
    app()
