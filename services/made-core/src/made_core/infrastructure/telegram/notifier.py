"""Asynchronous Telegram Bot API notification adapter for MADE."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from made_core.domain.models import Alert
from made_core.infrastructure.config import InfrastructureConfig

logger = logging.getLogger(__name__)


class TelegramNotificationError(Exception):
    """Raised when Telegram alert delivery fails."""


def _format_price(val: Any) -> str:
    """Format decimal/float price with dynamic precision."""
    try:
        d = Decimal(str(val))
        if d >= Decimal("100"):
            return f"${d:,.2f}"
        if d >= Decimal("1"):
            return f"${d:,.4f}"
        return f"${d:,.6f}"
    except Exception:
        return f"${val}"


def _get_exchange_url(source: str, market_type: str, symbol: str) -> str | None:
    """Generate direct trading terminal URL for standard crypto exchanges."""
    src = str(source).upper()
    m_type = str(market_type).upper()
    sym = str(symbol).upper()

    if src == "BINANCE":
        if "FUT" in m_type:
            return f"https://www.binance.com/en/futures/{sym}"
        return f"https://www.binance.com/en/trade/{sym}?type=spot"

    if src == "BYBIT":
        if "FUT" in m_type or "LINEAR" in m_type:
            return f"https://www.bybit.com/trade/usdt/{sym}"
        return f"https://www.bybit.com/en/trade/spot/{sym}"

    if src in ("DEX", "DEXSCREENER", "UNISWAP", "RAYDIUM", "PANCAKESWAP", "AERODROME"):
        return f"https://dexscreener.com/search?q={sym}"

    return None


class TelegramNotificationAdapter:
    """Production-grade Telegram Bot notifier with forum topic routing, rich HTML formatting, and action buttons."""

    def __init__(
        self,
        config: InfrastructureConfig | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config or InfrastructureConfig()
        self._client = client
        self._owns_client = client is None
        self._funding_alert_cooldowns: dict[str, tuple[float, Decimal]] = {}

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._config.telegram_timeout_seconds,
            )
        return self._client

    def format_alert_message(self, alert: Alert) -> str:
        """Format a domain Alert into a clean, rich, human-readable Telegram HTML message tailored to the triggered module."""
        ts_utc = alert.timestamp.astimezone(UTC)
        ts_str = ts_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
        details = alert.details or {}
        modules = alert.triggered_modules or ()

        icon = "🚨" if alert.priority.value == "HIGH" else "⚠️"

        # 1. Funding Rate Spread Anomaly
        if "funding-spread" in modules and "futures-futures-spread" not in modules and "spot-futures-spread" not in modules and "dex-futures-spread" not in modules:
            lines = [f"{icon} <b>[{alert.priority.value}] {alert.asset} Funding Anomaly</b>", ""]
            if "firstFundingRate" in details and "secondFundingRate" in details and details["firstFundingRate"] is not None and details["secondFundingRate"] is not None:
                s1 = str(details.get("firstSource", "Exchange 1")).capitalize()
                f1 = Decimal(str(details["firstFundingRate"])) * Decimal("100")

                s2 = str(details.get("secondSource", "Exchange 2")).capitalize()
                f2 = Decimal(str(details["secondFundingRate"])) * Decimal("100")

                diff_str = details.get("fundingSpreadPercent", f"{abs(f1 - f2):.4f}")
                lines.append(f"📊 <b>Розбіжність Funding:</b> <code>{diff_str}%</code>")
                lines.append(f"• <b>{s1} Futures:</b> <code>{f1:+.4f}%</code>")
                lines.append(f"• <b>{s2} Futures:</b> <code>{f2:+.4f}%</code>")
            else:
                lines.append(f"📊 <b>Розбіжність Funding:</b> <code>{alert.anomaly_score:.4f}%</code>")
                lines.append(f"<i>{alert.summary}</i>")

        # 2. DEX-Futures Arbitrage / Hedging Anomaly
        elif "dex-futures-spread" in modules:
            lines = [f"{icon} <b>[{alert.priority.value}] {alert.asset} DEX-Futures Arbitrage</b>", ""]
            spread_str = details.get("spreadPercent", f"{alert.anomaly_score:.2f}")
            if "dexPrice" in details and "futuresPrice" in details and details["dexPrice"] and details["futuresPrice"]:
                dex_name = str(details.get("dexName") or details.get("dexSource") or "DEX").capitalize()
                dex_p_str = _format_price(details["dexPrice"])

                s_fut = str(details.get("futuresSource", "CEX")).capitalize()
                p_fut_str = _format_price(details["futuresPrice"])

                lines.append(f"📊 <b>Спред (DEX vs CEX Short):</b> <code>+{spread_str}%</code>")
                lines.append(f"• 🦄 <b>{dex_name} (DEX Spot):</b> <code>{dex_p_str}</code>")
                lines.append(f"• 📉 <b>{s_fut} (CEX Futures):</b> <code>{p_fut_str}</code>")

                if details.get("dexLiquidityUsd"):
                    try:
                        liq = float(details["dexLiquidityUsd"])
                        if liq >= 1_000_000:
                            liq_str = f"${liq/1_000_000:.1f}M"
                        elif liq >= 1_000:
                            liq_str = f"${liq/1_000:.1f}K"
                        else:
                            liq_str = f"${liq:,.0f}"
                        lines.append(f"💧 <b>Ліквідність пулу:</b> <code>{liq_str}</code>")
                    except Exception:
                        pass
            else:
                lines.append(f"📊 <b>Спред:</b> <code>+{spread_str}%</code>")
                lines.append(f"<i>{alert.summary}</i>")

        # 3. Futures-Futures Spread Anomaly
        elif "futures-futures-spread" in modules:
            lines = [f"{icon} <b>[{alert.priority.value}] {alert.asset} Futures Spread Anomaly</b>", ""]
            spread_str = details.get("spreadPercent", f"{alert.anomaly_score:.2f}")
            if "firstPrice" in details and "secondPrice" in details and details["firstPrice"] and details["secondPrice"]:
                s1 = str(details.get("firstSource", "Exchange 1")).capitalize()
                m1 = str(details.get("firstMarketType", "Futures")).capitalize()
                p1_str = _format_price(details["firstPrice"])

                s2 = str(details.get("secondSource", "Exchange 2")).capitalize()
                m2 = str(details.get("secondMarketType", "Futures")).capitalize()
                p2_str = _format_price(details["secondPrice"])

                lines.append(f"📊 <b>Спред:</b> <code>+{spread_str}%</code>")
                lines.append(f"• <b>{s1} {m1}:</b> <code>{p1_str}</code>")
                lines.append(f"• <b>{s2} {m2}:</b> <code>{p2_str}</code>")
            else:
                lines.append(f"📊 <b>Спред:</b> <code>+{spread_str}%</code>")
                lines.append(f"<i>{alert.summary}</i>")

        # 4. Spot-Futures Spread Anomaly
        elif "spot-futures-spread" in modules:
            lines = [f"{icon} <b>[{alert.priority.value}] {alert.asset} Spot-Futures Spread Anomaly</b>", ""]
            spread_str = details.get("spreadPercent", f"{alert.anomaly_score:.2f}")
            if "spotPrice" in details and "futuresPrice" in details and details["spotPrice"] and details["futuresPrice"]:
                s_spot = str(details.get("spotSource", "Spot")).capitalize()
                p_spot_str = _format_price(details["spotPrice"])

                s_fut = str(details.get("futuresSource", "Futures")).capitalize()
                p_fut_str = _format_price(details["futuresPrice"])

                lines.append(f"📊 <b>Спред:</b> <code>+{spread_str}%</code>")
                lines.append(f"• <b>{s_spot} Spot:</b> <code>{p_spot_str}</code>")
                lines.append(f"• <b>{s_fut} Futures:</b> <code>{p_fut_str}</code>")
            else:
                lines.append(f"📊 <b>Спред:</b> <code>+{spread_str}%</code>")
                lines.append(f"<i>{alert.summary}</i>")

        # 5. Fallback / Multi-module Anomaly
        else:
            lines = [f"{icon} <b>[{alert.priority.value}] {alert.asset} Anomaly Detected</b>", ""]
            spread_str = details.get("spreadPercent", f"{alert.anomaly_score:.2f}")
            lines.append(f"📊 <b>Показник:</b> <code>+{spread_str}%</code>")
            lines.append(f"<i>{alert.summary}</i>")

        lines.append("")
        lines.append(f"⏰ <i>{ts_str}</i>")
        return "\n".join(lines)

    def build_inline_keyboard(self, alert: Alert) -> dict[str, Any] | None:
        """Construct interactive 1-click URL buttons for monitored exchange pairs."""
        details = alert.details or {}
        buttons: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        # 1. DEX observations
        if "dexUrl" in details and details["dexUrl"]:
            url = str(details["dexUrl"])
            if url not in seen_urls:
                seen_urls.add(url)
                dex_name = str(details.get("dexName") or "DEX").capitalize()
                buttons.append({"text": f"🦄 Купити на {dex_name}", "url": url})
        elif "dexSource" in details:
            src = str(details["dexSource"])
            sym = str(details.get("dexSymbol", f"{alert.asset}USDT"))
            url = _get_exchange_url(src, "DEX", sym)
            if url and url not in seen_urls:
                seen_urls.add(url)
                buttons.append({"text": f"🦄 Купити на {src.capitalize()}", "url": url})

        # 2. Futures for DEX-Futures pair
        if "futuresSource" in details and "dexSource" in details:
            src = str(details["futuresSource"])
            sym = str(details.get("futuresSymbol", f"{alert.asset}USDT"))
            url = _get_exchange_url(src, "FUTURES", sym)
            if url and url not in seen_urls:
                seen_urls.add(url)
                buttons.append({"text": f"📉 Шорт на {src.capitalize()} Futures", "url": url})

        # 3. Observation 1 & 2
        if "firstSource" in details and "firstSymbol" in details:
            src = str(details["firstSource"])
            m_type = str(details.get("firstMarketType", "FUTURES"))
            sym = str(details["firstSymbol"])
            url = _get_exchange_url(src, m_type, sym)
            if url and url not in seen_urls:
                seen_urls.add(url)
                buttons.append({"text": f"🟡 {src.capitalize()} {m_type.capitalize()}", "url": url})

        if "secondSource" in details and "secondSymbol" in details:
            src = str(details["secondSource"])
            m_type = str(details.get("secondMarketType", "FUTURES"))
            sym = str(details["secondSymbol"])
            url = _get_exchange_url(src, m_type, sym)
            if url and url not in seen_urls:
                seen_urls.add(url)
                buttons.append({"text": f"⚫ {src.capitalize()} {m_type.capitalize()}", "url": url})

        # 4. Spot observations
        if "spotSource" in details:
            src = str(details["spotSource"])
            sym = str(details.get("spotSymbol", f"{alert.asset}USDT"))
            url = _get_exchange_url(src, "SPOT", sym)
            if url and url not in seen_urls:
                seen_urls.add(url)
                buttons.append({"text": f"📍 {src.capitalize()} Spot", "url": url})

        if "futuresSource" in details and "dexSource" not in details:
            src = str(details["futuresSource"])
            sym = str(details.get("futuresSymbol", f"{alert.asset}USDT"))
            url = _get_exchange_url(src, "FUTURES", sym)
            if url and url not in seen_urls:
                seen_urls.add(url)
                buttons.append({"text": f"📈 {src.capitalize()} Futures", "url": url})

        # 3. Fallback defaults
        if not buttons:
            sym = f"{alert.asset}USDT"
            binance_url = f"https://www.binance.com/en/futures/{sym}"
            bybit_url = f"https://www.bybit.com/trade/usdt/{sym}"
            buttons.append({"text": "🟡 Binance Futures", "url": binance_url})
            buttons.append({"text": "⚫ Bybit Futures", "url": bybit_url})

        # 4. Spread Chart Navigation Button
        target_symbol = str(details.get("firstSymbol") or details.get("spotSymbol") or details.get("symbol") or f"{alert.asset}USDT")
        target_module = alert.triggered_modules[0] if alert.triggered_modules else "futures-futures-spread"
        chart_url = f"http://localhost:3000/charts?asset={alert.asset}&symbol={target_symbol}&module={target_module}"
        chart_button = [{"text": "📈 Графік розходження (Spread Chart)", "url": chart_url}]

        return {"inline_keyboard": [buttons, chart_button]}

    def get_target_topic_id(self, alert: Alert) -> int | None:
        """Determine the Telegram message_thread_id based on triggered modules."""
        modules = alert.triggered_modules or ()
        if not modules:
            return self._config.telegram_topic_general

        # Strict routing to designated topic
        if "funding-spread" in modules and "futures-futures-spread" not in modules and "spot-futures-spread" not in modules:
            return self._config.telegram_topic_funding or self._config.telegram_topic_general

        if "futures-futures-spread" in modules:
            return self._config.telegram_topic_futures_futures or self._config.telegram_topic_general

        if "spot-futures-spread" in modules:
            return self._config.telegram_topic_spot_futures or self._config.telegram_topic_general

        if "dex-futures-spread" in modules:
            return self._config.telegram_topic_dex_futures or self._config.telegram_topic_general

        if "funding-spread" in modules:
            return self._config.telegram_topic_funding or self._config.telegram_topic_general

        # Multi-module anomaly
        return self._config.telegram_topic_general

    def _sanitize_error_message(self, raw_message: str) -> str:
        """Strip bot token from any error or exception message."""
        if self._config.telegram_bot_token and self._config.telegram_bot_token in raw_message:
            return raw_message.replace(self._config.telegram_bot_token, "***")
        return raw_message

    async def send_alert(self, alert: Alert) -> None:
        """Send an Alert to the configured Telegram chat with retries and funding anti-spam throttling."""
        if alert is None:
            raise TypeError("alert must not be None")

        if not self._config.telegram_bot_token:
            raise TelegramNotificationError("Telegram bot token is not configured")

        if not self._config.telegram_chat_id:
            raise TelegramNotificationError("Telegram chat ID is not configured")

        # Anti-spam throttling for funding rate alerts
        modules = alert.triggered_modules or ()
        if "funding-spread" in modules and "futures-futures-spread" not in modules:
            details = alert.details or {}
            cur_funding_metric = Decimal("0")
            if "fundingSpreadPercent" in details:
                try:
                    cur_funding_metric = Decimal(str(details["fundingSpreadPercent"]))
                except Exception:
                    pass

            now_ts = asyncio.get_event_loop().time()
            if alert.asset in self._funding_alert_cooldowns:
                last_ts, last_metric = self._funding_alert_cooldowns[alert.asset]
                time_passed = now_ts - last_ts
                metric_diff = abs(cur_funding_metric - last_metric)

                if (time_passed < self._config.funding_alert_cooldown_seconds) and (metric_diff < self._config.funding_alert_min_change_percent):
                    logger.info(
                        "Throttling repetitive funding alert for %s (cooldown active: %.0fs remaining, spread diff: %s)",
                        alert.asset,
                        self._config.funding_alert_cooldown_seconds - time_passed,
                        metric_diff,
                    )
                    return

            self._funding_alert_cooldowns[alert.asset] = (now_ts, cur_funding_metric)

        endpoint = f"{self._config.telegram_api_base_url.rstrip('/')}/bot{self._config.telegram_bot_token}/sendMessage"
        message_text = self.format_alert_message(alert)
        payload: dict[str, Any] = {
            "chat_id": self._config.telegram_chat_id,
            "text": message_text,
            "parse_mode": "HTML",
        }

        reply_markup = self.build_inline_keyboard(alert)
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        topic_id = self.get_target_topic_id(alert)
        if topic_id is not None:
            payload["message_thread_id"] = topic_id

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
