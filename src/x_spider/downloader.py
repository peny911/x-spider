from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from x_spider.scope import slug_text


IMAGE_QUALITIES = ("orig", "4096x4096", "large", "medium", "small")


@dataclass(frozen=True)
class DownloadedImage:
    best_url: str
    quality: str
    content: bytes
    sha256: str
    extension: str
    width: int | None
    height: int | None


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
    safe_scope = slug_text(scope_name, "default")
    safe_media = slug_text(media_id, "media")
    filename = (
        f"{tweet_date}_{tweet_id}_{safe_publisher}_{safe_media}_{quality}{extension}"
    )
    return download_dir / scope_type / safe_scope / media_type / filename
