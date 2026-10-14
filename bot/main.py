import logging
from datetime import timezone

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, ContextTypes

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import engine, init_db, SessionLocal
from app.models import APIKey, Track, utc_now
from app.security import hash_secret
import secrets


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("bika_music_api.bot")


def is_expired(value) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    from datetime import datetime
    return value <= datetime.now(timezone.utc)


async def require_private_allowed(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None:
        return False
    if chat.type != ChatType.PRIVATE:
        await message.reply_text("For your security, use this command in the bot's private chat.")
        return False
    if not settings.telegram_allowlist:
        await message.reply_text(
            "API key generation is currently disabled. The owner must configure "
            "API_BOT_ALLOWED_USER_IDS in the server environment."
        )
        return False
    if user.id not in settings.telegram_allowlist:
        await message.reply_text("You are not authorized to manage Bika Music API keys.")
        return False
    return True


async def create_key(session: AsyncSession, owner_id: int, name: str) -> tuple[APIKey, str]:
    key_id = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    token = f"bika_live_{key_id}_{secret}"
    row = APIKey(
        id=key_id,
        owner_telegram_id=owner_id,
        name=(name.strip()[:80] or "default"),
        prefix=f"bika_live_{key_id}",
        secret_hash=hash_secret(secret),
        rate_limit_per_minute=settings.rate_limit_per_minute,
    )
    session.add(row)
    await session.flush()
    return row, token


def format_key_row(key: APIKey) -> str:
    status = "revoked" if key.revoked_at else ("expired" if is_expired(key.expires_at) else "active")
    created = key.created_at.strftime("%Y-%m-%d %H:%M UTC") if key.created_at else "unknown"
    return (
        f"ID: {key.id}\n"
        f"Name: {key.name}\n"
        f"Status: {status}\n"
        f"Requests: {key.request_count}\n"
        f"Limit: {key.rate_limit_per_minute}/minute\n"
        f"Created: {created}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    if update.effective_chat and update.effective_chat.type != ChatType.PRIVATE:
        await message.reply_text("Open a private chat with this bot to manage API keys.")
        return
    if not settings.telegram_allowlist:
        await message.reply_text(
            "BIKA MUSIC API BOT\n\n"
            "Key management is disabled until the server owner sets "
            "API_BOT_ALLOWED_USER_IDS in .env.\n\n"
            "Commands: /generate, /myapi, /revoke, /regenerate, /stats, /docs"
        )
        return
    await message.reply_text(
        "BIKA MUSIC API BOT\n\n"
        "Generate and manage API credentials for the authorized music catalog.\n\n"
        "/generate [name] — create a key\n"
        "/myapi — list your keys\n"
        "/revoke <key_id> — revoke a key\n"
        "/regenerate <key_id> — replace a key\n"
        "/stats — usage summary\n"
        "/docs — API documentation\n\n"
        "Raw API keys are shown only once. Keep them private."
    )


async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private_allowed(update, context):
        return
    user = update.effective_user
    message = update.effective_message
    assert user is not None and message is not None
    name = " ".join(context.args).strip()[:80] or "default"
    async with SessionLocal() as session:
        row, token = await create_key(session, user.id, name)
        await session.commit()
        key_id = row.id
        rate = row.rate_limit_per_minute
    api_url = settings.public_api_base_url.rstrip("/") + "/v1"
    await message.reply_text(
        "✅ API key created\n\n"
        f"API URL:\n{api_url}\n\n"
        f"API Key ID: {key_id}\n"
        f"API Key (shown once):\n{token}\n\n"
        f"Rate limit: {rate} requests/minute\n"
        "Playback URLs are short-lived. Store this key in your application's secret environment, "
        "not in source code or public chats."
    )


async def myapi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private_allowed(update, context):
        return
    user = update.effective_user
    message = update.effective_message
    assert user is not None and message is not None
    async with SessionLocal() as session:
        rows = list((await session.scalars(
            select(APIKey)
            .where(APIKey.owner_telegram_id == user.id)
            .order_by(APIKey.created_at.desc())
            .limit(20)
        )).all())
    if not rows:
        await message.reply_text("You have no API keys yet. Use /generate [name].")
        return
    # Never display full keys or stored hashes.
    text = "YOUR API KEYS (latest 20)\n\n" + "\n\n".join(format_key_row(row) for row in rows)
    await message.reply_text(text[:4000])


async def revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private_allowed(update, context):
        return
    user = update.effective_user
    message = update.effective_message
    assert user is not None and message is not None
    if not context.args:
        await message.reply_text("Usage: /revoke <key_id>")
        return
    key_id = context.args[0].strip().lower()
    async with SessionLocal() as session:
        row = await session.get(APIKey, key_id)
        if row is None or row.owner_telegram_id != user.id:
            await message.reply_text("Key not found.")
            return
        if row.revoked_at is not None:
            await message.reply_text("This key is already revoked.")
            return
        row.revoked_at = utc_now()
        await session.commit()
    await message.reply_text(f"✅ API key {key_id} has been revoked. Existing playback URLs are also invalidated.")


async def regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private_allowed(update, context):
        return
    user = update.effective_user
    message = update.effective_message
    assert user is not None and message is not None
    if not context.args:
        await message.reply_text("Usage: /regenerate <key_id>")
        return
    old_id = context.args[0].strip().lower()
    async with SessionLocal() as session:
        old = await session.get(APIKey, old_id)
        if old is None or old.owner_telegram_id != user.id or old.revoked_at is not None:
            await message.reply_text("Active key not found.")
            return
        old.revoked_at = utc_now()
        new, token = await create_key(session, user.id, old.name)
        await session.commit()
        new_id = new.id
        rate = new.rate_limit_per_minute
    api_url = settings.public_api_base_url.rstrip("/") + "/v1"
    await message.reply_text(
        "✅ Key rotated. The old key is revoked.\n\n"
        f"API URL:\n{api_url}\n\n"
        f"New key ID: {new_id}\n"
        f"New API Key (shown once):\n{token}\n\n"
        f"Rate limit: {rate} requests/minute\n"
        "Update your application environment immediately."
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private_allowed(update, context):
        return
    user = update.effective_user
    message = update.effective_message
    assert user is not None and message is not None
    async with SessionLocal() as session:
        key_count = await session.scalar(
            select(func.count()).select_from(APIKey).where(APIKey.owner_telegram_id == user.id)
        ) or 0
        active_count = await session.scalar(
            select(func.count()).select_from(APIKey).where(
                APIKey.owner_telegram_id == user.id,
                APIKey.revoked_at.is_(None),
            )
        ) or 0
        requests = await session.scalar(
            select(func.coalesce(func.sum(APIKey.request_count), 0)).where(
                APIKey.owner_telegram_id == user.id
            )
        ) or 0
        tracks = await session.scalar(
            select(func.count()).select_from(Track).where(Track.is_active.is_(True))
        ) or 0
    await message.reply_text(
        "BIKA MUSIC API STATS\n\n"
        f"Your keys: {key_count}\n"
        f"Not revoked: {active_count}\n"
        f"Recorded API requests: {requests}\n"
        f"Catalog tracks: {tracks}"
    )


async def docs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_private_allowed(update, context):
        return
    message = update.effective_message
    if message is None:
        return
    await message.reply_text(
        "API docs: " + settings.public_api_base_url.rstrip("/") + "/docs\n"
        "Local deployment and integration guide: see docs/API.md in the repository."
    )


async def post_init(application: Application) -> None:
    await init_db()
    logger.info("Telegram API management bot initialized.")


async def post_shutdown(application: Application) -> None:
    await engine.dispose()


def main() -> None:
    if not settings.api_bot_token:
        raise SystemExit("API_BOT_TOKEN is required to start the Telegram management bot.")
    application = (
        Application.builder()
        .token(settings.api_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(CommandHandler("generate", generate))
    application.add_handler(CommandHandler("myapi", myapi))
    application.add_handler(CommandHandler("revoke", revoke))
    application.add_handler(CommandHandler("regenerate", regenerate))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("docs", docs))
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
