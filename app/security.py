import hashlib
import hmac
import re
import time

from app.config import settings


_KEY_ID_RE = re.compile(r"^[a-f0-9]{12}$")


def parse_api_key(token: str | None) -> tuple[str, str] | None:
    """Return (public key id, secret) for a well-formed key; never log the token."""
    if not token or len(token) > 200:
        return None
    parts = token.split("_", 3)
    if len(parts) != 4 or parts[0] != "bika" or parts[1] != "live":
        return None
    key_id, secret = parts[2], parts[3]
    if not _KEY_ID_RE.fullmatch(key_id) or not secret or len(secret) < 32:
        return None
    return key_id, secret


def hash_secret(secret: str, pepper: str | None = None) -> str:
    actual_pepper = settings.api_key_pepper if pepper is None else pepper
    if len(actual_pepper) < 32:
        raise RuntimeError("API_KEY_PEPPER must contain at least 32 characters.")
    return hmac.new(
        actual_pepper.encode("utf-8"),
        secret.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def sign_playback(
    track_id: str,
    key_id: str,
    expires_at: int,
    secret: str | None = None,
) -> str:
    signing_secret = settings.playback_signing_secret if secret is None else secret
    if len(signing_secret) < 32:
        raise RuntimeError("PLAYBACK_SIGNING_SECRET must contain at least 32 characters.")
    message = f"{track_id}:{key_id}:{expires_at}".encode("utf-8")
    return hmac.new(signing_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_playback_signature(
    track_id: str,
    key_id: str,
    expires_at: int,
    signature: str,
    *,
    secret: str | None = None,
    now: int | None = None,
    max_ttl_seconds: int = 3600,
) -> bool:
    current_time = int(time.time()) if now is None else now
    if expires_at < current_time or expires_at > current_time + max_ttl_seconds:
        return False
    if not re.fullmatch(r"[a-f0-9]{64}", signature or ""):
        return False
    try:
        expected = sign_playback(track_id, key_id, expires_at, secret=secret)
    except RuntimeError:
        return False
    return hmac.compare_digest(expected, signature)
