# Bika Music API

A self-hosted API service and Telegram management bot for API credentials and an operator-managed audio catalog. This repository is separate from Bika-Music-v3.

## Components

- **FastAPI service** — health checks, authenticated search/metadata, and short-lived signed playback URLs.
- **Telegram bot** — generates, lists, rotates, and revokes per-user API keys.
- **PostgreSQL** — persistent API-key and catalog metadata.
- **Redis** — shared sliding-window rate limiting across API workers.
- **Catalog indexer** — reads metadata from an operator-managed local audio directory; it does not download music.

This project intentionally does not scrape websites, reverse-engineer private downloader endpoints, bypass DRM, or bypass third-party platform access controls. Only add audio you own, have licensed, or otherwise have permission to stream.

## Quick start

1. Copy .env.example to .env.
2. Change every placeholder. Generate independent secrets with openssl rand -hex 32 for API_KEY_PEPPER and PLAYBACK_SIGNING_SECRET. Set POSTGRES_PASSWORD, the matching database URL, your Telegram bot token, your public HTTPS API URL, and allowed Telegram numeric user IDs.
3. Create the media directory and put authorized local audio in it.
4. Start the service: docker compose up -d --build.
5. Check docker compose ps and docker compose logs -f api bot.
6. Index audio: docker compose exec api python -m scripts.index_media.
7. Open a private chat with the Telegram bot, then use /generate music-client.
8. Call the API with the generated key in the X-API-Key header.

For a production deployment, put a TLS reverse proxy in front of the API. Compose binds port 8000 to localhost by default and does not publish PostgreSQL or Redis.

## Telegram bot commands

- /generate [name] — create a new API key.
- /myapi — list key IDs, status, request counts, and rate limits. It never repeats a secret.
- /regenerate <key_id> — revoke the previous key and display its replacement once.
- /revoke <key_id> — revoke a key and invalidate its active playback URLs.
- /stats — view your key usage and current catalog size.
- /docs — show the Swagger API URL.

For security, commands must be used in a private chat and API key management is disabled unless the Telegram user ID is listed in API_BOT_ALLOWED_USER_IDS.

## Example client configuration

Set these variables in the consumer's deployment, not in source code:

    MUSIC_API_URL=https://api.example.com/v1
    MUSIC_API_KEY=<key displayed once by the Telegram bot>

The API URL is shared; access, rate limits, revocation, and usage counters are controlled by the individual API key. There is no need to create a new server URL per user.

## Main endpoints

- GET /health/live — liveness check.
- GET /health/ready — database readiness check.
- GET /v1/search?q=<query>&limit=10 — search the authorized catalog.
- GET /v1/tracks/{track_id} — track metadata.
- GET /v1/tracks/{track_id}/playback — mint a signed playback URL.
- GET /v1/streams/{track_id}?kid=...&exp=...&sig=... — serve audio for a short-lived signed URL.

Full request/response details: docs/API.md. Setup and operations: docs/DEPLOYMENT.md. Interactive API docs are served at /docs.

## Security notes

- Raw API keys are displayed only once. The database stores a peppered HMAC digest, not the original key.
- Use separate, long random values for API_KEY_PEPPER and PLAYBACK_SIGNING_SECRET. Do not rotate the pepper without rotating every API key.
- Playback URLs are bearer secrets and expire quickly. Revoking a key immediately invalidates its URLs.
- In production, PostgreSQL, Redis, strong secrets, and an HTTPS public URL are required.
- Do not expose PostgreSQL or Redis on the public internet and never commit .env.

## Development

Install requirements.txt, configure .env for local development, then run:

    uvicorn app.main:app --reload
    python -m bot.main
    pytest -q
    ruff check app bot scripts tests

The catalog indexer is run as a separate operator action when audio files are added or updated. The Music Bot repository is not modified by this project.
