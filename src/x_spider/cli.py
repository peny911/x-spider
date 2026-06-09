from __future__ import annotations

import asyncio
from typing import Annotated
from urllib.parse import parse_qs, urlparse

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

from x_spider.browser import persistent_context
from x_spider.config import get_settings
from x_spider.crawler import reset_author_records, reset_stale_downloads, retry_failed_images, run_crawl
from x_spider.db import create_session_factory, session_scope
from x_spider.models import CrawlTask, MediaAsset, Tweet
from x_spider.scope import CrawlSpec, build_search_url, build_user_url, normalize_handle, normalize_handles

app = typer.Typer(no_args_is_help=True, help="X-Spider local media downloader.")
console = Console(markup=False)


def parse_csv_handles(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(normalize_handles([item for item in value.split(",")]))


def ensure_media_capable(media_type: str) -> None:
    if media_type not in {"images", "videos", "all"}:
        raise typer.BadParameter("--media 只能是 images、videos 或 all。")


def warn_if_all_mode(media_type: str) -> None:
    if media_type == "videos":
        console.print("视频下载会逐条打开 tweet 详情页捕获 mp4，请预期速度会慢于图片。")
    elif media_type == "all":
        console.print("all 模式会同时尝试下载图片和视频；视频会逐条打开 tweet 详情页捕获 mp4。")


def print_result(
    seen: int,
    new: int,
    downloaded: int,
    skipped: int,
    failed: int,
    scroll_rounds: int = 0,
    no_new_rounds: int = 0,
    stop_reason: str = "",
) -> None:
    table = Table(title="Crawl Result")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Seen tweets", str(seen))
    table.add_row("New tweets", str(new))
    table.add_row("Downloaded", str(downloaded))
    table.add_row("Skipped", str(skipped))
    table.add_row("Failed", str(failed))
    table.add_row("Scroll rounds", str(scroll_rounds))
    table.add_row("No-new rounds", str(no_new_rounds))
    table.add_row("Stop reason", stop_reason or "-")
    console.print(table)


def print_crawl_progress(event: dict[str, object]) -> None:
    console.print(
        "[crawl] "
        f"round={event['round']} "
        f"visible={event['visible']} "
        f"new_visible={event['new_visible']} "
        f"new_tweets={event.get('new_tweets', '-')} "
        f"new_records={event.get('new_records', '-')} "
        f"matched={event['matched']} "
        f"media={event['media']} "
        f"downloaded={event['downloaded']} "
        f"skipped={event['skipped']} "
        f"failed={event['failed']} "
        f"total_seen={event['total_seen']} "
        f"no_new_rounds={event['no_new_rounds']} "
        f"snapshots={event.get('snapshots', '-')} "
        f"scroll_y={event.get('scroll_y', '-')} "
        f"scroll_distance={event.get('scroll_distance', '-')}"
    )
    if event.get("last_error"):
        console.print(f"[download] last_error={short_value(event['last_error'])}")


def short_value(value: object, limit: int = 160) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def print_video_progress(event: dict[str, object]) -> None:
    event_name = str(event.get("event") or "")
    if event_name == "start":
        console.print(
            "[video] "
            f"start tweet_id={event.get('tweet_id')} "
            f"url={short_value(event.get('tweet_url'))}"
        )
    elif event_name == "open_detail":
        console.print(
            "[video] "
            f"open_detail capture_seconds={event.get('capture_seconds')} "
            f"url={short_value(event.get('tweet_url'))}"
        )
    elif event_name == "player_click":
        console.print(f"[video] player_click selector={event.get('selector')}")
    elif event_name == "capture_done":
        console.print(
            "[video] "
            f"capture_done total={event.get('total_urls')} "
            f"mp4={event.get('mp4_urls')} "
            f"hls={event.get('playlist_urls')}"
        )
    elif event_name == "candidate":
        console.print(
            "[video] "
            f"candidate quality={event.get('quality')} "
            f"bytes={event.get('content_length')} "
            f"url={short_value(event.get('url'))}"
        )
    elif event_name == "select":
        console.print(
            "[video] "
            f"select quality={event.get('quality')} "
            f"bytes={event.get('content_length')} "
            f"url={short_value(event.get('url'))}"
        )
    elif event_name == "hls_variant":
        console.print(
            "[video] "
            f"hls_variant quality={event.get('quality')} "
            f"bandwidth={event.get('bandwidth')} "
            f"url={short_value(event.get('url'))}"
        )
    elif event_name == "hls_select":
        console.print(
            "[video] "
            f"hls_select quality={event.get('quality')} "
            f"segments={event.get('segments')} "
            f"url={short_value(event.get('url'))}"
        )
    elif event_name == "hls_downloaded":
        console.print(
            "[video] "
            f"hls_downloaded quality={event.get('quality')} "
            f"segments={event.get('segments')} "
            f"bytes={event.get('bytes')} "
            f"url={short_value(event.get('url'))}"
        )
    elif event_name == "download_response":
        console.print(
            "[video] "
            f"download_response status={event.get('status_code')} "
            f"bytes={event.get('bytes')} "
            f"content_type={event.get('content_type')} "
            f"url={short_value(event.get('url'))}"
        )
    elif event_name == "saved":
        console.print(
            "[video] "
            f"saved tweet_id={event.get('tweet_id')} "
            f"quality={event.get('quality')} "
            f"bytes={event.get('bytes')} "
            f"path={short_value(event.get('local_path'))}"
        )
    elif event_name == "skip_existing":
        console.print(
            "[video] "
            f"skip_existing tweet_id={event.get('tweet_id')} "
            f"media={short_value(event.get('media_identity'))}"
        )
    elif event_name == "failed":
        console.print(
            "[video] "
            f"failed tweet_id={event.get('tweet_id')} "
            f"error={short_value(event.get('error'))} "
            f"url={short_value(event.get('tweet_url'))}"
        )
    else:
        console.print(f"[video] {event}")


def format_limit(value: int) -> str:
    return "unlimited" if value <= 0 else str(value)


def search_query_from_url(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    values = query.get("q") or []
    return values[0] if values else ""


def should_pause_before_browser_exit(settings) -> bool:
    return not settings.close_browser_on_finish and not settings.cdp_endpoint


def pause_before_browser_exit(settings) -> None:
    if not should_pause_before_browser_exit(settings):
        return
    console.print(
        "X_SPIDER_CLOSE_BROWSER_ON_FINISH=false：浏览器会保留到你按 Enter。"
    )
    console.print("注意：这是 Playwright 管理的浏览器，命令退出后窗口仍会关闭。")
    typer.prompt("检查完成后按 Enter 结束命令", default="", show_default=False)


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
    table.add_row("Close browser on finish", str(settings.close_browser_on_finish))
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
    table.add_row("No-new round limit", str(settings.no_new_round_limit))
    table.add_row("Video capture seconds", str(settings.video_capture_seconds))
    console.print(table)


@app.command()
def login() -> None:
    """打开持久化浏览器，让用户手动登录 X。"""

    async def _run() -> None:
        settings = get_settings()
        async with persistent_context(settings) as context:
            page = await context.new_page()
            await page.goto("https://x.com/home", wait_until="domcontentloaded")
            console.print("浏览器已打开。请手动登录 X。")
            if should_pause_before_browser_exit(settings):
                pause_before_browser_exit(settings)
            else:
                typer.prompt("登录完成后按 Enter 继续", default="", show_default=False)

    asyncio.run(_run())


@app.command("crawl-user")
def crawl_user(
    handle: Annotated[str, typer.Argument(help="作者 handle，例如 @authorA")],
    keyword: Annotated[str | None, typer.Option("--keyword", "-k", help="可选关键词")] = None,
    mentions: Annotated[
        str | None,
        typer.Option("--mentions", help="正文提及账号，逗号分隔，例如 @a,@b"),
    ] = None,
    media: Annotated[
        str,
        typer.Option("--media", "-m", help="images / videos / all"),
    ] = "images",
    max_scrolls: Annotated[int, typer.Option("--max-scrolls", help="最大滚动轮数；0 表示不限制")] = 0,
    max_items: Annotated[int | None, typer.Option("--max-items", help="最多处理帖子数")] = None,
    no_new_round_limit: Annotated[
        int | None,
        typer.Option("--no-new-round-limit", help="连续无新内容后停止的轮数"),
    ] = None,
    source: Annotated[
        str,
        typer.Option("--source", help="auto / homepage / search"),
    ] = "auto",
    search_tab: Annotated[
        str,
        typer.Option("--search-tab", help="top / latest"),
    ] = "top",
) -> None:
    """抓取作者主页，或作者范围内的关键词搜索结果。"""

    ensure_media_capable(media)
    warn_if_all_mode(media)
    if source not in {"auto", "homepage", "search"}:
        raise typer.BadParameter("--source 只能是 auto、homepage 或 search。")
    if search_tab not in {"top", "latest"}:
        raise typer.BadParameter("--search-tab 只能是 top 或 latest。")
    normalized = normalize_handle(handle)
    parsed_mentions = parse_csv_handles(mentions)
    spec = CrawlSpec(
        task_type="user",
        publishers=(normalized,),
        mentions=parsed_mentions,
        keyword=keyword,
        media_type=media,
    )
    if source == "search" or (source == "auto" and (keyword or parsed_mentions)):
        url = build_search_url(spec, search_tab=search_tab)
    else:
        url = build_user_url(normalized)

    async def _run() -> None:
        settings = get_settings()
        factory = create_session_factory(settings)
        console.print(f"[crawl] url={url}")
        search_query = search_query_from_url(url)
        if search_query:
            console.print(f"[crawl] search_query={search_query}")
        console.print(
            "[crawl] "
            f"max_scrolls={format_limit(max_scrolls)} "
            f"no_new_round_limit={no_new_round_limit if no_new_round_limit is not None else settings.no_new_round_limit} "
            f"source={source} "
            f"search_tab={search_tab}"
        )
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
                    no_new_round_limit=no_new_round_limit,
                    progress_callback=print_crawl_progress,
                    video_progress_callback=print_video_progress,
                )
            print_result(
                result.seen_tweets,
                result.new_tweets,
                result.downloaded,
                result.skipped,
                result.failed,
                result.scroll_rounds,
                result.no_new_rounds,
                result.stop_reason,
            )
            pause_before_browser_exit(settings)

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
    max_scrolls: Annotated[int, typer.Option("--max-scrolls", help="最大滚动轮数；0 表示不限制")] = 0,
    max_items: Annotated[int | None, typer.Option("--max-items", help="最多处理帖子数")] = None,
    no_new_round_limit: Annotated[
        int | None,
        typer.Option("--no-new-round-limit", help="连续无新内容后停止的轮数"),
    ] = None,
    search_tab: Annotated[
        str,
        typer.Option("--search-tab", help="top / latest"),
    ] = "top",
) -> None:
    """抓取 X 搜索页，支持发布者、提及和关键词组合。"""

    ensure_media_capable(media)
    warn_if_all_mode(media)
    if search_tab not in {"top", "latest"}:
        raise typer.BadParameter("--search-tab 只能是 top 或 latest。")
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
    url = build_search_url(spec, search_tab=search_tab)

    async def _run() -> None:
        settings = get_settings()
        factory = create_session_factory(settings)
        console.print(f"[crawl] url={url}")
        search_query = search_query_from_url(url)
        if search_query:
            console.print(f"[crawl] search_query={search_query}")
        console.print(
            "[crawl] "
            f"max_scrolls={format_limit(max_scrolls)} "
            f"no_new_round_limit={no_new_round_limit if no_new_round_limit is not None else settings.no_new_round_limit} "
            f"search_tab={search_tab}"
        )
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
                    no_new_round_limit=no_new_round_limit,
                    progress_callback=print_crawl_progress,
                    video_progress_callback=print_video_progress,
                )
            print_result(
                result.seen_tweets,
                result.new_tweets,
                result.downloaded,
                result.skipped,
                result.failed,
                result.scroll_rounds,
                result.no_new_rounds,
                result.stop_reason,
            )
            pause_before_browser_exit(settings)

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


@app.command("reset-author")
def reset_author(
    handle: Annotated[str, typer.Argument(help="作者 handle，例如 @authorA")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过确认")] = False,
) -> None:
    """重置指定作者的本地数据库记录，使其可以重新爬取。"""

    normalized = normalize_handle(handle)
    if not yes:
        confirmed = typer.confirm(
            f"将删除作者 @{normalized} 的本地 DB 记录，但不会删除已下载文件。继续？"
        )
        if not confirmed:
            console.print("已取消。")
            return

    settings = get_settings()
    factory = create_session_factory(settings)
    with session_scope(factory) as session:
        result = reset_author_records(session, normalized)

    table = Table(title=f"Reset Author @{result.handle}")
    table.add_column("Record")
    table.add_column("Deleted", justify="right")
    table.add_row("Tweets", str(result.tweets))
    table.add_row("Media assets", str(result.media_assets))
    table.add_row("Scope tweets", str(result.scope_tweets))
    table.add_row("Crawl scopes", str(result.crawl_scopes))
    table.add_row("Crawl tasks", str(result.crawl_tasks))
    console.print(table)


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
