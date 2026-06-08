from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse


@dataclass(frozen=True)
class ExtractedMedia:
    media_type: str
    source_url: str
    media_identity: str


@dataclass(frozen=True)
class ExtractedTweet:
    tweet_id: str
    author_handle: str | None
    text: str
    url: str
    published_at: datetime | None
    media: tuple[ExtractedMedia, ...] = field(default_factory=tuple)


def extract_tweet_id_from_url(url: str) -> str | None:
    parts = [part for part in urlparse(url).path.split("/") if part]
    for index, part in enumerate(parts):
        if part == "status" and index + 1 < len(parts):
            candidate = parts[index + 1]
            if candidate.isdigit():
                return candidate
    return None


def extract_handle_from_url(url: str) -> str | None:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) >= 3 and parts[1] == "status":
        return parts[0]
    return None


def image_identity(url: str) -> str:
    parsed = urlparse(url)
    return f"image:{parsed.netloc}{parsed.path}"


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def parse_extracted_articles(raw_items: list[dict]) -> list[ExtractedTweet]:
    tweets: list[ExtractedTweet] = []
    seen: set[str] = set()
    for item in raw_items:
        status_url = item.get("statusUrl")
        if not status_url:
            continue
        tweet_id = extract_tweet_id_from_url(status_url)
        if not tweet_id or tweet_id in seen:
            continue

        image_urls = item.get("imageUrls") or []
        media = tuple(
            ExtractedMedia(media_type="image", source_url=url, media_identity=image_identity(url))
            for url in image_urls
            if "pbs.twimg.com/media" in url
        )
        if not media:
            continue

        seen.add(tweet_id)
        tweets.append(
            ExtractedTweet(
                tweet_id=tweet_id,
                author_handle=item.get("authorHandle") or extract_handle_from_url(status_url),
                text=item.get("text") or "",
                url=status_url,
                published_at=parse_datetime(item.get("publishedAt")),
                media=media,
            )
        )
    return tweets


ARTICLE_EXTRACT_SCRIPT = """
articles => articles.map(article => {
  const links = Array.from(article.querySelectorAll('a[href*="/status/"]'));
  const statusLink = links.find(a => /\\/status\\/\\d+/.test(a.getAttribute('href') || ''));
  const statusHref = statusLink ? statusLink.href : null;

  const timeEl = article.querySelector('time');
  const imageUrls = Array.from(article.querySelectorAll('img[src*="pbs.twimg.com/media"]'))
    .map(img => img.currentSrc || img.src)
    .filter(Boolean);

  let authorHandle = null;
  if (statusHref) {
    const parts = new URL(statusHref).pathname.split('/').filter(Boolean);
    if (parts.length >= 3 && parts[1] === 'status') authorHandle = parts[0];
  }

  return {
    statusUrl: statusHref,
    authorHandle,
    text: article.innerText || '',
    publishedAt: timeEl ? timeEl.getAttribute('datetime') : null,
    imageUrls: Array.from(new Set(imageUrls)),
  };
})
"""

