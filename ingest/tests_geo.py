"""Гео на шлюзе: таймзона->страна, извлечение IP, кросс-проверка VPN."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geo  # noqa: E402


def test_tz_country_covers_sea_market():
    assert geo.country_from_tz("Asia/Phnom_Penh") == "KH"
    assert geo.country_from_tz("Asia/Ho_Chi_Minh") == "VN"
    assert geo.country_from_tz("Asia/Bangkok") == "TH"
    assert geo.country_from_tz("Asia/Jakarta") == "ID"
    assert geo.country_from_tz("Nowhere/Void") == ""


def test_client_ip_prefers_real_header_and_skips_private():
    h = {"X-Real-Client-IP": "202.58.194.234", "X-Forwarded-For": "1.2.3.4"}
    assert geo.client_ip(h, "127.0.0.1") == "202.58.194.234"
    # приватный/loopback гео не несёт
    assert geo.client_ip({"X-Real-Client-IP": "10.0.0.5"}, "") == ""
    assert geo.client_ip({}, "127.0.0.1") == ""
    # фолбэк на первый XFF
    assert geo.client_ip({"X-Forwarded-For": "8.8.8.8, 10.0.0.1"}, "") == "8.8.8.8"


def test_resolve_uses_tz_when_no_geoip_db():
    out = geo.resolve({"X-Real-Client-IP": "202.58.194.234"}, "", "Asia/Phnom_Penh")
    assert out["ip"] == "202.58.194.234"
    assert out["country"] == "KH" and out["geo_src"] == "tz"
    assert out["tz_country"] == "KH"


def test_resolve_empty_without_signals():
    assert geo.resolve({}, "127.0.0.1", "") == {}
