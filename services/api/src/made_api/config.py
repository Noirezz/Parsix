"""Configuration settings for MADE REST API."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiConfig(BaseSettings):
    """Configuration for FastAPI REST API service."""

    model_config = SettingsConfigDict(
        env_prefix="MADE_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173"]
    )
    title: str = "MADE REST API"
    version: str = "0.1.0"
    description: str = "Read-only REST API for Modular Anomaly Detection Engine (MADE)"
