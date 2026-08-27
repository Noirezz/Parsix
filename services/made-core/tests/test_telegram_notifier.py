"""Unit tests for Telegram notification adapter and error handling."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from unittest import mock

import httpx
import pytest

from made_core.domain.enums import Priority
from made_core.domain.models import Alert
from made_core.infrastructure.config import InfrastructureConfig
from made_core.infrastructure.telegram.notifier import (
    TelegramNotificationAdapter,
    TelegramNotificationError,
)

TS = datetime(2026, 8, 26, 18, 25, 0, tzinfo=UTC)


def _make_alert(
    *,
    priority: Priority = Priority.HIGH,
    asset: str = "BTC",
    title: str = "[HIGH] BTC anomaly detected",
    summary: str = "BTC anomaly detected by 2 module(s). Composite score: 4.4.",
    modules: tuple[str, ...] = ("futures-futures-spread", "spot-futures-spread"),
) -> Alert:
    return Alert(
        alert_id="alt-tg-1",
        timestamp=TS,
        asset=asset,
        priority=priority,
        title=title,
        summary=summary,
        anomaly_score=Decimal("4.4"),
        triggered_modules=modules,
        details={"score": "4.4"},
    )


def test_telegram_config_defaults_and_env_overrides():
    default_config = InfrastructureConfig()
    assert default_config.telegram_bot_token is None
    assert default_config.telegram_chat_id is None
    assert default_config.telegram_api_base_url == "https://api.telegram.org"
    assert default_config.telegram_timeout_seconds == 10.0
    assert default_config.telegram_max_retries == 3
    assert default_config.telegram_retry_base_delay_seconds == 1.0

    env_vars = {
        "MADE_TELEGRAM_BOT_TOKEN": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        "MADE_TELEGRAM_CHAT_ID": "-1001234567890",
        "MADE_TELEGRAM_API_BASE_URL": "https://api.telegram-proxy.internal",
        "MADE_TELEGRAM_TIMEOUT_SECONDS": "5.0",
        "MADE_TELEGRAM_MAX_RETRIES": "2",
        "MADE_TELEGRAM_RETRY_BASE_DELAY_SECONDS": "0.1",
    }
    with mock.patch.dict(os.environ, env_vars, clear=False):
        config = InfrastructureConfig()
        assert config.telegram_bot_token == "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        assert config.telegram_chat_id == "-1001234567890"
        assert config.telegram_api_base_url == "https://api.telegram-proxy.internal"
        assert config.telegram_timeout_seconds == 5.0
        assert config.telegram_max_retries == 2
        assert config.telegram_retry_base_delay_seconds == 0.1


def test_format_alert_message_exact():
    config = InfrastructureConfig(
        telegram_bot_token="test_token",
        telegram_chat_id="12345",
    )
    adapter = TelegramNotificationAdapter(config=config)
    alert = _make_alert()

    formatted = adapter.format_alert_message(alert)

    expected = (
        "🚨 [HIGH] BTC anomaly detected\n\n"
        "Summary: BTC anomaly detected by 2 module(s). Composite score: 4.4.\n"
        "Priority: HIGH\n"
        "Modules: futures-futures-spread, spot-futures-spread\n"
        "Timestamp: 2026-08-26 18:25:00 UTC"
    )
    assert formatted == expected


@pytest.mark.asyncio
async def test_successful_high_alert_delivery():
    recorded_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 999}})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = InfrastructureConfig(
        telegram_bot_token="secret_token_123",
        telegram_chat_id="-1009999",
    )
    adapter = TelegramNotificationAdapter(config=config, client=client)

    alert = _make_alert(priority=Priority.HIGH)
    await adapter.send_alert(alert)

    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    assert req.url == "https://api.telegram.org/botsecret_token_123/sendMessage"
    payload = json.loads(req.content.decode("utf-8"))
    assert payload["chat_id"] == "-1009999"
    assert "🚨 [HIGH] BTC anomaly detected" in payload["text"]


@pytest.mark.asyncio
async def test_successful_medium_alert_delivery():
    recorded_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1000}})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = InfrastructureConfig(
        telegram_bot_token="secret_token_123",
        telegram_chat_id="-1009999",
    )
    adapter = TelegramNotificationAdapter(config=config, client=client)

    alert = _make_alert(
        priority=Priority.MEDIUM,
        title="[MEDIUM] ETH anomaly detected",
        summary="ETH anomaly detected by 1 module(s).",
        modules=("dex-futures-spread",),
    )
    await adapter.send_alert(alert)

    assert len(recorded_requests) == 1
    payload = json.loads(recorded_requests[0].content.decode("utf-8"))
    assert "Priority: MEDIUM" in payload["text"]
    assert "Modules: dex-futures-spread" in payload["text"]


@pytest.mark.asyncio
async def test_telegram_api_ok_false_handling():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = InfrastructureConfig(
        telegram_bot_token="token_123",
        telegram_chat_id="invalid_chat",
    )
    adapter = TelegramNotificationAdapter(config=config, client=client)

    alert = _make_alert()
    with pytest.raises(TelegramNotificationError, match="Bad Request: chat not found"):
        await adapter.send_alert(alert)


@pytest.mark.asyncio
async def test_http_429_retry_and_success():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                429,
                json={"ok": False, "error_code": 429, "parameters": {"retry_after": 0.01}},
            )
        return httpx.Response(200, json={"ok": True, "result": {}})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = InfrastructureConfig(
        telegram_bot_token="token_123",
        telegram_chat_id="chat_123",
        telegram_retry_base_delay_seconds=0.01,
    )
    adapter = TelegramNotificationAdapter(config=config, client=client)

    alert = _make_alert()
    await adapter.send_alert(alert)

    assert call_count == 2


@pytest.mark.asyncio
async def test_http_5xx_retry_and_success():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(502, text="Bad Gateway")
        return httpx.Response(200, json={"ok": True, "result": {}})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = InfrastructureConfig(
        telegram_bot_token="token_123",
        telegram_chat_id="chat_123",
        telegram_retry_base_delay_seconds=0.01,
    )
    adapter = TelegramNotificationAdapter(config=config, client=client)

    alert = _make_alert()
    await adapter.send_alert(alert)

    assert call_count == 2


@pytest.mark.asyncio
async def test_network_exception_retry_and_success():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ConnectError("Connection refused")
        return httpx.Response(200, json={"ok": True, "result": {}})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = InfrastructureConfig(
        telegram_bot_token="token_123",
        telegram_chat_id="chat_123",
        telegram_retry_base_delay_seconds=0.01,
    )
    adapter = TelegramNotificationAdapter(config=config, client=client)

    alert = _make_alert()
    await adapter.send_alert(alert)

    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_exhaustion_raises_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = InfrastructureConfig(
        telegram_bot_token="token_123",
        telegram_chat_id="chat_123",
        telegram_max_retries=2,
        telegram_retry_base_delay_seconds=0.01,
    )
    adapter = TelegramNotificationAdapter(config=config, client=client)

    alert = _make_alert()
    with pytest.raises(TelegramNotificationError, match="after 2 retries"):
        await adapter.send_alert(alert)


@pytest.mark.asyncio
async def test_permanent_4xx_failure_no_retries():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            401,
            json={"ok": False, "error_code": 401, "description": "Unauthorized: invalid bot token"},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = InfrastructureConfig(
        telegram_bot_token="invalid_token",
        telegram_chat_id="chat_123",
        telegram_max_retries=3,
        telegram_retry_base_delay_seconds=0.01,
    )
    adapter = TelegramNotificationAdapter(config=config, client=client)

    alert = _make_alert()
    with pytest.raises(TelegramNotificationError, match="Unauthorized: invalid bot token"):
        await adapter.send_alert(alert)

    # Should only call once, no retries on 401
    assert call_count == 1


@pytest.mark.asyncio
async def test_missing_bot_token_raises_error():
    config = InfrastructureConfig(telegram_bot_token=None, telegram_chat_id="123")
    adapter = TelegramNotificationAdapter(config=config)
    with pytest.raises(TelegramNotificationError, match="bot token is not configured"):
        await adapter.send_alert(_make_alert())


@pytest.mark.asyncio
async def test_missing_chat_id_raises_error():
    config = InfrastructureConfig(telegram_bot_token="token_123", telegram_chat_id=None)
    adapter = TelegramNotificationAdapter(config=config)
    with pytest.raises(TelegramNotificationError, match="chat ID is not configured"):
        await adapter.send_alert(_make_alert())


@pytest.mark.asyncio
async def test_bot_token_not_leaked_in_exception_messages():
    secret_token = "secret_bot_token_999888777"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            text=f"Error accessing endpoint with token {secret_token}",
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = InfrastructureConfig(
        telegram_bot_token=secret_token,
        telegram_chat_id="chat_123",
    )
    adapter = TelegramNotificationAdapter(config=config, client=client)

    with pytest.raises(TelegramNotificationError) as exc_info:
        await adapter.send_alert(_make_alert())

    err_str = str(exc_info.value)
    assert secret_token not in err_str
    assert "***" in err_str


@pytest.mark.asyncio
async def test_async_context_manager_and_close():
    config = InfrastructureConfig(telegram_bot_token="t", telegram_chat_id="c")
    adapter = TelegramNotificationAdapter(config=config)

    async with adapter:
        assert adapter._client is not None

    assert adapter._client is None
