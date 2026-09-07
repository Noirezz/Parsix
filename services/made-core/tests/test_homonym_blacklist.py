"""Unit tests for HomonymBlacklist component."""

from __future__ import annotations

from decimal import Decimal

from made_core.application.homonym_filter import HomonymBlacklist


def test_homonym_blacklist_initialization():
    bl = HomonymBlacklist(initial_blacklist=["ONUSDT", "BOXUSDT"])
    assert bl.is_blacklisted("ONUSDT") is True
    assert bl.is_blacklisted("onusdt") is True
    assert bl.is_blacklisted("BOXUSDT") is True
    assert bl.is_blacklisted("BTCUSDT") is False


def test_homonym_blacklist_add_and_membership():
    bl = HomonymBlacklist()
    assert bl.is_blacklisted("TESTCOIN") is False
    bl.add("testcoin", reason="manual_test")
    assert bl.is_blacklisted("TESTCOIN") is True
    assert "TESTCOIN" in bl.get_blacklisted()


def test_homonym_auto_detection_and_blacklisting():
    bl = HomonymBlacklist(max_price_ratio=Decimal("2.0"), auto_blacklist=True)

    # Legitimate high spread: $1.00 vs $1.70 (ratio 1.70 < 2.0) -> Not a homonym
    is_homonym = bl.check_and_record_homonym("LEGITUSDT", "LEGIT", Decimal("1.00"), Decimal("1.70"))
    assert is_homonym is False
    assert bl.is_blacklisted("LEGITUSDT") is False

    # Homonym collision: $0.25 vs $73.00 (ratio 292.0 >= 2.0) -> Auto-blacklisted!
    is_homonym = bl.check_and_record_homonym("ONUSDT", "ON", Decimal("0.25"), Decimal("73.00"))
    assert is_homonym is True
    assert bl.is_blacklisted("ONUSDT") is True
    assert bl.is_blacklisted("ON") is True

    # Subsequent check is immediately O(1) True
    assert bl.is_blacklisted("ONUSDT") is True
