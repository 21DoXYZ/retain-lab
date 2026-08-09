"""Разбор User-Agent на шлюзе: ОС, браузер, тип устройства, бот.

Зачем на сервере, если сниппет и так шлёт устройство: на iPhone/Safari
клиентские API (userAgentData, deviceMemory, battery, connection) пусты -
а UA-заголовок приходит ВСЕГДА. Серверный разбор закрывает iPhone-пробел и
даёт единый os/browser-family для когорт независимо от браузера.

Без внешних зависимостей: компактные регэкспы по семействам. Точную модель
телефона UA не несёт (и Apple, и reduced-UA Chrome её убрали) - только
семейство ОС, версию (где есть) и класс устройства.
"""

from __future__ import annotations

import re

_BOTS = re.compile(
    r"bot|crawl|spider|slurp|bingpreview|headless|phantom|puppeteer|"
    r"playwright|lighthouse|gtmetrix|pingdom|curl|wget|python-requests|"
    r"axios|go-http|java/|okhttp", re.I)

# порядок важен: специфичное раньше общего (Edge до Chrome, Chrome до Safari)
_BROWSERS = [
    ("Edge", re.compile(r"Edg(?:e|A|iOS)?/(\d+)", re.I)),
    ("Samsung Internet", re.compile(r"SamsungBrowser/(\d+)", re.I)),
    ("Opera", re.compile(r"OPR/(\d+)|Opera/(\d+)", re.I)),
    ("Yandex", re.compile(r"YaBrowser/(\d+)", re.I)),
    ("Firefox", re.compile(r"Firefox/(\d+)", re.I)),
    ("Chrome", re.compile(r"(?:Chrome|CriOS)/(\d+)", re.I)),
    ("Safari", re.compile(r"Version/(\d+).*Safari", re.I)),
]


def _os(ua: str) -> tuple[str, str]:
    """(семейство ОС, версия|'')."""
    m = re.search(r"(?:iPhone|CPU) OS (\d+[_\d]*) like Mac", ua)
    if m:
        return "iOS", m.group(1).replace("_", ".")
    m = re.search(r"iPad;.*OS (\d+[_\d]*)", ua)
    if m:
        return "iPadOS", m.group(1).replace("_", ".")
    m = re.search(r"Android (\d+(?:\.\d+)?)", ua)
    if m:
        return "Android", m.group(1)
    m = re.search(r"Mac OS X (\d+[_\d]*)", ua)
    if m:
        return "macOS", m.group(1).replace("_", ".")
    if "Windows NT 10" in ua:
        return "Windows", "10/11"
    if "Windows" in ua:
        return "Windows", ""
    if "Linux" in ua:
        return "Linux", ""
    return "", ""


def _device_type(ua: str) -> str:
    if re.search(r"iPad|Tablet|PlayBook|Silk", ua):
        return "tablet"
    if re.search(r"Mobi|iPhone|Android.*Mobile|iPod", ua):
        return "mobile"
    if "Android" in ua:               # Android без "Mobile" - планшет
        return "tablet"
    return "desktop"


def parse_ua(ua: str) -> dict:
    """{os, os_ver, browser, browser_ver, device_type, bot}. Пустой UA -> {}."""
    ua = str(ua or "").strip()
    if not ua:
        return {}
    out: dict = {"bot": 1 if _BOTS.search(ua) else 0}
    os_fam, os_ver = _os(ua)
    if os_fam:
        out["os"] = os_fam
    if os_ver:
        out["os_ver"] = os_ver
    for name, rx in _BROWSERS:
        m = rx.search(ua)
        if m:
            out["browser"] = name
            ver = next((g for g in m.groups() if g), "")
            if ver:
                out["browser_ver"] = ver
            break
    out["device_type"] = _device_type(ua)
    return out
