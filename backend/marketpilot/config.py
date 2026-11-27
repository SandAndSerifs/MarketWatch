"""Application configuration.

All secrets come from environment variables (or a local, git-ignored `.env`).
Nothing in this module ever contains a real credential.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env", BACKEND_DIR.parent / ".env"),
        env_prefix="",
        extra="ignore",
    )

    # ---- runtime -------------------------------------------------------
    environment: Literal["development", "production", "test"] = Field("development", alias="MARKETPILOT_ENV")
    database_url: str = Field(f"sqlite:///{BACKEND_DIR / 'marketpilot.db'}", alias="DATABASE_URL")
    api_host: str = Field("127.0.0.1", alias="API_HOST")
    api_port: int = Field(8000, alias="API_PORT")
    cors_origins: str = Field("http://localhost:3000,http://127.0.0.1:3000", alias="CORS_ORIGINS")
    # When false the API serves requests but the autonomous engine/scanner loops do not run.
    run_engine: bool = Field(True, alias="RUN_ENGINE")
    # Remote access (e.g. Cloudflare Tunnel): requires login with APP_PASSWORD (>= 12 chars).
    public_mode: bool = Field(False, alias="PUBLIC_MODE")
    app_password: SecretStr | None = Field(None, alias="APP_PASSWORD")
    session_secret: SecretStr | None = Field(None, alias="SESSION_SECRET")

    # ---- market data -----------------------------------------------------
    market_data_provider: Literal["alpaca", "massive", "none"] = Field("alpaca", alias="MARKET_DATA_PROVIDER")
    alpaca_api_key_id: SecretStr | None = Field(None, alias="ALPACA_API_KEY_ID")
    alpaca_api_secret_key: SecretStr | None = Field(None, alias="ALPACA_API_SECRET_KEY")
    # "iex" is free real-time (IEX exchange only). "sip" requires Algo Trader Plus for real-time.
    alpaca_feed: Literal["iex", "sip", "delayed_sip"] = Field("iex", alias="ALPACA_FEED")
    alpaca_data_url: str = Field("https://data.alpaca.markets", alias="ALPACA_DATA_URL")
    alpaca_stream_url: str = Field("wss://stream.data.alpaca.markets", alias="ALPACA_STREAM_URL")
    # Reference data (asset list, clock, calendar) is read from the PAPER trading host only.
    # MarketPilot never calls an order endpoint on any Alpaca host.
    alpaca_reference_url: str = Field("https://paper-api.alpaca.markets", alias="ALPACA_REFERENCE_URL")

    massive_api_key: SecretStr | None = Field(None, alias="MASSIVE_API_KEY")
    massive_rest_url: str = Field("https://api.massive.com", alias="MASSIVE_REST_URL")
    massive_realtime: bool = Field(False, alias="MASSIVE_REALTIME")  # True only on a real-time plan

    finnhub_api_key: SecretStr | None = Field(None, alias="FINNHUB_API_KEY")

    stale_quote_seconds: int = Field(90, alias="STALE_QUOTE_SECONDS")

    # ---- AI --------------------------------------------------------------
    ai_provider: Literal["anthropic", "none"] = Field("anthropic", alias="AI_PROVIDER")
    anthropic_api_key: SecretStr | None = Field(None, alias="ANTHROPIC_API_KEY")
    ai_model: str = Field("claude-opus-5-5", alias="AI_MODEL")
    ai_effort: Literal["low", "medium", "high", "xhigh", "max"] = Field("medium", alias="AI_EFFORT")

    # ---- notifications ---------------------------------------------------
    smtp_host: str | None = Field(None, alias="SMTP_HOST")
    smtp_port: int = Field(587, alias="SMTP_PORT")
    smtp_user: str | None = Field(None, alias="SMTP_USER")
    smtp_password: SecretStr | None = Field(None, alias="SMTP_PASSWORD")
    alert_email_to: str | None = Field(None, alias="ALERT_EMAIL_TO")
    alert_webhook_url: SecretStr | None = Field(None, alias="ALERT_WEBHOOK_URL")  # e.g. ntfy.sh topic URL

    # ---- optional brokerage (read-only, disabled by default) -------------
    robinhood_mcp_enabled: bool = Field(False, alias="ROBINHOOD_MCP_ENABLED")
    robinhood_mcp_url: str = Field("https://agent.robinhood.com/mcp/trading", alias="ROBINHOOD_MCP_URL")
    robinhood_mcp_token: SecretStr | None = Field(None, alias="ROBINHOOD_MCP_TOKEN")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def has_alpaca(self) -> bool:
        return bool(self.alpaca_api_key_id and self.alpaca_api_secret_key)

    def has_massive(self) -> bool:
        return bool(self.massive_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def reset_settings_cache() -> None:
    get_settings.cache_clear()
