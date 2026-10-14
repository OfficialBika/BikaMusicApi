# Deployment

## 1. Prepare configuration

Copy .env.example to .env and set:

- APP_ENV=production
- PUBLIC_API_BASE_URL to your real HTTPS API base URL
- a strong POSTGRES_PASSWORD and matching DATABASE_URL password
- independent random API_KEY_PEPPER and PLAYBACK_SIGNING_SECRET values
- API_BOT_TOKEN from Telegram BotFather
- API_BOT_ALLOWED_USER_IDS to the numeric Telegram user IDs permitted to generate/manage keys

Create independent secrets with:

    openssl rand -hex 32
    openssl rand -hex 32

Never commit .env. Keep backups of PostgreSQL data and the signing/pepper values. Losing API_KEY_PEPPER makes existing API keys unusable; changing PLAYBACK_SIGNING_SECRET invalidates all active signed playback URLs.

## 2. Place authorized audio files

Create a media folder beside compose.yaml and copy in audio you are legally allowed to stream. The container mounts it read-only at /data/media. Do not put cookies, API secrets, or unrelated personal files in this directory.

## 3. Start services

    cp .env.example .env
    # edit .env before starting
    docker compose up -d --build
    docker compose ps
    docker compose logs -f api bot

The API port is bound to 127.0.0.1 by default. Put a TLS reverse proxy such as Caddy or Nginx in front of it and proxy HTTPS traffic to 127.0.0.1:8000. Do not expose PostgreSQL or Redis publicly.

## 4. Index the audio catalog

After adding authorized files to ./media:

    docker compose exec api python -m scripts.index_media

Run the command again after adding/updating files. This updates metadata for existing paths and indexes new paths; it does not delete catalog records for removed files, which will return 404 until the files are restored or records are managed separately.

## 5. Generate credentials

Open the Telegram bot in a private chat and use:

    /generate music-client
    /myapi
    /stats
    /revoke <key_id>
    /regenerate <key_id>
    /docs

API management commands are disabled unless the Telegram user ID appears in API_BOT_ALLOWED_USER_IDS. The bot only displays a raw API key at creation/rotation time.

Store the API URL and key in the Music Bot deployment's environment variables, not in source code:

    MUSIC_API_URL=https://api.example.com/v1
    MUSIC_API_KEY=<key shown once by the bot>

This repository is independent of Bika-Music-v3; integrate the API client separately after the service has been deployed and tested.

## 6. Verify

    curl -fsS https://api.example.com/health/live
    curl -fsS https://api.example.com/health/ready
    curl -H "X-API-Key: $MUSIC_API_KEY" "$MUSIC_API_URL"

Open https://api.example.com/docs only after HTTPS is configured.

## Operational notes

- PostgreSQL persists key and catalog data; Redis provides shared sliding-window rate limiting.
- Production startup fails closed when secrets, HTTPS URL, PostgreSQL, or Redis settings are missing.
- A short-lived signed playback URL is a bearer secret; do not send it to public chats.
- Back up PostgreSQL and protect the Redis/PostgreSQL network.
- The included indexer is intended for a trusted operator-managed directory.
- This project is API and credential management software; it does not supply third-party music rights.
