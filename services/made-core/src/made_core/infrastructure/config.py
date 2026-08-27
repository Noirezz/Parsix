"""Configuration models for MADE Core infrastructure."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class InfrastructureConfig(BaseSettings):
    """Infrastructure configuration for Redis Streams and MADE worker."""

    model_config = SettingsConfigDict(
        env_prefix="MADE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_username: str | None = Field(default=None)
    redis_password: str | None = Field(default=None)
    redis_db: int = Field(default=0, ge=0)
    redis_url: str | None = Field(default=None)

    input_stream: str = Field(default="events:normalized")
    consumer_group: str = Field(default="made-core-processors")
    consumer_name: str = Field(default="made-core-worker-1")
    batch_size: int = Field(default=10, ge=1)
    block_timeout_ms: int = Field(default=2000, ge=0)
    dead_letter_stream: str = Field(default="events:dead-letter")
    pel_claim_min_idle_ms: int = Field(default=60000, ge=0)
    pel_claim_batch_size: int = Field(default=10, ge=1)


    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_database: str = Field(default="made")
    postgres_username: str = Field(default="postgres")
    postgres_password: str | None = Field(default=None)
    postgres_url: str | None = Field(default=None)

    telegram_bot_token: str | None = Field(default=None)
    telegram_chat_id: str | None = Field(default=None)
    telegram_api_base_url: str = Field(default="https://api.telegram.org")
    telegram_timeout_seconds: float = Field(default=10.0, gt=0)
    telegram_max_retries: int = Field(default=3, ge=0)
    telegram_retry_base_delay_seconds: float = Field(default=1.0, ge=0)


    def get_redis_url(self) -> str:
        """Construct or return the Redis connection URL."""
        if self.redis_url:
            return self.redis_url
        auth = ""
        if self.redis_username and self.redis_password:
            auth = f"{self.redis_username}:{self.redis_password}@"
        elif self.redis_password:
            auth = f":{self.redis_password}@"
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    def get_postgres_url(self, async_driver: bool = True) -> str:
        """Construct or return the PostgreSQL connection URL."""
        if self.postgres_url:
            url = self.postgres_url
            if async_driver and url.startswith("postgresql://"):
                return url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url
        driver = "postgresql+asyncpg" if async_driver else "postgresql"
        auth = f"{self.postgres_username}"
        if self.postgres_password:
            auth = f"{auth}:{self.postgres_password}"
        return f"{driver}://{auth}@{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"

