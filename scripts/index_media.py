import asyncio
import hashlib
import mimetypes
from pathlib import Path

from mutagen import File as MutagenFile
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, engine, init_db
from app.models import Track, utc_now


AUDIO_EXTENSIONS = {
    ".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus",
    ".wav", ".weba", ".webm", ".mp4", ".aiff", ".wma",
}


def first_tag(audio, key: str) -> str | None:
    try:
        value = audio.get(key)
        if not value:
            return None
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        return str(value).strip()[:300] if value else None
    except Exception:
        return None


def metadata_for(path: Path) -> tuple[str, str, str | None, float | None]:
    title = path.stem[:300]
    artist = "Unknown artist"
    album = None
    duration = None
    try:
        audio = MutagenFile(path, easy=True)
        if audio is not None:
            title = first_tag(audio, "title") or title
            artist = first_tag(audio, "artist") or artist
            album = first_tag(audio, "album")
            info = getattr(audio, "info", None)
            length = getattr(info, "length", None) if info else None
            duration = float(length) if length is not None else None
    except Exception:
        # Untagged or unsupported metadata does not prevent catalog indexing.
        pass
    return title, artist, album, duration


async def main() -> None:
    root = settings.media_root.resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"MEDIA_ROOT is not a directory: {root}")

    await init_db()
    seen = 0
    async with SessionLocal() as session:
        candidates = sorted(root.rglob("*"))
        for path in candidates:
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                continue
            relative = path.relative_to(root).as_posix()
            track_id = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24]
            title, artist, album, duration = metadata_for(path)
            mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            row = await session.scalar(select(Track).where(Track.media_path == relative))
            fields = {
                "title": title,
                "artist": artist,
                "album": album,
                "duration_seconds": duration,
                "media_path": relative,
                "mime_type": mime_type,
                "file_size": path.stat().st_size,
                "source_name": "local",
                "updated_at": utc_now(),
                "is_active": True,
            }
            if row is None:
                row = Track(id=track_id, **fields)
                session.add(row)
            else:
                for name, value in fields.items():
                    setattr(row, name, value)
            seen += 1
        await session.commit()
    await engine.dispose()
    print(f"Indexed {seen} authorized local audio file(s) from {root}.")
    print("Only import audio you own, licensed, or otherwise have permission to stream.")


if __name__ == "__main__":
    asyncio.run(main())
