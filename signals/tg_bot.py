#!/usr/bin/env python3
"""Telegram-бот подписки на алерты Retention Board.

Команды (работают и в личке, и в группе — где написали, тот чат и подпишется):
    /add     — подписать этот чат на уведомления
    /stop    — отписать этот чат
    /status  — текущее состояние: сайт казино, поток событий, их приёмник сигналов
    /help    — справка

Подписки хранятся в secrets/tg_chats.json — оттуда их читает monitor.sh.
Long-polling, без вебхуков: не нужен публичный URL.
"""
import json
import os
import time
from datetime import datetime, timezone

import requests
import clickhouse_connect

BOT = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHATS_FILE = os.environ.get("TG_CHATS_FILE", "/secrets/tg_chats.json")
SITE_URL = os.environ.get("MONITOR_SITE_URL", "https://billionbahis279.com")
CB_URL = os.environ.get("CALLBACK_HEALTH_URL", "")
CB_TOKEN = os.environ.get("RETENTION_BOARD_CALLBACK_TOKEN", "")
MAX_SILENCE = int(os.environ.get("MONITOR_STREAM_MAX_SILENCE", "900"))

CH = dict(host=os.environ.get("CH_HOST", "clickhouse"), port=int(os.environ.get("CH_PORT", "8123")),
          username=os.environ.get("CH_USER", "default"), password=os.environ.get("CH_PASSWORD", ""),
          database=os.environ.get("CH_DB", "retention"))

API = f"https://api.telegram.org/bot{BOT}"
HELP = ("<b>Retention Board — бот алертов</b>\n\n"
        "/add — подписать этот чат на уведомления\n"
        "/stop — отписать этот чат\n"
        "/status — состояние интеграции сейчас\n\n"
        "Присылаю сообщение только при <b>смене</b> состояния (падение / восстановление), не спамлю.")


def load_chats():
    try:
        with open(CHATS_FILE) as fh:
            return json.load(fh)
    except Exception:
        return []


def save_chats(chats):
    os.makedirs(os.path.dirname(CHATS_FILE), exist_ok=True)
    with open(CHATS_FILE, "w") as fh:
        json.dump(chats, fh, ensure_ascii=False, indent=2)


def send(chat_id, text):
    try:
        requests.post(f"{API}/sendMessage", timeout=15,
                      data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    except Exception as e:
        print(f"[bot] отправка в {chat_id} не удалась: {e}", flush=True)


def health():
    """Те же три проверки, что и в monitor.sh."""
    try:
        site = requests.get(SITE_URL, timeout=20).status_code
    except Exception:
        site = 0
    try:
        c = clickhouse_connect.get_client(**CH)
        silence = int(c.query("SELECT toInt64(ifNull(dateDiff('second', max(ingested_at), now64(3)), 999999)) "
                              "FROM live_events").result_rows[0][0])
    except Exception:
        silence = 999999
    cb = 0
    if CB_URL:
        try:
            cb = requests.get(CB_URL, timeout=20,
                              headers={"Authorization": f"Bearer {CB_TOKEN}"}).status_code
        except Exception:
            cb = 0
    ok_site, ok_stream, ok_cb = site == 200, silence <= MAX_SILENCE, (cb == 200 or not CB_URL)
    lines = [
        "<b>Retention Board — состояние</b>\n",
        f"{'✅' if ok_site else '🔴'} <b>Сайт казино:</b> {'работает' if ok_site else 'НЕДОСТУПЕН'} ({site})",
        f"{'✅' if ok_stream else '🔴'} <b>Поток событий:</b> "
        + (f"идёт (последнее {silence}с назад)" if ok_stream else f"ТИШИНА {silence // 60} мин"),
        f"{'✅' if ok_cb else '🔴'} <b>Приёмник сигналов:</b> {'отвечает' if ok_cb else 'НЕ ОТВЕЧАЕТ'} ({cb or 'n/a'})",
    ]
    if not ok_stream:
        lines.append("\n⚠️ Витрина, скоринг и сигналы <b>заморожены</b> до восстановления потока.")
    return "\n".join(lines)


def handle(msg):
    chat = msg.get("chat", {})
    cid = chat.get("id")
    title = chat.get("title") or chat.get("username") or chat.get("first_name") or str(cid)
    text = (msg.get("text") or "").split("@")[0].strip().lower()   # /add@MyBot → /add

    if text == "/add":
        chats = load_chats()
        if any(c["id"] == cid for c in chats):
            send(cid, "Этот чат уже подписан ✅")
            return
        chats.append({"id": cid, "title": title,
                      "added": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")})
        save_chats(chats)
        print(f"[bot] подписан чат {cid} ({title})", flush=True)
        send(cid, f"✅ Чат «{title}» подписан на алерты.\nВсего подписчиков: {len(chats)}")
    elif text in ("/stop", "/remove"):
        chats = [c for c in load_chats() if c["id"] != cid]
        save_chats(chats)
        print(f"[bot] отписан чат {cid}", flush=True)
        send(cid, "🚫 Чат отписан. Вернуть — /add")
    elif text == "/status":
        send(cid, health())
    elif text in ("/help", "/start"):
        send(cid, HELP)


def main():
    if not BOT:
        print("[bot] TELEGRAM_BOT_TOKEN не задан — жду настройки", flush=True)
        while not BOT:
            time.sleep(60)
    me = requests.get(f"{API}/getMe", timeout=15).json()
    print(f"[bot] запущен: @{me.get('result', {}).get('username')} · подписчиков: {len(load_chats())}", flush=True)
    offset = None
    while True:
        try:
            r = requests.get(f"{API}/getUpdates", timeout=40,
                             params={"timeout": 30, "offset": offset}).json()
            for upd in r.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("channel_post")
                if msg:
                    handle(msg)
        except Exception as e:      # noqa: BLE001 — бот не должен умирать
            print(f"[bot] ошибка опроса: {e}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
