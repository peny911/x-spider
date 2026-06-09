from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import random
import httpx
from playwright.async_api import Page
from sqlalchemy import select
from sqlalchemy.orm import Session

from x_spider.config import Settings
from x_spider.downloader import build_local_path, fetch_best_image, fetch_best_video
from x_spider.extractor import ARTICLE_EXTRACT_SCRIPT, ExtractedTweet, parse_extracted_articles
from x_spider.models import CrawlScope, CrawlTask, MediaAsset, ScopeTweet, Tweet, utc_now
from x_spider.scope import CrawlSpec, download_scope_parts


@dataclass
class CrawlResult:
    seen_tweets: int = 0
    new_tweets: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    scroll_rounds: int = 0
    no_new_rounds: int = 0
    stop_reason: str = ""


@dataclass
class ResetAuthorResult:
    handle: str
    tweets: int = 0
    media_assets: int = 0
    scope_tweets: int = 0
    crawl_scopes: int = 0
    crawl_tasks: int = 0


def date_for_filename(tweet: ExtractedTweet) -> str:
    value = tweet.published_at or datetime.utcnow()
    return value.strftime("%Y%m%d")


def media_id_from_identity(media_identity: str) -> str:
    return media_identity.rsplit("/", 1)[-1].replace(":", "_")[:80]


def ensure_scope(session: Session, spec: CrawlSpec) -> CrawlScope:
    scope = session.get(CrawlScope, spec.scope_key)
    if scope:
        return scope
    scope = CrawlScope(scope_key=spec.scope_key)
    session.add(scope)
    session.flush()
    return scope


def upsert_tweet(session: Session, tweet: ExtractedTweet) -> bool:
    existing = session.get(Tweet, tweet.tweet_id)
    if existing:
        existing.last_seen_at = utc_now()
        return False
    session.add(
        Tweet(
            tweet_id=tweet.tweet_id,
            author_handle=tweet.author_handle,
            text=tweet.text,
            url=tweet.url,
            published_at=tweet.published_at,
        )
    )
    return True


def link_scope_tweet(session: Session, scope_key: str, tweet_id: str) -> bool:
    exists = session.execute(
        select(ScopeTweet).where(
            ScopeTweet.scope_key == scope_key,
            ScopeTweet.tweet_id == tweet_id,
        )
    ).scalar_one_or_none()
    if not exists:
        session.add(ScopeTweet(scope_key=scope_key, tweet_id=tweet_id))
        session.flush()
        return True
    return False


def ensure_media_asset(session: Session, tweet: ExtractedTweet, media) -> MediaAsset | None:
    existing = session.execute(
        select(MediaAsset).where(MediaAsset.media_identity == media.media_identity)
    ).scalar_one_or_none()
    if existing:
        return None
    asset = MediaAsset(
        media_identity=media.media_identity,
        tweet_id=tweet.tweet_id,
        media_type=media.media_type,
        source_url=media.source_url,
    )
    session.add(asset)
    session.flush()
    return asset


def should_process_media(media_type: str, requested_media_type: str) -> bool:
    if requested_media_type == "all":
        return media_type in {"image", "video"}
    if requested_media_type == "images":
        return media_type == "image"
    if requested_media_type == "videos":
        return media_type == "video"
    return False


def reset_author_records(session: Session, handle: str) -> ResetAuthorResult:
    normalized = handle.lstrip("@").strip()
    result = ResetAuthorResult(handle=normalized)

    tweet_ids = list(
        session.execute(
            select(Tweet.tweet_id).where(Tweet.author_handle == normalized)
        ).scalars()
    )

    if tweet_ids:
        media_assets = list(
            session.execute(
                select(MediaAsset).where(MediaAsset.tweet_id.in_(tweet_ids))
            ).scalars()
        )
        result.media_assets = len(media_assets)
        for asset in media_assets:
            session.delete(asset)

        scope_tweets = list(
            session.execute(
                select(ScopeTweet).where(ScopeTweet.tweet_id.in_(tweet_ids))
            ).scalars()
        )
        deleted_scope_tweet_ids = {scope_tweet.id for scope_tweet in scope_tweets}
        result.scope_tweets = len(scope_tweets)
        for scope_tweet in scope_tweets:
            session.delete(scope_tweet)
    else:
        deleted_scope_tweet_ids = set()

    tweets = list(
        session.execute(
            select(Tweet).where(Tweet.tweet_id.in_(tweet_ids))
        ).scalars()
    )
    result.tweets = len(tweets)
    for tweet in tweets:
        session.delete(tweet)

    scope_prefix = f"type=user|publishers={normalized}|"
    scopes = list(
        session.execute(
            select(CrawlScope).where(CrawlScope.scope_key.startswith(scope_prefix))
        ).scalars()
    )
    scope_keys = [scope.scope_key for scope in scopes]
    if scope_keys:
        scoped_links = list(
            session.execute(
                select(ScopeTweet).where(ScopeTweet.scope_key.in_(scope_keys))
            ).scalars()
        )
        scoped_links = [
            scope_tweet
            for scope_tweet in scoped_links
            if scope_tweet.id not in deleted_scope_tweet_ids
        ]
        result.scope_tweets += len(scoped_links)
        for scope_tweet in scoped_links:
            session.delete(scope_tweet)

    result.crawl_scopes = len(scopes)
    for scope in scopes:
        session.delete(scope)

    tasks = list(session.execute(select(CrawlTask)).scalars())
    for task in tasks:
        publishers = {
            publisher.strip()
            for publisher in (task.publishers or "").split(",")
            if publisher.strip()
        }
        if normalized in publishers:
            session.delete(task)
            result.crawl_tasks += 1

    session.commit()
    return result


async def extract_visible_tweets(page: Page) -> list[ExtractedTweet]:
    raw_items = await page.locator("article").evaluate_all(ARTICLE_EXTRACT_SCRIPT)
    return parse_extracted_articles(raw_items)


async def wait_for_visible_media_settle(page: Page, timeout_ms: int = 2500) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    previous_count: int | None = None
    stable_count = 0
    while asyncio.get_running_loop().time() < deadline:
        media_count = await page.locator(
            'article img[src*="pbs.twimg.com/media"], '
            'article img[srcset*="pbs.twimg.com/media"], '
            'article video, '
            'article div[data-testid="videoPlayer"], '
            'article img[src*="ext_tw_video_thumb"], '
            'article img[src*="tweet_video_thumb"]'
        ).count()
        if media_count == previous_count:
            stable_count += 1
            if stable_count >= 2:
                return
        else:
            stable_count = 0
            previous_count = media_count
        await page.wait_for_timeout(350)


def matches_filters(tweet: ExtractedTweet, spec: CrawlSpec) -> bool:
    text = tweet.text.lower()
    if spec.keyword and spec.keyword.lower() not in text:
        return False
    if spec.mentions:
        mention_tokens = {f"@{mention.lower()}" for mention in spec.mentions}
        if not any(token in text for token in mention_tokens):
            return False
    return True


async def wait_for_login_or_articles(page: Page) -> None:
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(2500)
    if await page.locator('input[name="text"]').count() > 0 and await page.locator("article").count() == 0:
        raise RuntimeError("X login appears to be required. Run `x-spider login` first.")
    await page.locator("article").first.wait_for(timeout=30000)
    await wait_for_visible_media_settle(page, timeout_ms=3500)


async def scroll_one_step(page: Page, settings: Settings) -> int:
    step_min = max(1, settings.scroll_step_min_px)
    step_max = max(step_min, settings.scroll_step_max_px)
    pause_min = max(0.0, settings.scroll_pause_min_seconds)
    pause_max = max(pause_min, settings.scroll_pause_max_seconds)

    distance = random.randint(step_min, step_max)
    await page.mouse.wheel(0, distance)
    await asyncio.sleep(random.uniform(pause_min, pause_max))
    return distance


async def current_scroll_y(page: Page) -> int:
    value = await page.evaluate("() => Math.round(window.scrollY)")
    return int(value or 0)


async def run_crawl(
    *,
    page: Page,
    session: Session,
    settings: Settings,
    spec: CrawlSpec,
    url: str,
    max_scrolls: int,
    max_items: int | None,
    no_new_round_limit: int | None = None,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
    video_progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> CrawlResult:
    result = CrawlResult()
    task = CrawlTask(
        task_type=spec.task_type,
        url=url,
        publishers=",".join(spec.publishers) or None,
        mentions=",".join(spec.mentions) or None,
        keyword=spec.keyword,
        media_type=spec.media_type,
        status="running",
    )
    session.add(task)
    scope = ensure_scope(session, spec)
    session.commit()

    try:
        timeout = httpx.Timeout(settings.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            await page.goto(url, wait_until="domcontentloaded")
            await wait_for_login_or_articles(page)

            seen_this_run: set[str] = set()
            matched_this_run: set[str] = set()
            seen_media_this_run: set[str] = set()
            no_new_rounds = 0
            effective_no_new_round_limit = (
                settings.no_new_round_limit if no_new_round_limit is None else no_new_round_limit
            )

            while max_scrolls <= 0 or result.scroll_rounds < max_scrolls:
                result.scroll_rounds += 1
                round_visible_ids: set[str] = set()
                round_new = 0
                round_new_tweets = 0
                round_new_records = 0
                round_matched = 0
                round_media = 0
                round_snapshots = 0
                round_scroll_distance = 0
                round_last_error = ""
                downloaded_before = result.downloaded
                skipped_before = result.skipped
                failed_before = result.failed

                async def process_current_snapshot() -> bool:
                    nonlocal round_media, round_matched, round_new, round_new_tweets
                    nonlocal round_new_records, round_snapshots, round_last_error
                    await wait_for_visible_media_settle(page)
                    tweets = await extract_visible_tweets(page)
                    round_snapshots += 1
                    for tweet in tweets:
                        round_visible_ids.add(tweet.tweet_id)
                        first_seen_in_run = tweet.tweet_id not in seen_this_run
                        if first_seen_in_run:
                            seen_this_run.add(tweet.tweet_id)
                            result.seen_tweets += 1
                            round_new += 1
                            if max_items is not None and result.seen_tweets > max_items:
                                result.stop_reason = f"max_items reached: {max_items}"
                                task.status = "completed"
                                session.commit()
                                return True
                        if not matches_filters(tweet, spec):
                            continue

                        first_matched_in_run = tweet.tweet_id not in matched_this_run
                        if first_matched_in_run:
                            matched_this_run.add(tweet.tweet_id)
                            round_matched += 1
                            inserted_tweet = upsert_tweet(session, tweet)
                            if inserted_tweet:
                                result.new_tweets += 1
                                round_new_tweets += 1
                            inserted_scope_link = link_scope_tweet(
                                session, spec.scope_key, tweet.tweet_id
                            )
                            if inserted_tweet or inserted_scope_link:
                                round_new_records += 1
                            scope.latest_seen_tweet_id = tweet.tweet_id
                            scope.latest_seen_at = utc_now()
                            scope.total_seen += 1
                            task.last_seen_tweet_id = tweet.tweet_id

                        for media in tweet.media:
                            if not should_process_media(media.media_type, spec.media_type):
                                continue
                            if media.media_identity in seen_media_this_run:
                                continue
                            seen_media_this_run.add(media.media_identity)
                            round_media += 1
                            asset = ensure_media_asset(session, tweet, media)
                            if asset is None:
                                if media.media_type == "video" and video_progress_callback:
                                    video_progress_callback(
                                        {
                                            "event": "skip_existing",
                                            "tweet_id": tweet.tweet_id,
                                            "tweet_url": tweet.url,
                                            "media_identity": media.media_identity,
                                        }
                                    )
                                result.skipped += 1
                                continue
                            round_new_records += 1
                            session.commit()
                            try:
                                if media.media_type == "image":
                                    downloaded = await fetch_best_image(client, media.source_url)
                                    local_media_dir = "images"
                                else:
                                    if video_progress_callback:
                                        video_progress_callback(
                                            {
                                                "event": "start",
                                                "tweet_id": tweet.tweet_id,
                                                "tweet_url": media.source_url,
                                                "media_identity": media.media_identity,
                                            }
                                        )
                                    downloaded = await fetch_best_video(
                                        page,
                                        client,
                                        media.source_url,
                                        settings.video_capture_seconds,
                                        progress_callback=video_progress_callback,
                                    )
                                    local_media_dir = "videos"
                                existing_hash = session.execute(
                                    select(MediaAsset).where(
                                        MediaAsset.sha256 == downloaded.sha256,
                                        MediaAsset.id != asset.id,
                                    )
                                ).scalars().first()
                                if existing_hash:
                                    asset.download_status = "skipped_duplicate"
                                    asset.sha256 = downloaded.sha256
                                    asset.best_url = downloaded.best_url
                                    result.skipped += 1
                                else:
                                    download_scope_type, download_scope = download_scope_parts(
                                        spec, tweet.author_handle
                                    )
                                    path = build_local_path(
                                        settings.resolved_download_dir,
                                        download_scope_type,
                                        download_scope,
                                        local_media_dir,
                                        date_for_filename(tweet),
                                        tweet.tweet_id,
                                        tweet.author_handle,
                                        media_id_from_identity(media.media_identity),
                                        downloaded.quality,
                                        downloaded.extension,
                                    )
                                    path.parent.mkdir(parents=True, exist_ok=True)
                                    path.write_bytes(downloaded.content)
                                    asset.best_url = downloaded.best_url
                                    asset.local_path = str(path)
                                    asset.sha256 = downloaded.sha256
                                    asset.width = downloaded.width
                                    asset.height = downloaded.height
                                    asset.duration_ms = getattr(downloaded, "duration_ms", None)
                                    asset.download_status = "downloaded"
                                    scope.total_downloaded += 1
                                    result.downloaded += 1
                                    if media.media_type == "video" and video_progress_callback:
                                        video_progress_callback(
                                            {
                                                "event": "saved",
                                                "tweet_id": tweet.tweet_id,
                                                "quality": downloaded.quality,
                                                "bytes": len(downloaded.content),
                                                "local_path": str(path),
                                            }
                                        )
                            except Exception as exc:
                                asset.download_status = "failed"
                                asset.error = str(exc)
                                round_last_error = str(exc)
                                result.failed += 1
                                if media.media_type == "video" and video_progress_callback:
                                    video_progress_callback(
                                        {
                                            "event": "failed",
                                            "tweet_id": tweet.tweet_id,
                                            "tweet_url": media.source_url,
                                            "error": str(exc),
                                        }
                                    )
                            finally:
                                session.commit()
                    return False

                if await process_current_snapshot():
                    return result

                for _ in range(max(1, settings.scroll_steps_per_round)):
                    round_scroll_distance += await scroll_one_step(page, settings)
                    if await process_current_snapshot():
                        return result

                no_new_rounds = no_new_rounds + 1 if round_new_tweets == 0 else 0
                result.no_new_rounds = no_new_rounds
                task.no_new_rounds = no_new_rounds
                task.last_scroll_position += 1
                session.commit()
                if progress_callback:
                    progress_callback(
                        {
                            "round": result.scroll_rounds,
                            "visible": len(round_visible_ids),
                            "new_visible": round_new,
                            "new_tweets": round_new_tweets,
                            "new_records": round_new_records,
                            "matched": round_matched,
                            "media": round_media,
                            "downloaded": result.downloaded - downloaded_before,
                            "skipped": result.skipped - skipped_before,
                            "failed": result.failed - failed_before,
                            "total_seen": result.seen_tweets,
                            "no_new_rounds": no_new_rounds,
                            "snapshots": round_snapshots,
                            "scroll_y": await current_scroll_y(page),
                            "scroll_distance": round_scroll_distance,
                            "last_error": round_last_error,
                        }
                    )
                if (
                    effective_no_new_round_limit > 0
                    and no_new_rounds >= effective_no_new_round_limit
                ):
                    result.stop_reason = (
                        f"no new tweets for {effective_no_new_round_limit} consecutive rounds"
                    )
                    break

        if not result.stop_reason:
            if max_scrolls <= 0:
                result.stop_reason = "stopped without max_scrolls limit"
            else:
                result.stop_reason = f"max_scrolls reached: {max_scrolls}"
        scope.last_success_at = utc_now()
        task.status = "completed"
        session.commit()
        return result
    except Exception:
        task.status = "failed"
        session.commit()
        raise


def reset_stale_downloads(session: Session) -> int:
    assets = session.execute(
        select(MediaAsset).where(MediaAsset.download_status == "downloading")
    ).scalars()
    count = 0
    for asset in assets:
        asset.download_status = "pending"
        count += 1
    session.commit()
    return count


async def retry_failed_images(session: Session, settings: Settings) -> CrawlResult:
    result = CrawlResult()
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    assets = session.execute(
        select(MediaAsset).where(MediaAsset.download_status.in_(["failed", "pending"]))
    ).scalars()
    async with httpx.AsyncClient(timeout=timeout) as client:
        for asset in assets:
            tweet = session.get(Tweet, asset.tweet_id)
            if not tweet:
                continue
            try:
                downloaded = await fetch_best_image(client, asset.source_url)
                existing_hash = session.execute(
                    select(MediaAsset).where(
                        MediaAsset.sha256 == downloaded.sha256,
                        MediaAsset.id != asset.id,
                    )
                ).scalars().first()
                if existing_hash:
                    asset.download_status = "skipped_duplicate"
                    asset.sha256 = downloaded.sha256
                    result.skipped += 1
                else:
                    pseudo_tweet = ExtractedTweet(
                        tweet_id=tweet.tweet_id,
                        author_handle=tweet.author_handle,
                        text=tweet.text or "",
                        url=tweet.url,
                        published_at=tweet.published_at,
                    )
                    path = build_local_path(
                        settings.resolved_download_dir,
                        "retry",
                        "failed",
                        "images",
                        date_for_filename(pseudo_tweet),
                        tweet.tweet_id,
                        tweet.author_handle,
                        media_id_from_identity(asset.media_identity),
                        downloaded.quality,
                        downloaded.extension,
                    )
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(downloaded.content)
                    asset.best_url = downloaded.best_url
                    asset.local_path = str(path)
                    asset.sha256 = downloaded.sha256
                    asset.width = downloaded.width
                    asset.height = downloaded.height
                    asset.download_status = "downloaded"
                    result.downloaded += 1
            except Exception as exc:
                asset.download_status = "failed"
                asset.error = str(exc)
                result.failed += 1
            finally:
                session.commit()
    return result
