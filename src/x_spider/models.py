from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from x_spider.db import Base


def utc_now() -> datetime:
    return datetime.utcnow()


class CrawlTask(Base):
    __tablename__ = "crawl_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_type: Mapped[str] = mapped_column(String(32), index=True)
    url: Mapped[str] = mapped_column(Text)
    publishers: Mapped[str | None] = mapped_column(Text)
    mentions: Mapped[str | None] = mapped_column(Text)
    keyword: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(16), default="images")
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    last_seen_tweet_id: Mapped[str | None] = mapped_column(String(64))
    last_scroll_position: Mapped[int] = mapped_column(Integer, default=0)
    no_new_rounds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class Tweet(Base):
    __tablename__ = "tweets"

    tweet_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    author_handle: Mapped[str | None] = mapped_column(String(64), index=True)
    text: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    raw_json: Mapped[str | None] = mapped_column(Text)

    media_assets: Mapped[list[MediaAsset]] = relationship(back_populates="tweet")


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_identity: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    tweet_id: Mapped[str] = mapped_column(ForeignKey("tweets.tweet_id"), index=True)
    media_type: Mapped[str] = mapped_column(String(16), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    best_url: Mapped[str | None] = mapped_column(Text)
    local_path: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    download_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    tweet: Mapped[Tweet] = relationship(back_populates="media_assets")


class CrawlScope(Base):
    __tablename__ = "crawl_scopes"

    scope_key: Mapped[str] = mapped_column(String(1024), primary_key=True)
    latest_seen_tweet_id: Mapped[str | None] = mapped_column(String(64))
    latest_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    total_seen: Mapped[int] = mapped_column(Integer, default=0)
    total_downloaded: Mapped[int] = mapped_column(Integer, default=0)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)


class ScopeTweet(Base):
    __tablename__ = "scope_tweets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope_key: Mapped[str] = mapped_column(ForeignKey("crawl_scopes.scope_key"), index=True)
    tweet_id: Mapped[str] = mapped_column(ForeignKey("tweets.tweet_id"), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (UniqueConstraint("scope_key", "tweet_id", name="uq_scope_tweets_scope_tweet"),)
