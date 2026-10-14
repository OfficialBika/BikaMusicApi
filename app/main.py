import hmac
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import engine, get_session, init_db
from app.limiter import close_limiter, enforce_rate_limit, init_limiter
from app.models import APIKey, Track, utc_now
from app.schemas import PlaybackResponse, SearchResponse, TrackSummary
from app.security import hash_secret, parse_api_key, sign_playback, verify_playback_signature


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("bika_music_api")


def validate_runtime_config() -> None:
    if settings.rate_limit_per_minute < 1:
        raise RuntimeError("RATE_LIMIT_PER_MINUTE must be positive.")
    if not 1 <= settings.playback_url_ttl_seconds <= 3600:
        raise RuntimeError("PLAYBACK_URL_TTL_SECONDS must be between 1 and 3600.")
    if settings.is_production:
        for name, value in (
            ("API_KEY_PEPPER", settings.api_key_pepper),
            ("PLAYBACK_SIGNING_SECRET", settings.playback_signing_secret),
        ):
            if (
                len(value) < 32
                or "replace" in value.lower()
                or "change-this" in value.lower()
                or "example" in value.lower()
            ):
                raise RuntimeError(f"{name} must be replaced with a strong random secret.")
        if settings.api_key_pepper == settings.playback_signing_secret:
            raise RuntimeError("API_KEY_PEPPER and PLAYBACK_SIGNING_SECRET must differ.")
        if not settings.database_url.startswith("postgresql+asyncpg://"):
            raise RuntimeError("Production must use PostgreSQL with asyncpg.")
        if not settings.redis_url:
            raise RuntimeError("Production requires REDIS_URL for shared rate limiting.")
        if not settings.public_api_base_url.startswith("https://"):
            raise RuntimeError("Production PUBLIC_API_BASE_URL must use HTTPS.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_runtime_config()
    settings.media_root.mkdir(parents=True, exist_ok=True)
    await init_db()
    await init_limiter()
    logger.info("Bika Music API startup complete; environment=%s", settings.app_env)
    try:
        yield
    finally:
        await close_limiter()
        await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "API for an authorized local audio catalog. API keys are managed through the "
        "Telegram bot; raw keys are displayed once and are never stored."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="A valid API key is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def is_expired(value: datetime | None) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= datetime.now(timezone.utc)


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: AsyncSession = Depends(get_session),
) -> APIKey:
    token = x_api_key
    if not token and authorization:
        scheme, _, credential = authorization.partition(" ")
        if scheme.lower() == "bearer" and credential:
            token = credential.strip()
    parsed = parse_api_key(token)
    if parsed is None:
        raise unauthorized()

    key_id, secret = parsed
    api_key = await session.get(APIKey, key_id)
    if (
        api_key is None
        or api_key.revoked_at is not None
        or is_expired(api_key.expires_at)
    ):
        raise unauthorized()
    try:
        candidate_hash = hash_secret(secret)
    except RuntimeError as exc:
        logger.error("API key pepper is not configured securely.")
        raise HTTPException(status_code=503, detail="API authentication is not configured.") from exc

    if not hmac.compare_digest(api_key.secret_hash, candidate_hash):
        raise unauthorized()

    await enforce_rate_limit(f"key:{api_key.id}", api_key.rate_limit_per_minute)
    await session.execute(
        update(APIKey)
        .where(APIKey.id == api_key.id)
        .values(
            request_count=APIKey.request_count + 1,
            last_used_at=utc_now(),
        )
    )
    await session.commit()
    request.state.api_key_id = api_key.id
    return api_key


def safe_media_path(media_path: str) -> Path:
    root = settings.media_root.resolve()
    candidate = (root / media_path).resolve(strict=True)
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise FileNotFoundError("Media file is outside the configured media root.")
    return candidate


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@app.get("/health/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    try:
        await session.execute(select(1))
    except Exception as exc:
        logger.warning("Readiness check failed: database unavailable")
        raise HTTPException(status_code=503, detail="Database unavailable.") from exc
    return {"status": "ready"}


@app.get("/v1", tags=["service"])
async def api_info() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "docs": f"{settings.public_api_base_url.rstrip('/')}/docs",
        "catalog": "authorized-local-audio",
    }


@app.get("/v1/search", response_model=SearchResponse, tags=["catalog"])
async def search_tracks(
    q: str = Query(min_length=1, max_length=200, description="Track title or artist"),
    limit: int = Query(default=10, ge=1, le=50),
    _: APIKey = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
) -> SearchResponse:
    term = escape_like(q.strip())
    if not term:
        raise HTTPException(status_code=422, detail="Search query cannot be blank.")
    pattern = f"%{term}%"
    statement = (
        select(Track)
        .where(
            Track.is_active.is_(True),
            or_(
                Track.title.ilike(pattern, escape="\\"),
                Track.artist.ilike(pattern, escape="\\"),
                Track.album.ilike(pattern, escape="\\"),
            ),
        )
        .order_by(Track.title.asc())
        .limit(limit)
    )
    tracks = list((await session.scalars(statement)).all())
    return SearchResponse(
        query=q.strip(),
        count=len(tracks),
        items=[TrackSummary.model_validate(track) for track in tracks],
    )


@app.get("/v1/tracks/{track_id}", response_model=TrackSummary, tags=["catalog"])
async def get_track(
    track_id: str,
    _: APIKey = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
) -> TrackSummary:
    track = await session.get(Track, track_id)
    if track is None or not track.is_active:
        raise HTTPException(status_code=404, detail="Track not found.")
    return TrackSummary.model_validate(track)


@app.get("/v1/tracks/{track_id}/playback", response_model=PlaybackResponse, tags=["playback"])
async def create_playback_url(
    track_id: str,
    api_key: APIKey = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
) -> PlaybackResponse:
    track = await session.get(Track, track_id)
    if track is None or not track.is_active:
        raise HTTPException(status_code=404, detail="Track not found.")

    try:
        safe_media_path(track.media_path)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="Audio file is not available.")

    expires_at = int(datetime.now(timezone.utc).timestamp()) + settings.playback_url_ttl_seconds
    signature = sign_playback(track.id, api_key.id, expires_at)
    base_url = settings.public_api_base_url.rstrip("/")
    query = urlencode({"kid": api_key.id, "exp": expires_at, "sig": signature})
    url = f"{base_url}/v1/streams/{track.id}?{query}"
    return PlaybackResponse(
        track=TrackSummary.model_validate(track),
        url=url,
        expires_in=settings.playback_url_ttl_seconds,
    )


@app.get("/v1/streams/{track_id}", tags=["playback"], include_in_schema=True)
async def stream_track(
    track_id: str,
    kid: str = Query(min_length=12, max_length=12),
    exp: int = Query(ge=1),
    sig: str = Query(min_length=64, max_length=64),
    session: AsyncSession = Depends(get_session),
):
    if not verify_playback_signature(track_id, kid, exp, sig, max_ttl_seconds=3600):
        raise HTTPException(status_code=403, detail="Playback URL is invalid or expired.")

    api_key = await session.get(APIKey, kid)
    if (
        api_key is None
        or api_key.revoked_at is not None
        or is_expired(api_key.expires_at)
    ):
        raise HTTPException(status_code=403, detail="Playback authorization has been revoked.")

    await enforce_rate_limit(f"stream:{api_key.id}", max(1, api_key.rate_limit_per_minute * 2))
    track = await session.get(Track, track_id)
    if track is None or not track.is_active:
        raise HTTPException(status_code=404, detail="Track not found.")

    try:
        path = safe_media_path(track.media_path)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="Audio file is not available.")

    await session.execute(
        update(APIKey)
        .where(APIKey.id == api_key.id)
        .values(
            request_count=APIKey.request_count + 1,
            last_used_at=utc_now(),
        )
    )
    await session.commit()
    return FileResponse(
        path=path,
        media_type=track.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
