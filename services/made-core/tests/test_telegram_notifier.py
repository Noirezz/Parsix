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

    assert "🚨 <b>[HIGH] BTC Futures Spread Anomaly</b>" in formatted
    assert "2026-08-26 18:25:00 UTC" in formatted
    assert "Modules:" not in formatted  # Module name omitted from body as topic indicates category


def test_format_alert_message_with_exchange_prices():
    config = InfrastructureConfig(
        telegram_bot_token="test_token",
        telegram_chat_id="12345",
    )
    adapter = TelegramNotificationAdapter(config=config)
    alert = Alert(
        alert_id="alt-tg-rich",
        timestamp=TS,
        asset="BTC",
        priority=Priority.HIGH,
        title="[HIGH] BTC Futures Spread",
        summary="Spread detected",
        anomaly_score=Decimal("4.85"),
        triggered_modules=("futures-futures-spread",),
        details={
            "firstSource": "Binance",
            "firstMarketType": "Futures",
            "firstPrice": "68500.00",
            "firstSymbol": "BTCUSDT",
            "secondSource": "Bybit",
            "secondMarketType": "Futures",
            "secondPrice": "65200.00",
            "secondSymbol": "BTCUSDT",
            "spreadPercent": "4.85",
        },
    )

    formatted = adapter.format_alert_message(alert)
    assert "🚨 <b>[HIGH] BTC Futures Spread Anomaly</b>" in formatted
    assert "📊 <b>Спред:</b> <code>+4.85%</code>" in formatted
    assert "• <b>Binance Futures:</b> <code>$68,500.00</code>" in formatted
    assert "• <b>Bybit Futures:</b> <code>$65,200.00</code>" in formatted

    # Test keyboard buttons
    markup = adapter.build_inline_keyboard(alert)
    assert markup is not None
    assert "inline_keyboard" in markup
    buttons = markup["inline_keyboard"][0]
    assert len(buttons) == 2
    assert buttons[0]["text"] == "🟡 Binance Futures"
    assert "binance.com/en/futures/BTCUSDT" in buttons[0]["url"]
    assert buttons[1]["text"] == "⚫ Bybit Futures"
    assert "bybit.com/trade/usdt/BTCUSDT" in buttons[1]["url"]


def test_format_alert_message_funding():
    config = InfrastructureConfig(
        telegram_bot_token="test_token",
        telegram_chat_id="12345",
    )
    adapter = TelegramNotificationAdapter(config=config)
    alert = Alert(
        alert_id="alt-tg-fund",
        timestamp=TS,
        asset="BTC",
        priority=Priority.HIGH,
        title="[HIGH] BTC Funding Spread",
        summary="Funding divergence detected",
        anomaly_score=Decimal("0.085"),
        triggered_modules=("funding-spread",),
        details={
            "firstSource": "Binance",
            "secondSource": "Bybit",
            "firstFundingRate": "0.0005",
            "secondFundingRate": "-0.00035",
            "fundingSpreadPercent": "0.0850",
        },
    )

    formatted = adapter.format_alert_message(alert)
    assert "🚨 <b>[HIGH] BTC Funding Anomaly</b>" in formatted
    assert "📊 <b>Розбіжність Funding:</b> <code>0.0850%</code>" in formatted
    assert "• <b>Binance Futures:</b> <code>+0.0500%</code>" in formatted
    assert "• <b>Bybit Futures:</b> <code>-0.0350%</code>" in formatted


def test_format_alert_message_dex_futures():
    config = InfrastructureConfig(
        telegram_bot_token="test_token",
        telegram_chat_id="12345",
    )
    adapter = TelegramNotificationAdapter(config=config)
    alert = Alert(
        alert_id="alt-tg-dex",
        timestamp=TS,
        asset="SOL",
        priority=Priority.HIGH,
        title="[HIGH] SOL DEX-Futures Arbitrage",
        summary="DEX vs CEX Futures divergence detected",
        anomaly_score=Decimal("6.25"),
        triggered_modules=("dex-futures-spread",),
        details={
            "dexSource": "Raydium",
            "dexName": "Raydium",
            "dexPrice": "135.50",
            "dexUrl": "https://dexscreener.com/solana/58o1b9q5wpwfwturfuk8h8uydg58j",
            "dexLiquidityUsd": "5000000",
            "futuresSource": "Binance",
            "futuresPrice": "144.00",
            "spreadPercent": "6.25",
        },
    )

    formatted = adapter.format_alert_message(alert)
    assert "🚨 <b>[HIGH] SOL DEX-Futures Arbitrage</b>" in formatted
    assert "📊 <b>Спред (DEX vs CEX Short):</b> <code>+6.25%</code>" in formatted
    assert "• 🦄 <b>Raydium (DEX Spot):</b> <code>$135.50</code>" in formatted
    assert "• 📉 <b>Binance (CEX Futures):</b> <code>$144.00</code>" in formatted
    assert "💧 <b>Ліквідність пулу:</b> <code>$5.0M</code>" in formatted

    # Test interactive buttons
    markup = adapter.build_inline_keyboard(alert)
    assert markup is not None
    buttons = markup["inline_keyboard"][0]
    assert len(buttons) == 2
    assert buttons[0]["text"] == "🦄 Купити на Raydium"
    assert "dexscreener.com/solana" in buttons[0]["url"]
    assert buttons[1]["text"] == "📉 Шорт на Binance Futures"
    assert "binance.com/en/futures/SOLUSDT" in buttons[1]["url"]



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
    assert "🚨 <b>[HIGH] BTC Futures Spread Anomaly</b>" in payload["text"]
    assert payload.get("parse_mode") == "HTML"
    assert "reply_markup" in payload


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
    assert "<b>[MEDIUM] BTC DEX-Futures Arbitrage</b>" in payload["text"]
    assert payload.get("parse_mode") == "HTML"


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


def test_telegram_topic_routing_determination():
    config = InfrastructureConfig(
        telegram_bot_token="t",
        telegram_chat_id="c",
        telegram_topic_futures_futures=8,
        telegram_topic_spot_futures=4,
        telegram_topic_dex_futures=2,
        telegram_topic_funding=6,
        telegram_topic_general=15,
    )
    adapter = TelegramNotificationAdapter(config=config)

    # 1. Futures-Futures module -> Topic 8
    alert_ff = _make_alert(modules=("futures-futures-spread",))
    assert adapter.get_target_topic_id(alert_ff) == 8

    # 2. Spot-Futures module -> Topic 4
    alert_sf = _make_alert(modules=("spot-futures-spread",))
    assert adapter.get_target_topic_id(alert_sf) == 4

    # 3. DEX-Futures module -> Topic 2
    alert_dex = _make_alert(modules=("dex-futures-spread",))
    assert adapter.get_target_topic_id(alert_dex) == 2

    # 4. Funding module -> Topic 6
    alert_fund = _make_alert(modules=("funding-spread",))
    assert adapter.get_target_topic_id(alert_fund) == 6

    # 5. Multiple modules with futures -> Topic 8
    alert_multi = _make_alert(modules=("futures-futures-spread", "spot-futures-spread"))
    assert adapter.get_target_topic_id(alert_multi) == 8

    # 6. Unmapped module -> Topic 15 (General)
    alert_custom = _make_alert(modules=("unknown-module",))
    assert adapter.get_target_topic_id(alert_custom) == 15


@pytest.mark.asyncio
async def test_telegram_send_alert_includes_message_thread_id():
    captured_payload = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1001}})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = InfrastructureConfig(
        telegram_bot_token="test_token",
        telegram_chat_id="-10012345",
        telegram_topic_futures_futures=8,
    )
    adapter = TelegramNotificationAdapter(config=config, client=client)
    alert = _make_alert(modules=("futures-futures-spread",))

    await adapter.send_alert(alert)

    assert captured_payload is not None
    assert captured_payload["chat_id"] == "-10012345"
    assert captured_payload["message_thread_id"] == 8
    assert "🚨 <b>[HIGH] BTC Futures Spread Anomaly</b>" in captured_payload["text"]


@pytest.mark.asyncio
async def test_funding_alert_throttling_cooldown():
    recorded_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1002}})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    config = InfrastructureConfig(
        telegram_bot_token="test_token",
        telegram_chat_id="-10012345",
        funding_alert_cooldown_seconds=3600.0,
        funding_alert_min_change_percent=Decimal("0.02"),
    )
    adapter = TelegramNotificationAdapter(config=config, client=client)

    alert1 = Alert(
        alert_id="alt-fund-1",
        timestamp=TS,
        asset="BTC",
        priority=Priority.HIGH,
        title="[HIGH] BTC Funding",
        summary="Funding anomaly",
        anomaly_score=Decimal("0.05"),
        triggered_modules=("funding-spread",),
        details={"fundingSpreadPercent": "0.0500"},
    )

    # First send -> Should be delivered
    await adapter.send_alert(alert1)
    assert len(recorded_requests) == 1

    # Second send with identical spread immediately -> Throttled!
    await adapter.send_alert(alert1)
    assert len(recorded_requests) == 1  # No second request

    # Third send with significantly different spread (+0.03% change >= 0.02% threshold) -> Delivered!
    alert2 = Alert(
        alert_id="alt-fund-2",
        timestamp=TS,
        asset="BTC",
        priority=Priority.HIGH,
        title="[HIGH] BTC Funding",
        summary="Funding anomaly",
        anomaly_score=Decimal("0.085"),
        triggered_modules=("funding-spread",),
        details={"fundingSpreadPercent": "0.0850"},
    )
    await adapter.send_alert(alert2)
    assert len(recorded_requests) == 2
