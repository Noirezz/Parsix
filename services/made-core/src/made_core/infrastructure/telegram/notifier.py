"""Asynchronous Telegram Bot API notification adapter for MADE."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from made_core.domain.models import Alert
from made_core.infrastructure.config import InfrastructureConfig

logger = logging.getLogger(__name__)


class TelegramNotificationError(Exception):
    """Raised when Telegram alert delivery fails."""


class TelegramNotificationAdapter:
    """Asynchronous notification adapter delivering Alert objects to Telegram chats."""

    def __init__(
        self,
        config: InfrastructureConfig | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config or InfrastructureConfig()
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._config.telegram_timeout_seconds,
            )
        return self._client

    def format_alert_message(self, alert: Alert) -> str:
        """Format a domain Alert into a deterministic, human-readable Telegram message."""
        ts_utc = alert.timestamp.astimezone(UTC)
        ts_str = ts_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
        modules_str = ", ".join(alert.triggered_modules)

        # Title formatting: add alert icon if not present
        title = alert.title if alert.title.startswith("🚨") else f"🚨 {alert.title}"

        return (
            f"{title}\n\n"
            f"Summary: {alert.summary}\n"
            f"Priority: {alert.priority.value}\n"
            f"Modules: {modules_str}\n"
            f"Timestamp: {ts_str}"
        )

    def _sanitize_error_message(self, raw_message: str) -> str:
        """Strip bot token from any error or exception message."""
        if self._config.telegram_bot_token and self._config.telegram_bot_token in raw_message:
            return raw_message.replace(self._config.telegram_bot_token, "***")
        return raw_message

    async def send_alert(self, alert: Alert) -> None:
        """Send an Alert to the configured Telegram chat with retries for transient failures."""
        if alert is None:
            raise TypeError("alert must not be None")

        if not self._config.telegram_bot_token:
            raise TelegramNotificationError("Telegram bot token is not configured")

        if not self._config.telegram_chat_id:
            raise TelegramNotificationError("Telegram chat ID is not configured")

        endpoint = f"{self._config.telegram_api_base_url.rstrip('/')}/bot{self._config.telegram_bot_token}/sendMessage"
        message_text = self.format_alert_message(alert)
        payload = {
            "chat_id": self._config.telegram_chat_id,
            "text": message_text,
        }

        client = self._get_client()
        max_retries = self._config.telegram_max_retries
        base_delay = self._config.telegram_retry_base_delay_seconds

        for attempt in range(max_retries + 1):
            try:
                response = await client.post(endpoint, json=payload)

                # Check HTTP status
                if response.status_code == 429:
                    # Rate limit - transient error
                    if attempt < max_retries:
                        retry_after = base_delay * (2**attempt)
                        try:
                            res_json = response.json()
                            if "parameters" in res_json and "retry_after" in res_json["parameters"]:
                                retry_after = min(float(res_json["parameters"]["retry_after"]), 30.0)
                        except Exception:
                            pass
                        logger.warning("Telegram rate limited (429). Retrying in %.2f seconds (attempt %d/%d)", retry_after, attempt + 1, max_retries)
                        await asyncio.sleep(retry_after)
                        continue
                    raise TelegramNotificationError(f"Telegram API rate limit (429) exceeded after {max_retries} retries")

                if 500 <= response.status_code < 600:
                    # Server error - transient
                    if attempt < max_retries:
                        delay = base_delay * (2**attempt)
                        logger.warning("Telegram server error (%d). Retrying in %.2f seconds (attempt %d/%d)", response.status_code, delay, attempt + 1, max_retries)
                        await asyncio.sleep(delay)
                        continue
                    raise TelegramNotificationError(f"Telegram server error ({response.status_code}) after {max_retries} retries")

                if 400 <= response.status_code < 500:
                    # Client error - permanent, do not retry
                    err_desc = response.text
                    try:
                        err_json = response.json()
                        err_desc = err_json.get("description", err_desc)
                    except Exception:
                        pass
                    raise TelegramNotificationError(f"Telegram API client error ({response.status_code}): {self._sanitize_error_message(err_desc)}")

                # Check Telegram payload { "ok": true }
                res_data = response.json()
                if not res_data.get("ok"):
                    desc = res_data.get("description", "Unknown Telegram error")
                    raise TelegramNotificationError(f"Telegram API reported failure: {self._sanitize_error_message(desc)}")

                # Success
                return

            except (httpx.TransportError, httpx.TimeoutException) as net_err:
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    logger.warning("Telegram network error. Retrying in %.2f seconds (attempt %d/%d)", delay, attempt + 1, max_retries)
                    await asyncio.sleep(delay)
                    continue
                sanitized_err = self._sanitize_error_message(str(net_err))
                raise TelegramNotificationError(f"Telegram delivery network error after {max_retries} retries: {sanitized_err}") from net_err

    async def close(self) -> None:
        """Close the underlying HTTP client if owned."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> TelegramNotificationAdapter:
        self._get_client()
        return self


    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
