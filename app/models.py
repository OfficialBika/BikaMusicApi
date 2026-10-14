from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class APIKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_owner_created", "owner_telegram_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    owner_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(80), default="default")
    prefix: Mapped[str] = mapped_column(String(32))
    secret_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_count: Mapped[int] = mapped_column(BigInteger, default=0)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60)


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (
        Index("ix_tracks_active_title", "is_active", "title"),
        Index("ix_tracks_active_artist", "is_active", "artist"),
    )

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    artist: Mapped[str] = mapped_column(String(300), default="Unknown artist")
    album: Mapped[str | None] = mapped_column(String(300), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    media_path: Mapped[str] = mapped_column(String(1000), unique=True)
    mime_type: Mapped[str] = mapped_column(String(150), default="application/octet-stream")
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    source_name: Mapped[str] = mapped_column(String(100), default="local")
    rights_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
