"""Серверный разбор UA: закрывает iPhone-пробел (клиентские API там пусты)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ua as uamod  # noqa: E402

IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
ANDROID = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36")
BOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


def test_iphone_os_and_browser_from_ua():
    """Именно то, чего на iPhone НЕ дают клиентские API."""
    d = uamod.parse_ua(IPHONE)
    assert d["os"] == "iOS" and d["os_ver"] == "17.5"
    assert d["browser"] == "Safari" and d["browser_ver"] == "17"
    assert d["device_type"] == "mobile" and d["bot"] == 0


def test_android_chrome():
    d = uamod.parse_ua(ANDROID)
    assert d["os"] == "Android" and d["os_ver"] == "14"
    assert d["browser"] == "Chrome" and d["device_type"] == "mobile"


def test_bot_flagged():
    assert uamod.parse_ua(BOT)["bot"] == 1
    assert uamod.parse_ua("python-requests/2.31")["bot"] == 1


def test_desktop_and_edge_before_chrome():
    edge = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0")
    d = uamod.parse_ua(edge)
    assert d["os"] == "Windows" and d["browser"] == "Edge"
    assert d["device_type"] == "desktop"


def test_empty_ua():
    assert uamod.parse_ua("") == {}
