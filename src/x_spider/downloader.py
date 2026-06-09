from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from x_spider.scope import slug_text


IMAGE_QUALITIES = ("orig", "4096x4096", "large", "medium", "small")
MIN_DIRECT_VIDEO_BYTES = 64 * 1024


@dataclass(frozen=True)
class DownloadedImage:
    best_url: str
    quality: str
    content: bytes
    sha256: str
    extension: str
    width: int | None
    height: int | None


@dataclass(frozen=True)
class VideoCandidate:
    url: str
    width: int | None
    height: int | None
    content_length: int | None = None
    source: str = "mp4"


@dataclass(frozen=True)
class HlsVariant:
    url: str
    bandwidth: int | None
    width: int | None
    height: int | None


@dataclass(frozen=True)
class DownloadedVideo:
    best_url: str
    quality: str
    content: bytes
    sha256: str
    extension: str
    width: int | None
    height: int | None
    duration_ms: int | None


def build_best_image_urls(url: str) -> list[tuple[str, str]]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    candidates: list[tuple[str, str]] = []
    for quality in IMAGE_QUALITIES:
        next_query = dict(query)
        next_query["name"] = [quality]
        encoded = urlencode(next_query, doseq=True)
        candidates.append((urlunparse(parsed._replace(query=encoded)), quality))
    candidates.append((url, "source"))
    return list(dict.fromkeys(candidates))


def extension_from_url_or_content_type(url: str, content_type: str | None) -> str:
    query = parse_qs(urlparse(url).query)
    if query.get("format"):
        fmt = query["format"][0].lower()
        if fmt == "jpeg":
            fmt = "jpg"
        return f".{fmt}"

    media_type = (content_type or "").split(";")[0].lower()
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    return mapping.get(media_type, ".jpg")


def image_size(content: bytes) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(BytesIO(content)) as image:
            return image.size
    except Exception:
        return None, None


async def fetch_best_image(client: Any, source_url: str) -> DownloadedImage:
    last_error: Exception | None = None
    for candidate_url, quality in build_best_image_urls(source_url):
        try:
            response = await client.get(candidate_url, follow_redirects=True)
            content_type = response.headers.get("content-type", "")
            if response.status_code != 200 or not content_type.startswith("image/"):
                continue
            content = response.content
            width, height = image_size(content)
            return DownloadedImage(
                best_url=str(response.url),
                quality=quality,
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
                extension=extension_from_url_or_content_type(str(response.url), content_type),
                width=width,
                height=height,
            )
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"failed to fetch image: {last_error or source_url}")


def video_size_from_url(url: str) -> tuple[int | None, int | None]:
    match = re.search(r"/(\d+)x(\d+)(?:/|$)", url)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def is_video_mp4_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("video.twimg.com") and parsed.path.endswith(".mp4")


def is_video_playlist_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("video.twimg.com") and parsed.path.endswith(".m3u8")


def video_quality_label(width: int | None, height: int | None) -> str:
    if width and height:
        return f"{width}x{height}"
    return "mp4"


def emit_video_event(
    callback: Callable[[dict[str, object]], None] | None,
    event: str,
    **values: object,
) -> None:
    if callback:
        callback({"event": event, **values})


async def collect_video_urls_from_tweet(
    page: Any,
    tweet_url: str,
    capture_seconds: float,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> set[str]:
    urls: set[str] = set()
    detail_page = await page.context.new_page()

    def remember(url: str) -> None:
        if "video.twimg.com" in url:
            urls.add(url)

    detail_page.on("response", lambda response: remember(response.url))
    try:
        emit_video_event(
            progress_callback,
            "open_detail",
            tweet_url=tweet_url,
            capture_seconds=capture_seconds,
        )
        await detail_page.goto(tweet_url, wait_until="domcontentloaded")
        await detail_page.wait_for_timeout(1500)
        selectors = [
            'div[data-testid="videoPlayer"]',
            'div[data-testid="playButton"]',
            'button[aria-label*="Play"]',
            "video",
        ]
        clicked_selector = ""
        for selector in selectors:
            locator = detail_page.locator(selector).first
            try:
                if await locator.count() > 0:
                    await locator.click(timeout=1500, force=True)
                    clicked_selector = selector
                    break
            except Exception:
                continue
        emit_video_event(
            progress_callback,
            "player_click",
            selector=clicked_selector or "-",
        )
        try:
            await detail_page.keyboard.press("k")
        except Exception:
            pass
        await detail_page.wait_for_timeout(max(0, int(capture_seconds * 1000)))
        try:
            performance_urls = await detail_page.evaluate(
                "() => performance.getEntriesByType('resource').map(entry => entry.name)"
            )
            for url in performance_urls:
                remember(str(url))
        except Exception:
            pass
        emit_video_event(
            progress_callback,
            "capture_done",
            total_urls=len(urls),
            mp4_urls=len([url for url in urls if is_video_mp4_url(url)]),
            playlist_urls=len([url for url in urls if is_video_playlist_url(url)]),
        )
    finally:
        await detail_page.close()
    return urls


async def with_video_content_length(client: Any, url: str) -> VideoCandidate:
    width, height = video_size_from_url(url)
    try:
        response = await client.head(url, follow_redirects=True)
        content_length = response.headers.get("content-length")
        return VideoCandidate(
            url=str(response.url),
            width=width,
            height=height,
            content_length=int(content_length) if content_length else None,
        )
    except Exception:
        return VideoCandidate(url=url, width=width, height=height)


def video_candidate_score(candidate: VideoCandidate) -> tuple[int, int, int]:
    pixels = (candidate.width or 0) * (candidate.height or 0)
    content_length = candidate.content_length or 0
    known_size = 1 if pixels else 0
    return known_size, pixels, content_length


def parse_m3u8_attributes(value: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for match in re.finditer(r'([A-Z0-9-]+)=("[^"]+"|[^,]+)', value):
        raw = match.group(2)
        attributes[match.group(1)] = raw[1:-1] if raw.startswith('"') and raw.endswith('"') else raw
    return attributes


def parse_resolution(value: str | None) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    match = re.match(r"(\d+)x(\d+)", value)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def parse_hls_variants(master_url: str, content: str) -> list[HlsVariant]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    variants: list[HlsVariant] = []
    for index, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF:") or index + 1 >= len(lines):
            continue
        next_line = lines[index + 1]
        if next_line.startswith("#"):
            continue
        attributes = parse_m3u8_attributes(line.split(":", 1)[1])
        width, height = parse_resolution(attributes.get("RESOLUTION"))
        bandwidth = attributes.get("BANDWIDTH") or attributes.get("AVERAGE-BANDWIDTH")
        variants.append(
            HlsVariant(
                url=urljoin(master_url, next_line),
                bandwidth=int(bandwidth) if bandwidth and bandwidth.isdigit() else None,
                width=width,
                height=height,
            )
        )
    return variants


def hls_variant_score(variant: HlsVariant) -> tuple[int, int, int]:
    pixels = (variant.width or 0) * (variant.height or 0)
    bandwidth = variant.bandwidth or 0
    known_size = 1 if pixels else 0
    return known_size, pixels, bandwidth


def parse_hls_segments(playlist_url: str, content: str) -> list[str]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    urls: list[str] = []
    for line in lines:
        if line.startswith("#EXT-X-MAP:"):
            attributes = parse_m3u8_attributes(line.split(":", 1)[1])
            uri = attributes.get("URI")
            if uri:
                urls.append(urljoin(playlist_url, uri))
        elif not line.startswith("#"):
            urls.append(urljoin(playlist_url, line))
    return urls


async def fetch_text(client: Any, url: str) -> tuple[str, str]:
    response = await client.get(url, follow_redirects=True)
    if response.status_code != 200:
        raise RuntimeError(f"failed to fetch playlist: HTTP {response.status_code}")
    return str(response.url), response.text


async def fetch_hls_video(
    client: Any,
    playlist_urls: list[str],
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> DownloadedVideo:
    last_error: Exception | None = None
    for playlist_url in playlist_urls:
        try:
            final_master_url, master_content = await fetch_text(client, playlist_url)
            variants = parse_hls_variants(final_master_url, master_content)
            if variants:
                for variant in sorted(variants, key=hls_variant_score, reverse=True):
                    emit_video_event(
                        progress_callback,
                        "hls_variant",
                        url=variant.url,
                        quality=video_quality_label(variant.width, variant.height),
                        bandwidth=variant.bandwidth or 0,
                    )
                best_variant = max(variants, key=hls_variant_score)
                media_playlist_url = best_variant.url
                width = best_variant.width
                height = best_variant.height
                quality = video_quality_label(width, height)
            else:
                media_playlist_url = final_master_url
                width, height = video_size_from_url(final_master_url)
                quality = video_quality_label(width, height)

            final_playlist_url, playlist_content = await fetch_text(client, media_playlist_url)
            segment_urls = parse_hls_segments(final_playlist_url, playlist_content)
            if not segment_urls:
                raise RuntimeError("HLS playlist has no media segments")

            emit_video_event(
                progress_callback,
                "hls_select",
                url=media_playlist_url,
                quality=quality,
                segments=len(segment_urls),
            )
            parts: list[bytes] = []
            for segment_url in segment_urls:
                response = await client.get(segment_url, follow_redirects=True)
                if response.status_code != 200:
                    raise RuntimeError(
                        f"failed to fetch HLS segment: HTTP {response.status_code}"
                    )
                parts.append(response.content)
            content = b"".join(parts)
            emit_video_event(
                progress_callback,
                "hls_downloaded",
                url=media_playlist_url,
                quality=quality,
                segments=len(segment_urls),
                bytes=len(content),
            )
            return DownloadedVideo(
                best_url=media_playlist_url,
                quality=quality,
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
                extension=".mp4",
                width=width,
                height=height,
                duration_ms=None,
            )
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"failed to fetch HLS video: {last_error}")


async def fetch_best_video(
    page: Any,
    client: Any,
    tweet_url: str,
    capture_seconds: float,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> DownloadedVideo:
    urls = await collect_video_urls_from_tweet(
        page,
        tweet_url,
        capture_seconds,
        progress_callback=progress_callback,
    )
    mp4_urls = sorted({url for url in urls if is_video_mp4_url(url)})
    playlist_urls = sorted({url for url in urls if is_video_playlist_url(url)})
    if playlist_urls:
        return await fetch_hls_video(client, playlist_urls, progress_callback=progress_callback)
    if not mp4_urls:
        raise RuntimeError("no downloadable mp4 video URL found")

    candidates = [await with_video_content_length(client, url) for url in mp4_urls]
    for candidate in sorted(candidates, key=video_candidate_score, reverse=True):
        emit_video_event(
            progress_callback,
            "candidate",
            url=candidate.url,
            quality=video_quality_label(candidate.width, candidate.height),
            content_length=candidate.content_length or 0,
        )
    best = max(candidates, key=video_candidate_score)
    if best.content_length is not None and best.content_length < MIN_DIRECT_VIDEO_BYTES:
        raise RuntimeError(
            f"direct mp4 candidate is too small to be a complete video: {best.content_length} bytes"
        )
    emit_video_event(
        progress_callback,
        "select",
        url=best.url,
        quality=video_quality_label(best.width, best.height),
        content_length=best.content_length or 0,
    )
    response = await client.get(best.url, follow_redirects=True)
    content_type = response.headers.get("content-type", "")
    if response.status_code != 200 or (
        "video/" not in content_type and not is_video_mp4_url(str(response.url))
    ):
        raise RuntimeError(f"failed to fetch video: HTTP {response.status_code}")
    width, height = video_size_from_url(str(response.url))
    width = width or best.width
    height = height or best.height
    content = response.content
    emit_video_event(
        progress_callback,
        "download_response",
        url=str(response.url),
        status_code=response.status_code,
        content_type=content_type or "-",
        bytes=len(content),
    )
    return DownloadedVideo(
        best_url=str(response.url),
        quality=video_quality_label(width, height),
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        extension=".mp4",
        width=width,
        height=height,
        duration_ms=None,
    )


def build_local_path(
    download_dir: Path,
    scope_type: str,
    scope_name: str,
    media_type: str,
    tweet_date: str,
    tweet_id: str,
    publisher: str | None,
    media_id: str,
    quality: str,
    extension: str,
) -> Path:
    safe_publisher = slug_text(publisher, "unknown")
    safe_scope_parts = [
        slug_text(part, "default")
        for part in scope_name.split("/")
        if slug_text(part, "")
    ]
    safe_scope = Path(*safe_scope_parts) if safe_scope_parts else Path("default")
    safe_media = slug_text(media_id, "media")
    filename = (
        f"{tweet_date}_{tweet_id}_{safe_publisher}_{safe_media}_{quality}{extension}"
    )
    if safe_scope_parts:
        return download_dir / scope_type / safe_scope / media_type / filename
    return download_dir / scope_type / media_type / filename
