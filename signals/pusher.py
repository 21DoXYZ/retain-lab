#!/usr/bin/env python3
"""Пушер сигналов модели: ClickHouse (player_actions) -> callback казино.

Читает предсказания моделей и батчами POST'ит их на эндпоинт казино
(CALLBACK_URL) с Bearer-токеном. Батч-режим: запускается по расписанию
(cron) после скоринга, не постоянный сервис.

DRY_RUN=1 (по умолчанию) — ничего не отправляет, только печатает, что БЫ
отправил (удобно согласовать формат с казино и не слать без их токена).
"""
import os
import sys
import json
from datetime import datetime, timezone

import clickhouse_connect
import requests

CH_HOST = os.environ.get("CH_HOST", "clickhouse")
CH_PORT = int(os.environ.get("CH_PORT", "8123"))
CH_USER = os.environ.get("CH_USER", "default")
CH_PASSWORD = os.environ.get("CH_PASSWORD", "")
CH_DB = os.environ.get("CH_DB", "retention")

CALLBACK_URL    = os.environ.get("CALLBACK_URL", "")
CALLBACK_HEALTH = os.environ.get("CALLBACK_HEALTH_URL", "")
CALLBACK_TOKEN  = os.environ.get("CALLBACK_TOKEN", "")
BATCH           = int(os.environ.get("BATCH_SIZE", "500"))
MODEL_VERSION   = os.environ.get("MODEL_VERSION", "")
DRY_RUN         = os.environ.get("SIGNALS_DRY_RUN", "1") not in ("0", "false", "False", "")

# только игроки, которых модели реально оценили
SQL = """
SELECT casino_player_id, round(pred_ltv_d90, 2), p_churn, p_2nd_deposit,
       early_tier, action, bonus, toInt64(round(priority))
FROM player_actions
WHERE pred_ltv_d90 > 0 OR p_churn IS NOT NULL
ORDER BY priority DESC
"""

# API-контракт: машиночитаемые enum-коды (русские подписи из вью — только для нашего UI)
ACTION_CODES = ("CONVERT", "NUDGE", "SAVE", "WINBACK", "NURTURE")

BONUS_MAP = [                       # (подстрока в UI-строке, канонический код)
    ("первый депозит", "first_deposit_bonus"),
    ("2-й депозит",    "second_deposit_reload"),
    ("VIP",            "vip_offer"),
    ("фриспин",        "freespins"),
    ("релоад",         "reload_cashback"),
    ("кэшбэк",         "reload_cashback"),
]


def map_action(action):
    """'CONVERT · первый депозит' -> 'CONVERT'; 'наблюдать' -> 'MONITOR'."""
    if not action:
        return None
    head = action.split("·")[0].strip()
    return head if head in ACTION_CODES else "MONITOR"


def map_bonus(bonus):
    if not bonus:
        return None
    for needle, code in BONUS_MAP:
        if needle.lower() in bonus.lower():
            return code
    return "other"


# Валидатор казино пока принимает только 5 действий (без MONITOR) — «наблюдать»
# не шлём, пока они не расширят enum. INCLUDE_MONITOR=1 — включить обратно.
INCLUDE_MONITOR = os.environ.get("INCLUDE_MONITOR", "0") in ("1", "true")

def build_signals(rows):
    out = []
    skipped = 0
    for pid, ltv, pch, p2, tier, action, bonus, prio in rows:
        if map_action(action) == "MONITOR" and not INCLUDE_MONITOR:
            skipped += 1
            continue
        out.append({
            "casino_player_id": int(pid),
            "pred_ltv_d90": float(ltv or 0),
            "p_churn_30d": None if pch is None else round(float(pch), 4),
            "p_next_deposit": None if p2 is None else round(float(p2), 4),
            "ltv_tier": tier or None,
            "recommended_action": map_action(action),
            "recommended_bonus": map_bonus(bonus),
            "priority": int(prio or 0),
        })
    if skipped:
        print(f"[signals] пропущено MONITOR-сигналов: {skipped} (казино не принимает MONITOR)", flush=True)
    return out


def post_batch(batch, scored_at):
    payload = {
        "model_version": MODEL_VERSION or scored_at[:10],
        "scored_at": scored_at,
        "signals": batch,
    }
    if DRY_RUN:
        return True
    for attempt in range(1, 4):
        try:
            r = requests.post(CALLBACK_URL, json=payload,
                              headers={"Authorization": f"Bearer {CALLBACK_TOKEN}",
                                       "Content-Type": "application/json"},
                              timeout=30)
            if r.status_code < 300:
                return True
            print(f"  [attempt {attempt}] HTTP {r.status_code}: {r.text[:200]}", flush=True)
        except Exception as e:
            print(f"  [attempt {attempt}] {e}", flush=True)
    return False


def main():
    client = clickhouse_connect.get_client(host=CH_HOST, port=CH_PORT, username=CH_USER,
                                           password=CH_PASSWORD, database=CH_DB)
    rows = client.query(SQL).result_rows
    signals = build_signals(rows)
    scored_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[signals] сигналов к отправке: {len(signals)} · DRY_RUN={DRY_RUN} · url={CALLBACK_URL or '—'}", flush=True)

    if not signals:
        print("[signals] нечего отправлять (модели ещё не скорены?)", flush=True)
        return 0

    if DRY_RUN:
        print("[signals] пример payload (DRY_RUN, ничего не отправлено):", flush=True)
        print(json.dumps({"model_version": MODEL_VERSION or scored_at[:10],
                          "scored_at": scored_at, "signals": signals[:3]},
                         ensure_ascii=False, indent=2), flush=True)
        return 0

    if not CALLBACK_URL or not CALLBACK_TOKEN:
        print("[signals] ERROR: CALLBACK_URL/CALLBACK_TOKEN не заданы", flush=True)
        return 1

    # health-check перед отправкой
    if CALLBACK_HEALTH:
        try:
            h = requests.get(CALLBACK_HEALTH, timeout=15)
            print(f"[signals] health {CALLBACK_HEALTH} -> {h.status_code}", flush=True)
        except Exception as e:
            print(f"[signals] health check failed: {e}", flush=True)

    sent = ok = 0
    for i in range(0, len(signals), BATCH):
        batch = signals[i:i + BATCH]
        sent += len(batch)
        if post_batch(batch, scored_at):
            ok += len(batch)
        else:
            print(f"[signals] батч {i//BATCH} не отправлен ({len(batch)} сигналов)", flush=True)
    print(f"[signals] отправлено {ok}/{sent}", flush=True)
    return 0 if ok == sent else 1


if __name__ == "__main__":
    sys.exit(main())
