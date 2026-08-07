"""Время события: клиент задаёт его сам, а мы обязаны ему не верить.

У браузера часы могут врать на годы, серверный интегратор может прислать что
угодно. Событие «из будущего» отравляет ВСЕ окна аналитики: оно месяцами
считается свежим, держит человека в активных и ломает стадии.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

FMT = "%Y-%m-%d %H:%M:%S.%f"
FUTURE_TOLERANCE_S = 300      # небольшой сдвиг часов - это нормально
MAX_PAST_DAYS = 3650          # старее - явно мусор


def sane_ts(raw, now: datetime | None = None) -> str:
    """Время события в формате ClickHouse. Будущее и мусор заменяем приёмом."""
    now = now or datetime.now(tz=timezone.utc)
    now_s = now.strftime(FMT)[:-3]
    text = str(raw or "").strip().replace("T", " ").replace("Z", "")
    for pattern in (FMT, "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(text[:26], pattern).replace(tzinfo=timezone.utc)
            break
        except ValueError:
            continue
    else:
        return now_s
    if parsed > now + timedelta(seconds=FUTURE_TOLERANCE_S):
        return now_s
    if parsed < now - timedelta(days=MAX_PAST_DAYS):
        return now_s
    return parsed.strftime(FMT)[:-3]
