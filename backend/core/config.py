"""Application settings, loaded from environment variables / .env."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # LLM (Gemini). The "-latest" alias tracks Google's current Flash-Lite, so the app keeps
    # working when versions are retired; it answers tool calls in ~1.5-3 s. Pinned older
    # versions are usually less congested, so they're the fallbacks, tried in order when a
    # model is overloaded (503), retired (404) or times out.
    google_api_key: str = ""
    gemini_model: str = "gemini-flash-lite-latest"
    gemini_fallback_models: str = "gemini-3.5-flash-lite,gemini-3.1-flash-lite"
    llm_timeout_seconds: float = 20.0
    llm_match_enabled: bool = True  # use Gemini to resolve ambiguous product matches

    # Storage
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/smartdeal"
    redis_url: str = "redis://localhost:6379/0"

    # Data sources (all optional)
    serpapi_key: str = ""  # Google Shopping India: covers most Indian stores
    amazon_access_key: str = ""
    amazon_secret_key: str = ""
    amazon_partner_tag: str = ""
    flipkart_affiliate_id: str = ""
    flipkart_affiliate_token: str = ""
    enable_scrapers: bool = True  # direct store scrapers when no API keys are set
    # Seeded demo data: "auto" = only when no live price source is configured, "true" = always, "false" = never
    demo_catalog: str = "auto"
    enabled_platforms: str = ""  # comma list of adapter slugs; empty = all available

    # Price-history backfill: the first time a live product is analysed, load ~12 months of
    # per-store prices from Google Shopping (SerpApi google_product, 1 search per product)
    history_backfill_enabled: bool = True
    history_backfill_monthly_limit: int = 100  # SerpApi searches/month reserved for backfills
    # Daily refresh of tracked live products costs 1 paid search each, so only the most recently
    # searched products are refreshed, up to this many per day (0 = off). Raise on a paid plan.
    price_refresh_daily_limit: int = 2

    # Tuning
    scraper_rate_limit_seconds: float = 1.0
    adapter_timeout_seconds: float = 20.0
    search_cache_ttl: int = 1800

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, url: str) -> str:
        """Hosts like Railway/Render/Heroku give "postgres(ql)://..." URLs; use the asyncpg driver."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url[len(prefix):]
        return url

    @property
    def gemini_fallback_list(self) -> list[str]:
        return [m.strip() for m in self.gemini_fallback_models.split(",") if m.strip()]

    @property
    def enabled_platform_list(self) -> list[str]:
        return [p.strip().lower() for p in self.enabled_platforms.split(",") if p.strip()]

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def checkpointer_url(self) -> str:
        """Plain libpq URL for the LangGraph Postgres checkpointer (psycopg)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.google_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
