from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import random
import httpx
from playwright.async_api import Page
from sqlalchemy import select
from sqlalchemy.orm import Session

from x_spider.config import Settings
from x_spider.downloader import build_local_path, fetch_best_image
from x_spider.extractor import ARTICLE_EXTRACT_SCRIPT, ExtractedTweet, parse_extracted_articles
from x_spider.models import CrawlScope, CrawlTask, MediaAsset, ScopeTweet, Tweet, utc_now
from x_spider.scope import CrawlSpec


@dataclass
class CrawlResult:
    seen_tweets: int = 0
    new_tweets: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0


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


def link_scope_tweet(session: Session, scope_key: str, tweet_id: str) -> None:
    exists = session.execute(
        select(ScopeTweet).where(
            ScopeTweet.scope_key == scope_key,
            ScopeTweet.tweet_id == tweet_id,
        )
    ).scalar_one_or_none()
    if not exists:
        session.add(ScopeTweet(scope_key=scope_key, tweet_id=tweet_id))
        session.flush()


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


async def extract_visible_tweets(page: Page) -> list[ExtractedTweet]:
    raw_items = await page.locator("article").evaluate_all(ARTICLE_EXTRACT_SCRIPT)
    return parse_extracted_articles(raw_items)


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


async def segmented_scroll(page: Page, settings: Settings) -> None:
    step_min = max(1, settings.scroll_step_min_px)
    step_max = max(step_min, settings.scroll_step_max_px)
    pause_min = max(0.0, settings.scroll_pause_min_seconds)
    pause_max = max(pause_min, settings.scroll_pause_max_seconds)
    steps = max(1, settings.scroll_steps_per_round)

    for _ in range(steps):
        distance = random.randint(step_min, step_max)
        await page.mouse.wheel(0, distance)
        await asyncio.sleep(random.uniform(pause_min, pause_max))


async def run_crawl(
    *,
    page: Page,
    session: Session,
    settings: Settings,
    spec: CrawlSpec,
    url: str,
    max_scrolls: int,
    max_items: int | None,
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
            no_new_rounds = 0

            for _ in range(max_scrolls):
                tweets = await extract_visible_tweets(page)
                round_new = 0
                for tweet in tweets:
                    if tweet.tweet_id in seen_this_run:
                        continue
                    seen_this_run.add(tweet.tweet_id)
                    result.seen_tweets += 1
                    if max_items is not None and result.seen_tweets > max_items:
                        task.status = "completed"
                        session.commit()
                        return result
                    if not matches_filters(tweet, spec):
                        continue

                    if upsert_tweet(session, tweet):
                        result.new_tweets += 1
                    link_scope_tweet(session, spec.scope_key, tweet.tweet_id)
                    scope.latest_seen_tweet_id = tweet.tweet_id
                    scope.latest_seen_at = utc_now()
                    scope.total_seen += 1
                    task.last_seen_tweet_id = tweet.tweet_id
                    round_new += 1

                    for media in tweet.media:
                        if spec.media_type == "videos":
                            continue
                        asset = ensure_media_asset(session, tweet, media)
                        if asset is None:
                            result.skipped += 1
                            continue
                        session.commit()
                        try:
                            downloaded = await fetch_best_image(client, media.source_url)
                            existing_hash = session.execute(
                                select(MediaAsset).where(
                                    MediaAsset.sha256 == downloaded.sha256,
                                    MediaAsset.id != asset.id,
                                )
                            ).scalar_one_or_none()
                            if existing_hash:
                                asset.download_status = "skipped_duplicate"
                                asset.sha256 = downloaded.sha256
                                asset.best_url = downloaded.best_url
                                result.skipped += 1
                            else:
                                path = build_local_path(
                                    settings.resolved_download_dir,
                                    spec.scope_type,
                                    spec.scope_name,
                                    "images",
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
                                asset.download_status = "downloaded"
                                scope.total_downloaded += 1
                                result.downloaded += 1
                        except Exception as exc:
                            asset.download_status = "failed"
                            asset.error = str(exc)
                            result.failed += 1
                        finally:
                            session.commit()

                no_new_rounds = no_new_rounds + 1 if round_new == 0 else 0
                task.no_new_rounds = no_new_rounds
                task.last_scroll_position += 1
                session.commit()
                if no_new_rounds >= settings.no_new_round_limit:
                    break
                await segmented_scroll(page, settings)

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
                ).scalar_one_or_none()
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
