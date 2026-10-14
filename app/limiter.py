import asyncio
import time
from collections import defaultdict, deque
from secrets import token_hex

from fastapi import HTTPException
from redis.asyncio import Redis

from app.config import settings


_redis: Redis | None = None
_lock = asyncio.Lock()
_windows: dict[str, deque[float]] = defaultdict(deque)


async def init_limiter() -> None:
    global _redis
    if not settings.redis_url:
        return
    _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    await _redis.ping()


async def close_limiter() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def enforce_rate_limit(identity: str, limit: int) -> None:
    now = time.time()
    if _redis is not None:
        bucket_key = f"rate:v1:{identity}"
        member = f"{int(now * 1000)}:{token_hex(8)}"
        script = (
            "redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1] - 60000); "
            "local count = redis.call('ZCARD', KEYS[1]); "
            "if count >= tonumber(ARGV[2]) then return count end; "
            "redis.call('ZADD', KEYS[1], ARGV[1], ARGV[3]); "
            "redis.call('PEXPIRE', KEYS[1], 120000); "
            "return count + 1"
        )
        try:
            count = int(await _redis.eval(script, 1, bucket_key, int(now * 1000), limit, member))
        except Exception as exc:
            # Fail closed when shared rate limiting is configured but unavailable.
            raise HTTPException(status_code=503, detail="Rate-limit service unavailable.") from exc
        if count > limit:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again shortly.",
                headers={"Retry-After": "60"},
            )
        return

    # Local fallback is useful for tests/development only; production requires Redis.
    async with _lock:
        queue = _windows[identity]
        cutoff = now - 60
        while queue and queue[0] <= cutoff:
            queue.popleft()
        if len(queue) >= limit:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again shortly.",
                headers={"Retry-After": "60"},
            )
        queue.append(now)
        # Prevent stale identities from growing without bound in a dev process.
        if len(_windows) > 10_000:
            stale = [key for key, values in _windows.items() if not values or values[-1] <= cutoff]
            for key in stale[:2_000]:
                _windows.pop(key, None)
