"""chains/senders.py — отправители каналов (MVP этапа 3а).

Единый интерфейс ``send(channel, player, template, params, ctx) -> (ok, reason)``.
Изолирует ЦЕПОЧКИ от способа доставки: сегодня прямые каналы, завтра — proxy без
правок runner-а (решение PII меняет только конфигурацию, не код исполнителя).

Каналы:
  • casino_webhook — POST CALLBACK_URL {"command":"send_message", player_id,
                     channel_hint, template_id, params} (Bearer, ретраи ×3);
  • bonus_grant    — POST CALLBACK_URL {"command":"bonus_grant", player_id,
                     bonus_id | ml_recommended} (те же ретраи);
  • email          — SMTP из env (SMTP_HOST/PORT/USER/PASS/FROM); нет конфигурации
                     → (False,'smtp_not_configured'); текст — render(texts[lang]);
  • telegram       — sendMessage через TELEGRAM_BOT_TOKEN на users.telegram_id;
                     нет токена/id → (False, ...).

DRY_RUN (SIGNALS_DRY_RUN, дефолт 1 — как pusher): ничего не уходит в сеть,
payload печатается, возвращается (True, 'dry_run'). Так согласуем формат с казино
и не шлём без их токена. Отправка ВСЕГДА логируется runner-ом в send_log.
"""
from __future__ import annotations

import json
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

# requests импортируется ЛЕНИВО внутри сетевых веток (_post_casino/_telegram):
# DRY_RUN и SMTP-путь без него работают — тесты и сухой прогон не требуют requests.

_LANG_FALLBACK = ('tr', 'ru')
_RETRIES = 3
_TIMEOUT = 30


# ── конфигурация каналов (из env; в тестах — прямой конструктор) ──────────────
@dataclass(frozen=True)
class SenderConfig:
    dry_run: bool = True
    callback_url: str = ''
    callback_token: str = ''
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_pass: str = ''
    smtp_from: str = ''
    tg_token: str = ''

    @classmethod
    def from_env(cls) -> 'SenderConfig':
        return cls(
            dry_run=os.environ.get('SIGNALS_DRY_RUN', '1') not in ('0', 'false', 'False', ''),
            callback_url=os.environ.get('CALLBACK_URL', '').strip(),
            callback_token=os.environ.get('CALLBACK_TOKEN', '').strip(),
            smtp_host=os.environ.get('SMTP_HOST', '').strip(),
            smtp_port=int(os.environ.get('SMTP_PORT', '587') or '587'),
            smtp_user=os.environ.get('SMTP_USER', '').strip(),
            smtp_pass=os.environ.get('SMTP_PASS', ''),
            smtp_from=os.environ.get('SMTP_FROM', '').strip(),
            tg_token=os.environ.get('TELEGRAM_BOT_TOKEN', '').strip(),
        )


# ── рендер шаблона ────────────────────────────────────────────────────────────
def pick_text(template: dict | None, lang: str) -> str:
    """Текст шаблона на языке игрока с фолбэком tr→ru. Пусто, если ничего нет."""
    if not template:
        return ''
    texts = template.get('texts') or {}
    if not isinstance(texts, dict):
        return ''
    for code in (lang, *_LANG_FALLBACK):
        if code and str(texts.get(code) or '').strip():
            return str(texts[code])
    return ''


def render(text: str, params: dict | None) -> str:
    """Подстановка {vars} значениями params. Неизвестные {vars} остаются как есть
    (без падения на format_map/KeyError и на «голых» скобках в тексте)."""
    out = text or ''
    for key, val in (params or {}).items():
        out = out.replace('{' + str(key) + '}', str(val))
    return out


# ── общий POST на колбэк казино (ретраи ×3, как pusher) ───────────────────────
def _post_casino(command: str, payload: dict, ctx: SenderConfig) -> tuple[bool, str]:
    body = {'command': command, **payload}
    if ctx.dry_run:
        print(f"[chains] DRY_RUN {command}: "
              f"{json.dumps(body, ensure_ascii=False)}", flush=True)
        return True, 'dry_run'
    if not ctx.callback_url or not ctx.callback_token:
        return False, 'callback_not_configured'
    import requests                                   # ленивый импорт сетевой зависимости
    last = 'no_attempt'
    for attempt in range(1, _RETRIES + 1):
        try:
            r = requests.post(
                ctx.callback_url, json=body,
                headers={'Authorization': f'Bearer {ctx.callback_token}',
                         'Content-Type': 'application/json'},
                timeout=_TIMEOUT)
            if r.status_code < 300:
                return True, 'sent'
            last = f'http_{r.status_code}'
            print(f"  [chains attempt {attempt}] HTTP {r.status_code}: {r.text[:200]}", flush=True)
        except Exception as e:                       # noqa: BLE001
            last = f'error:{type(e).__name__}'
            print(f"  [chains attempt {attempt}] {e}", flush=True)
    return False, last


# ── каналы ────────────────────────────────────────────────────────────────────
def _casino_message(player: dict, template: dict | None, params: dict,
                    ctx: SenderConfig) -> tuple[bool, str]:
    return _post_casino('send_message', {
        'player_id': int(player['casino_player_id']),
        'channel_hint': (template or {}).get('channel_kind', 'casino_webhook'),
        'template_id': (template or {}).get('template_id', ''),
        'params': params or {},
    }, ctx)


def _casino_bonus(player: dict, params: dict, ctx: SenderConfig) -> tuple[bool, str]:
    bonus = str((params or {}).get('bonus') or 'ml_recommended')
    body: dict[str, Any] = {'player_id': int(player['casino_player_id'])}
    if bonus == 'ml_recommended':
        body['ml_recommended'] = True
    else:
        body['bonus_id'] = bonus
    extra = {k: v for k, v in (params or {}).items() if k != 'bonus'}
    if extra:
        body['params'] = extra
    return _post_casino('bonus_grant', body, ctx)


def _email(player: dict, template: dict | None, params: dict,
           ctx: SenderConfig) -> tuple[bool, str]:
    if not (ctx.smtp_host and ctx.smtp_from):
        return False, 'smtp_not_configured'
    to = str(player.get('email') or '').strip()
    if not to:
        return False, 'no_email'
    lang = str(player.get('language') or 'tr')
    text = render(pick_text(template, lang), params)
    if not text:
        return False, 'no_template_text'
    if ctx.dry_run:
        print(f"[chains] DRY_RUN email → {to}: {text[:200]}", flush=True)
        return True, 'dry_run'
    try:
        msg = EmailMessage()
        msg['From'] = ctx.smtp_from
        msg['To'] = to
        msg['Subject'] = (template or {}).get('name', 'Retivo')
        msg.set_content(text)
        with smtplib.SMTP(ctx.smtp_host, ctx.smtp_port, timeout=_TIMEOUT) as s:
            s.starttls()
            if ctx.smtp_user:
                s.login(ctx.smtp_user, ctx.smtp_pass)
            s.send_message(msg)
        return True, 'sent'
    except Exception as e:                           # noqa: BLE001
        return False, f'error:{type(e).__name__}'


def _telegram(player: dict, template: dict | None, params: dict,
              ctx: SenderConfig) -> tuple[bool, str]:
    if not ctx.tg_token:
        return False, 'no_tg_token'
    chat = str(player.get('telegram_id') or '').strip()
    if not chat or chat == '0':
        return False, 'no_telegram'
    lang = str(player.get('language') or 'tr')
    text = render(pick_text(template, lang), params)
    if not text:
        return False, 'no_template_text'
    if ctx.dry_run:
        print(f"[chains] DRY_RUN telegram → {chat}: {text[:200]}", flush=True)
        return True, 'dry_run'
    import requests                                   # ленивый импорт сетевой зависимости
    for attempt in range(1, _RETRIES + 1):
        try:
            r = requests.post(
                f'https://api.telegram.org/bot{ctx.tg_token}/sendMessage',
                json={'chat_id': chat, 'text': text}, timeout=_TIMEOUT)
            if r.status_code < 300:
                return True, 'sent'
        except Exception as e:                       # noqa: BLE001
            print(f"  [chains tg attempt {attempt}] {e}", flush=True)
    return False, 'tg_failed'


# ── публичный вход ────────────────────────────────────────────────────────────
def send(channel: str, player: dict, template: dict | None, params: dict | None,
         ctx: SenderConfig) -> tuple[bool, str]:
    """Отправить по каналу. Возвращает (ok, reason) — reason='sent'|'dry_run' при
    успехе, иначе машинный код ошибки (для send_log.reason)."""
    params = params or {}
    if channel == 'casino_webhook':
        return _casino_message(player, template, params, ctx)
    if channel == 'bonus_grant':
        return _casino_bonus(player, params, ctx)
    if channel == 'email':
        return _email(player, template, params, ctx)
    if channel == 'telegram':
        return _telegram(player, template, params, ctx)
    return False, 'unknown_channel'
