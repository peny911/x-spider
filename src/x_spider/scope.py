from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote


def normalize_handle(handle: str) -> str:
    cleaned = handle.strip()
    if cleaned.startswith("@"):
        cleaned = cleaned[1:]
    return cleaned.strip()


def normalize_handles(handles: list[str] | None) -> list[str]:
    if not handles:
        return []
    return sorted({normalize_handle(handle) for handle in handles if normalize_handle(handle)})


def slug_text(text: str | None, fallback: str = "all") -> str:
    if not text:
        return fallback
    allowed = []
    for char in text.strip():
        if char.isalnum() or char in ("_", "-", "."):
            allowed.append(char)
        elif char.isspace():
            allowed.append("_")
    slug = "".join(allowed).strip("_")
    return slug or fallback


@dataclass(frozen=True)
class CrawlSpec:
    task_type: str
    media_type: str = "images"
    publishers: tuple[str, ...] = ()
    mentions: tuple[str, ...] = ()
    keyword: str | None = None

    @property
    def scope_key(self) -> str:
        publishers = ",".join(self.publishers) or "-"
        mentions = ",".join(self.mentions) or "-"
        keyword = self.keyword or "-"
        return (
            f"type={self.task_type}|publishers={publishers}|mentions={mentions}|"
            f"keyword={keyword}|media={self.media_type}"
        )

    @property
    def scope_type(self) -> str:
        if self.task_type == "user":
            return "users"
        if self.mentions:
            return "mentions"
        return "searches"

    @property
    def scope_name(self) -> str:
        if self.task_type == "user" and self.publishers:
            return self.publishers[0]
        if self.mentions:
            return "_".join(self.mentions)
        return f"q_{slug_text(self.keyword)}"


def download_scope_parts(spec: CrawlSpec, tweet_author: str | None = None) -> tuple[str, str]:
    if spec.mentions:
        model = "_".join(spec.mentions)
        author = "_".join(spec.publishers) or normalize_handle(tweet_author or "")
        if author:
            return "users", f"{model}/{author}"
        return "users", model
    if spec.task_type == "user" and spec.publishers:
        return "users", spec.publishers[0]
    return spec.scope_type, spec.scope_name


def download_scope_name(spec: CrawlSpec, tweet_author: str | None = None) -> str:
    scope_type, scope_name = download_scope_parts(spec, tweet_author)
    return f"{scope_type}/{scope_name}" if scope_name else scope_type


def media_filter(media_type: str) -> str:
    if media_type == "images":
        return "filter:images"
    if media_type == "videos":
        return "filter:videos"
    return "filter:media"


def build_search_url(spec: CrawlSpec, search_tab: str = "top") -> str:
    terms: list[str] = []
    for publisher in spec.publishers:
        terms.append(f"from:{publisher}")
    if spec.mentions:
        mention_terms = [f"@{mention}" for mention in spec.mentions]
        mention_query = " OR ".join(mention_terms)
        if len(mention_terms) > 1:
            mention_query = f"({mention_query})"
        terms.append(mention_query)
    if spec.keyword:
        terms.append(spec.keyword)
    terms.append(media_filter(spec.media_type))
    query = quote(" ".join(terms))
    url = f"https://x.com/search?q={query}&src=typed_query"
    if search_tab == "latest":
        url += "&f=live"
    return url


def build_user_url(handle: str) -> str:
    return f"https://x.com/{normalize_handle(handle)}"
