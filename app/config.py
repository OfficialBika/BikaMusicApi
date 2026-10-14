from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "Bika Music API"
    log_level: str = "INFO"
    public_api_base_url: str = "http://127.0.0.1:8000"
    database_url: str = "sqlite+aiosqlite:///./data/bika_music_api.db"
    redis_url: str | None = None
    api_key_pepper: str = ""
    playback_signing_secret: str = ""
    api_bot_token: str = ""
    api_bot_allowed_user_ids: str = ""
    media_root: Path = Path("./media")
    rate_limit_per_minute: int = 60
    playback_url_ttl_seconds: int = 300

    @property
    def telegram_allowlist(self) -> set[int]:
        allowed: set[int] = set()
        for item in self.api_bot_allowed_user_ids.split(","):
            value = item.strip()
            if not value:
                continue
            try:
                allowed.add(int(value))
            except ValueError:
                continue
        return allowed

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"


settings = Settings()
