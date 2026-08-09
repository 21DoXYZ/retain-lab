"""Гео на шлюзе: страна из IP-адреса и из таймзоны браузера.

Рынок - Юго-Восточная Азия (Камбоджа, Вьетнам и соседи), регуляция мягче -
поэтому гео собираем и храним, включая сам IP.

Два независимых источника, они дополняют друг друга:
  • IP -> страна: реальный адрес приходит в X-Real-Client-IP (Caddy). Точную
    страну по IP даёт офлайн-база MaxMind GeoLite2, если она примонтирована
    (GEOIP_DB); без неё остаётся сам IP - обогатим позже.
  • Таймзона -> страна: IANA-зона из браузера (Asia/Phnom_Penh -> KH). Работает
    ВСЕГДА и без сети, для нашего региона точна: у большинства стран ЮВА одна
    зона на страну. Кросс-проверка с IP ловит VPN и путешественников.
"""

from __future__ import annotations

import ipaddress
import os

# IANA-таймзона -> ISO-страна. Полный регион ЮВА + мировые мейджоры. Зоны,
# однозначно принадлежащие одной стране (для ЮВА это почти все), дают страну
# бесплатно и офлайн.
TZ_COUNTRY = {
    # Юго-Восточная Азия - наш рынок, максимально полно
    "Asia/Phnom_Penh": "KH", "Asia/Ho_Chi_Minh": "VN", "Asia/Saigon": "VN",
    "Asia/Bangkok": "TH", "Asia/Vientiane": "LA", "Asia/Yangon": "MM",
    "Asia/Kuala_Lumpur": "MY", "Asia/Kuching": "MY", "Asia/Singapore": "SG",
    "Asia/Jakarta": "ID", "Asia/Pontianak": "ID", "Asia/Makassar": "ID",
    "Asia/Jayapura": "ID", "Asia/Manila": "PH", "Asia/Brunei": "BN",
    "Asia/Dili": "TL",
    # Остальная Азия
    "Asia/Dubai": "AE", "Asia/Hong_Kong": "HK", "Asia/Shanghai": "CN",
    "Asia/Taipei": "TW", "Asia/Tokyo": "JP", "Asia/Seoul": "KR",
    "Asia/Kolkata": "IN", "Asia/Calcutta": "IN", "Asia/Karachi": "PK",
    "Asia/Dhaka": "BD", "Asia/Kathmandu": "NP", "Asia/Colombo": "LK",
    "Asia/Almaty": "KZ", "Asia/Tashkent": "UZ", "Asia/Tbilisi": "GE",
    "Asia/Yerevan": "AM", "Asia/Baku": "AZ", "Asia/Tehran": "IR",
    "Asia/Jerusalem": "IL", "Asia/Riyadh": "SA", "Asia/Qatar": "QA",
    "Asia/Kuwait": "KW", "Asia/Beirut": "LB", "Asia/Amman": "JO",
    # Мировые мейджоры (клиенты и трафик оттуда тоже бывают)
    "Europe/London": "GB", "Europe/Paris": "FR", "Europe/Berlin": "DE",
    "Europe/Madrid": "ES", "Europe/Rome": "IT", "Europe/Amsterdam": "NL",
    "Europe/Moscow": "RU", "Europe/Kyiv": "UA", "Europe/Kiev": "UA",
    "Europe/Warsaw": "PL", "Europe/Istanbul": "TR", "Europe/Lisbon": "PT",
    "America/New_York": "US", "America/Chicago": "US", "America/Denver": "US",
    "America/Los_Angeles": "US", "America/Phoenix": "US",
    "America/Toronto": "CA", "America/Vancouver": "CA",
    "America/Mexico_City": "MX", "America/Sao_Paulo": "BR",
    "America/Buenos_Aires": "AR", "America/Bogota": "CO",
    "Australia/Sydney": "AU", "Australia/Melbourne": "AU",
    "Australia/Perth": "AU", "Pacific/Auckland": "NZ", "Africa/Cairo": "EG",
    "Africa/Lagos": "NG", "Africa/Johannesburg": "ZA", "Africa/Nairobi": "KE",
}


def country_from_tz(tz: str) -> str:
    """ISO-страна из IANA-таймзоны, '' если не знаем зону."""
    return TZ_COUNTRY.get(str(tz or "").strip(), "")


def client_ip(headers, remote_addr: str = "") -> str:
    """Реальный IP клиента. X-Real-Client-IP ставит Caddy (подделать нельзя);
    фолбэк - первый адрес X-Forwarded-For; затем remote_addr."""
    raw = (headers.get("X-Real-Client-IP")
           or (headers.get("X-Forwarded-For", "").split(",")[0])
           or remote_addr or "").strip()
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return ""
    # приватные/loopback адреса гео не несут (локалка, docker-сеть)
    return "" if (ip.is_private or ip.is_loopback) else str(ip)


_reader = None
_reader_tried = False


def _geoip_reader():
    """Ленивый ридер MaxMind GeoLite2, если БД примонтирована и пакет есть."""
    global _reader, _reader_tried
    if _reader_tried:
        return _reader
    _reader_tried = True
    path = os.environ.get("GEOIP_DB", "/secrets/GeoLite2-City.mmdb")
    if not os.path.exists(path):
        return None
    try:
        import maxminddb
        _reader = maxminddb.open_database(path)
    except Exception:               # noqa: BLE001 - нет пакета/битая БД
        _reader = None
    return _reader


def geo_from_ip(ip: str) -> dict:
    """{country, region, city} из IP через GeoLite2. {} без базы или без матча.
    Точное город/регион; когда базы нет - страну даёт таймзона (см. resolve)."""
    if not ip:
        return {}
    reader = _geoip_reader()
    if reader is None:
        return {}
    try:
        rec = reader.get(ip) or {}
    except Exception:               # noqa: BLE001
        return {}
    out = {}
    c = (rec.get("country") or {}).get("iso_code")
    if c:
        out["country"] = c
    subs = rec.get("subdivisions") or []
    if subs:
        code = subs[0].get("iso_code") or (subs[0].get("names") or {}).get("en")
        if code:
            out["region"] = str(code)
    city = ((rec.get("city") or {}).get("names") or {}).get("en")
    if city:
        out["city"] = city
    return out


def resolve(headers, remote_addr: str, tz: str) -> dict:
    """Гео события: {ip, country, region?, city?, geo_src, tz_country, vpn?}.

    country - лучшее, что есть: из IP (точнее), иначе из таймзоны. tz_country
    хранится отдельно всегда: расхождение с IP-страной = VPN/путешественник,
    сам по себе сигнал.
    """
    ip = client_ip(headers, remote_addr)
    tz_country = country_from_tz(tz)
    out: dict = {}
    if ip:
        out["ip"] = ip
    if tz_country:
        out["tz_country"] = tz_country

    ip_geo = geo_from_ip(ip)
    if ip_geo:
        out.update(ip_geo)
        out["geo_src"] = "ip"
        if tz_country and ip_geo.get("country") and tz_country != ip_geo["country"]:
            out["vpn"] = 1          # страна IP и страна таймзоны расходятся
    elif tz_country:
        out["country"] = tz_country
        out["geo_src"] = "tz"
    return out
