"""chains/checks.py — проверки перед отправкой сообщения / начислением бонуса.

Чистые функции: НИКАКИХ глобальных подключений. Каждая проверка получает данные
явно (dict игрока и/или `query`-callable к ClickHouse) и возвращает кортеж
``(ok: bool, reason: str)`` — reason пустой при ok=True, иначе короткий машинный
код причины (пишется в chain_events.reason / send_log.reason).

`query(sql, params) -> rows` — callable, выполняющий CH-запрос и отдающий
result_rows (список кортежей). Инъекция в runner-е (обёртка над clickhouse_connect),
в тестах — мок. Все значения передаются через параметры CH ({name:Type}).

Состав (по плану W4-T4, ВСЕ — из уже существующих данных):
  • consent           — marketing_consent AND NOT opt_out/do_not_contact/self_excluded (users);
  • channel_available — email≠'' / telegram_id≠0; casino_webhook — контакты у казино (skip);
  • template_language — у шаблона есть текст на языке игрока (фолбэк tr→ru);
  • not_in_session    — игрок не в игровой сессии сейчас (session_start без session_end за 2ч);
  • fatigue           — не больше FATIGUE_MAX_SENDS касаний за FATIGUE_WINDOW_DAYS (send_log);
  • safety_segment    — не в сегменте safety_restricted (если он есть в segment_members).

Продуктовое решение (задокументировано, отклонение — см. отчёт W4-T4): marketing
consent + канал + язык гейтят ИСХОДЯЩИЕ СООБЩЕНИЯ (send_message). Начисление бонуса
(bonus_grant) — не контакт, а награда: его гейтят только ответственная игра
(self_excluded) + safety_restricted + fatigue + not_in_session, без marketing-consent.
Композицию проверок по типу узла делает runner (SEND_CHECKS / GRANT_CHECKS).
"""
from __future__ import annotations

import os
from typing import Any, Callable, Iterable

# callable(sql, params) -> rows (список кортежей result_rows ClickHouse)
Query = Callable[[str, dict], Iterable[tuple]]

_TRUTHY = frozenset({'t', 'true', '1', 'yes', 'y', 'on'})

# порядок фолбэка языка шаблона: язык игрока → tr → ru (как в senders.render)
_LANG_FALLBACK = ('tr', 'ru')

SAFETY_SYS_NAME = 'safety_restricted'


def _truthy(v: Any) -> bool:
    """Строковый/числовой флаг казино ('t'/'f'/''/1/0) → bool. Пусто = False."""
    if isinstance(v, bool):
        return v
    return str(v if v is not None else '').strip().lower() in _TRUTHY


def _scalar(rows: Iterable[tuple], default: int = 0) -> Any:
    """Первое значение первой строки (или default, если пусто) — CH count-запросы."""
    for r in rows:
        return r[0]
    return default


# ── consent (для send_message) ───────────────────────────────────────────────
# Режим неизвестного согласия (поля пустые — казино не шлёт opt-in, факт данных):
#   info    — ПРОПУСКАЕМ отправку, помечая reason 'consent_unknown' (решение
#             владельца 18.07: «сообщать, но не резать — для тестов нужно»);
#   enforce — fail-closed: без явного согласия не пишем (включить на проде,
#             когда казино начнёт слать opt_in_changed).
# Явные запреты (self_excluded / do_not_contact / opt_out) режут ВСЕГДА,
# независимо от режима.
CONSENT_MODE = os.environ.get('CHAINS_CONSENT_MODE', 'info').strip().lower()


def check_consent(player: dict) -> tuple[bool, str]:
    """Игрок не запретил маркетинговый контакт (users).

    Порядок причин от «жёсткой» к «мягкой»: self_excluded → do_not_contact →
    opted_out. Пустое согласие: режим info → (True, 'consent_unknown') — отправка
    идёт, причина попадает в send_log как пометка; режим enforce → отказ.
    """
    if _truthy(player.get('self_excluded')):
        return False, 'self_excluded'
    if _truthy(player.get('do_not_contact')):
        return False, 'do_not_contact'
    if _truthy(player.get('opt_out')):
        return False, 'opted_out'
    if not _truthy(player.get('marketing_consent')):
        if CONSENT_MODE == 'enforce':
            return False, 'no_marketing_consent'
        return True, 'consent_unknown'
    return True, ''


def check_not_restricted(player: dict) -> tuple[bool, str]:
    """Ответственная игра: не самоисключён (гейт для bonus_grant — без marketing-consent)."""
    if _truthy(player.get('self_excluded')):
        return False, 'self_excluded'
    return True, ''


# ── канал доступен ───────────────────────────────────────────────────────────
def check_channel(channel: str, player: dict) -> tuple[bool, str]:
    """Есть ли у игрока адрес для канала. casino_webhook — контакты у казино (ok)."""
    if channel == 'casino_webhook':
        return True, ''
    if channel == 'email':
        return (True, '') if str(player.get('email') or '').strip() else (False, 'no_email')
    if channel == 'telegram':
        tid = str(player.get('telegram_id') or '').strip()
        return (True, '') if tid and tid != '0' else (False, 'no_telegram')
    return False, 'unknown_channel'


# ── языковая версия шаблона ──────────────────────────────────────────────────
def check_template_language(template: dict | None, lang: str) -> tuple[bool, str]:
    """У шаблона есть непустой текст на языке игрока или по фолбэку (tr→ru)."""
    if not template:
        return False, 'no_template'
    texts = template.get('texts') or {}
    if not isinstance(texts, dict):
        return False, 'bad_template'
    for code in (lang, *_LANG_FALLBACK):
        if code and str(texts.get(code) or '').strip():
            return True, ''
    return False, 'no_template_text'


# ── не в игровой сессии сейчас ───────────────────────────────────────────────
def check_not_in_session(player_id: int, query: Query, window_hours: int = 2) -> tuple[bool, str]:
    """Нет открытой сессии за последние window_hours (session_start > session_end).

    Эвристика по live_events: (число start − число end) в окне > 0 ⇒ игрок сейчас
    внутри сессии — не дёргаем. Окно от now64(3) UTC самого CH (без локального now()).
    """
    rows = query(
        "SELECT countIf(event_type='session_start') - countIf(event_type='session_end') "
        "FROM live_events WHERE casino_player_id = {pid:UInt32} "
        "AND ts >= now64(3) - INTERVAL {h:UInt32} HOUR",
        {'pid': int(player_id), 'h': int(window_hours)})
    return (False, 'in_session') if int(_scalar(rows) or 0) > 0 else (True, '')


# ── усталость (fatigue) ──────────────────────────────────────────────────────
def check_fatigue(player_id: int, query: Query, max_sends: int = 3,
                  window_days: int = 7) -> tuple[bool, str]:
    """Не больше max_sends реальных касаний за window_days (send_log, все цепочки).

    Считаем доставленные/отправленные (не skipped/failed): status в
    sent|delivered|opened|clicked. Достигнут лимит ⇒ (False,'fatigue').
    """
    rows = query(
        "SELECT count() FROM send_log WHERE casino_player_id = {pid:UInt32} "
        "AND status IN ('sent','delivered','opened','clicked') "
        "AND ts >= now64(3) - INTERVAL {d:UInt32} DAY",
        {'pid': int(player_id), 'd': int(window_days)})
    return (False, 'fatigue') if int(_scalar(rows) or 0) >= int(max_sends) else (True, '')


# ── сегмент-предохранитель ───────────────────────────────────────────────────
def check_safety_segment(player_id: int, query: Query,
                         sys_name: str = SAFETY_SYS_NAME) -> tuple[bool, str]:
    """Игрок не входит в сегмент-предохранитель safety_restricted (если он существует).

    Если сегмент не материализован — участников нет, проверка проходит.
    """
    rows = query(
        "SELECT count() FROM segment_members "
        "WHERE sys_name = {s:String} AND casino_player_id = {pid:UInt32}",
        {'s': sys_name, 'pid': int(player_id)})
    return (False, 'safety_restricted') if int(_scalar(rows) or 0) > 0 else (True, '')
