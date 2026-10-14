import asyncio
from urllib.parse import parse_qsl, urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import settings
from app.db import SessionLocal, engine, init_db
from app.main import app
from app.models import APIKey, Track
from app.security import hash_secret


KEY_ID = "ab12cd34ef56"
KEY_SECRET = "test_secret_with_enough_characters_0123456789abcdef"
TOKEN = f"bika_live_{KEY_ID}_{KEY_SECRET}"
TRACK_ID = "0123456789abcdef01234567"
MEDIA_NAME = "__ci_test_audio__.mp3"


def seed_database() -> None:
    async def seed() -> None:
        await init_db()
        async with SessionLocal() as session:
            await session.execute(delete(Track))
            await session.execute(delete(APIKey))
            session.add(
                APIKey(
                    id=KEY_ID,
                    owner_telegram_id=123456789,
                    name="test",
                    prefix=f"bika_live_{KEY_ID}",
                    secret_hash=hash_secret(KEY_SECRET),
                    request_count=0,
                    rate_limit_per_minute=60,
                )
            )
            session.add(
                Track(
                    id=TRACK_ID,
                    title="Moon Song",
                    artist="Bika Artist",
                    album="Test Album",
                    duration_seconds=12.5,
                    media_path=MEDIA_NAME,
                    mime_type="audio/mpeg",
                    file_size=len(b"test-audio-bytes"),
                    source_name="test",
                    is_active=True,
                )
            )
            await session.commit()
        # Do not carry pooled SQLite connections into TestClient's event loop.
        await engine.dispose()

    asyncio.run(seed())


def test_catalog_auth_metadata_and_signed_stream() -> None:
    settings.media_root.mkdir(parents=True, exist_ok=True)
    media_path = settings.media_root / MEDIA_NAME
    media_path.write_bytes(b"test-audio-bytes")
    seed_database()

    try:
        with TestClient(app) as client:
            assert client.get("/health/live").status_code == 200
            assert client.get("/health/ready").status_code == 200
            assert client.get("/v1/search", params={"q": "Moon"}).status_code == 401

            headers = {"X-API-Key": TOKEN}
            search = client.get("/v1/search", params={"q": "Moon"}, headers=headers)
            assert search.status_code == 200
            result = search.json()
            assert result["count"] == 1
            assert result["items"][0]["id"] == TRACK_ID
            assert result["items"][0]["title"] == "Moon Song"
            assert "media_path" not in result["items"][0]

            metadata = client.get(f"/v1/tracks/{TRACK_ID}", headers=headers)
            assert metadata.status_code == 200
            assert metadata.json()["artist"] == "Bika Artist"

            playback = client.get(f"/v1/tracks/{TRACK_ID}/playback", headers=headers)
            assert playback.status_code == 200
            data = playback.json()
            assert 1 <= data["expires_in"] <= 3600
            parts = urlsplit(data["url"])
            stream = client.get(parts.path, params=dict(parse_qsl(parts.query)))
            assert stream.status_code == 200
            assert stream.content == b"test-audio-bytes"
    finally:
        media_path.unlink(missing_ok=True)
        asyncio.run(engine.dispose())
