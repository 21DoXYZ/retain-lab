#!/usr/bin/env python3
"""RT-триггер: мгновенная реакция на события (секунды), поверх батч-прогнозов.

Каждый тик (~1с):
  1) читает НОВЫЕ события из live_events (по watermark);
  2) сверяет с кэшем прогнозов player_actions (обновляется раз в 60с —
     батч-петля всё равно пересчитывает их раз в 5 минут);
  3) применяет правила; сработавшие триггеры мгновенно POST'ит на колбэк
     казино и пишет в retention.trigger_log (для UI/аудита).

Правила (пороги через env):
  losing_valuable — игрок с прогнозом LTV >= TRIGGER_LTV_MIN проиграл за последние
                    10 минут >= TRIGGER_LOSS_TH  ->  SAVE / срочный кэшбэк
  big_deposit     — успешный депозит >= TRIGGER_DEP_BIG  ->  NUDGE на волне

Кулдаун: один и тот же (игрок, правило) не чаще раза в TRIGGER_COOLDOWN_MIN минут
(переживает рестарт — восстанавливается из trigger_log).
"""
import os
import json
import time
import uuid
from datetime import datetime, timezone

import clickhouse_connect
import requests

CH_HOST = os.environ.get("CH_HOST", "clickhouse")
CH_PORT = int(os.environ.get("CH_PORT", "8123"))
CH_USER = os.environ.get("CH_USER", "default")
CH_PASSWORD = os.environ.get("CH_PASSWORD", "")
CH_DB = os.environ.get("CH_DB", "retention")

CALLBACK_URL   = os.environ.get("CALLBACK_URL", "")
CALLBACK_TOKEN = os.environ.get("CALLBACK_TOKEN", "")

POLL_MS      = int(os.environ.get("TRIGGER_POLL_MS", "1000"))
LOSS_TH      = float(os.environ.get("TRIGGER_LOSS_TH", "1000"))    # проигрыш за 10 мин, TRY
LTV_MIN      = float(os.environ.get("TRIGGER_LTV_MIN", "10000"))   # порог «ценный»
DEP_BIG      = float(os.environ.get("TRIGGER_DEP_BIG", "1000"))    # крупный депозит, TRY
COOLDOWN_MIN = int(os.environ.get("TRIGGER_COOLDOWN_MIN", "30"))

ENV_FILE = os.environ.get("ENV_FILE", "/host/.env")   # смонтированный .env для горячих флагов

client = None
_actions = {}            # casino_player_id -> (pred_ltv_d90, p_churn, dep_count)
_actions_at = 0.0
_cooldown = {}           # (player, rule) -> monotonic deadline
_enabled_state = None    # для лога смены состояния


def predictions_enabled():
    """PREDICTIONS_ENABLED из .env (горячо, каждый тик): шлём ТОЛЬКО при явном 1/true.

    FAIL-CLOSED, и это осознанно. Раньше значением по умолчанию было True: если
    .env не читался (сломался mount, файл переименовали) или строку просто удалили,
    рубильник тихо переходил в «ВКЛ» и в казино летели живые сигналы — то есть
    авария приводила к отправке. Для рубильника это неверная сторона отказа:
    молчание чинится одной строкой в .env, а разосланные игрокам бонусы — нет.
    """
    global _enabled_state
    val = False
    reason = 'строки PREDICTIONS_ENABLED нет в .env'
    try:
        with open(ENV_FILE) as fh:
            for line in fh:
                if line.startswith("PREDICTIONS_ENABLED="):
                    raw = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                    val = raw.lower() in ("1", "true", "yes", "on")
                    reason = f'PREDICTIONS_ENABLED={raw!r}'
    except Exception as e:
        val = False
        reason = f'{ENV_FILE} не прочитан ({e})'
    if val != _enabled_state:
        print(f"[rt] отправка предсказаний: {'ВКЛ' if val else f'ВЫКЛ — {reason}'}", flush=True)
        _enabled_state = val
    return val


def ch():
    global client
    if client is None:
        client = clickhouse_connect.get_client(host=CH_HOST, port=CH_PORT, username=CH_USER,
                                               password=CH_PASSWORD, database=CH_DB)
    return client


def q(sql):
    return ch().query(sql).result_rows


def refresh_actions(force=False):
    """Кэш батч-прогнозов; обновляем раз в 60с."""
    global _actions, _actions_at
    if not force and time.monotonic() - _actions_at < 60:
        return
    rows = q("SELECT casino_player_id, pred_ltv_d90, p_churn, dep_count FROM player_actions "
             "WHERE pred_ltv_d90 > 0 OR p_churn IS NOT NULL")
    _actions = {int(r[0]): (float(r[1] or 0), r[2], int(r[3] or 0)) for r in rows}
    _actions_at = time.monotonic()
    print(f"[rt] кэш прогнозов обновлён: {len(_actions)} игроков", flush=True)


def on_cooldown(player, rule):
    return _cooldown.get((player, rule), 0) > time.monotonic()


def arm_cooldown(player, rule):
    _cooldown[(player, rule)] = time.monotonic() + COOLDOWN_MIN * 60


def load_cooldowns():
    """После рестарта не дублируем недавние триггеры."""
    try:
        for pid, rule in q(f"SELECT casino_player_id, rule FROM trigger_log "
                           f"WHERE fired_at > now() - INTERVAL {COOLDOWN_MIN} MINUTE"):
            arm_cooldown(int(pid), rule)
    except Exception:
        pass


def send_triggers(triggers):
    """POST на колбэк казино + лог в ClickHouse."""
    if not triggers:
        return
    payload = {
        "model_version": "rt-trigger",
        "scored_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "signals": [t["signal"] for t in triggers],
    }
    ok = False
    if CALLBACK_URL and CALLBACK_TOKEN:
        try:
            r = requests.post(CALLBACK_URL, json=payload, timeout=10,
                              headers={"Authorization": f"Bearer {CALLBACK_TOKEN}"})
            ok = r.status_code < 300
        except Exception as e:
            print(f"[rt] callback error: {e}", flush=True)
    rows = [(t["ts"], t["player"], t["rule"], json.dumps(t["signal"], ensure_ascii=False), 1 if ok else 0)
            for t in triggers]
    ch().insert("trigger_log", rows,
                column_names=["fired_at", "casino_player_id", "rule", "details", "delivered"])
    for t in triggers:
        print(f"[rt] 🔥 {t['rule']} → игрок {t['player']} · {t['why']} · delivered={ok}", flush=True)


def main():
    print(f"[rt] старт: poll={POLL_MS}ms loss_th={LOSS_TH} ltv_min={LTV_MIN} "
          f"dep_big={DEP_BIG} cooldown={COOLDOWN_MIN}m", flush=True)
    ch().command("""
        CREATE TABLE IF NOT EXISTS retention.trigger_log (
            fired_at DateTime64(3), casino_player_id UInt32,
            rule LowCardinality(String), details String, delivered UInt8
        ) ENGINE = MergeTree ORDER BY (casino_player_id, fired_at)""")
    refresh_actions(force=True)
    load_cooldowns()

    # watermark по ingested_at (момент вставки у нас): монотонный, без гонок
    # с отставанием часов источника и буфером Kafka
    wm = q("SELECT toString(greatest(max(ingested_at), now64(3) - INTERVAL 10 SECOND)) FROM live_events")[0][0]
    while True:
        t0 = time.monotonic()
        try:
            if not predictions_enabled():
                # двигаем watermark, чтобы при включении не выстрелить по старым событиям
                wm = q("SELECT toString(greatest(max(ingested_at), now64(3) - INTERVAL 10 SECOND)) FROM live_events")[0][0]
                time.sleep(max(0.0, POLL_MS / 1000.0 - (time.monotonic() - t0)))
                continue
            refresh_actions()
            events = q(f"""SELECT casino_player_id, event_type, amount, status, toString(max(ingested_at))
                           FROM live_events WHERE ingested_at > toDateTime64('{wm}', 3)
                           GROUP BY casino_player_id, event_type, amount, status""")
            if events:
                wm = max(e[4] for e in events)
                now_iso = datetime.now(timezone.utc)
                triggers = []

                # --- правило: крупный успешный депозит -----------------------
                for pid, etype, amount, status, _ in events:
                    pid = int(pid)
                    if etype == 'deposit' and status == 'completed' and float(amount) >= DEP_BIG \
                       and not on_cooldown(pid, 'big_deposit'):
                        arm_cooldown(pid, 'big_deposit')
                        ltv, pch, dep = _actions.get(pid, (0, None, 0))
                        triggers.append({"player": pid, "rule": "big_deposit", "ts": now_iso,
                            "why": f"депозит {amount}₺",
                            "signal": {"casino_player_id": pid, "trigger": "big_deposit",
                                       "recommended_action": "NUDGE", "recommended_bonus": "reload_cashback",
                                       "pred_ltv_d90": ltv, "context": {"deposit": float(amount)},
                                       "priority": 9000}})

                # --- правило: ценный игрок в минусе сейчас --------------------
                touched = {int(e[0]) for e in events if e[1] in ('bet', 'win')}
                candidates = [p for p in touched
                              if _actions.get(p, (0,))[0] >= LTV_MIN and not on_cooldown(p, 'losing_valuable')]
                if candidates:
                    idl = ','.join(map(str, candidates))
                    for pid, net in q(f"""SELECT casino_player_id,
                                            sum(win_amount) - sum(bet_amount) AS net
                                          FROM live_events
                                          WHERE casino_player_id IN ({idl})
                                            AND ts > now64(3) - INTERVAL 10 MINUTE
                                            AND event_type IN ('bet','win')
                                          GROUP BY casino_player_id
                                          HAVING net <= -{LOSS_TH}"""):
                        pid = int(pid)
                        arm_cooldown(pid, 'losing_valuable')
                        ltv, pch, dep = _actions.get(pid, (0, None, 0))
                        triggers.append({"player": pid, "rule": "losing_valuable", "ts": now_iso,
                            "why": f"net {round(float(net))}₺ за 10 мин при LTV {round(ltv)}",
                            "signal": {"casino_player_id": pid, "trigger": "losing_valuable",
                                       "recommended_action": "SAVE", "recommended_bonus": "reload_cashback",
                                       "pred_ltv_d90": ltv,
                                       "p_churn_30d": None if pch is None else round(float(pch), 4),
                                       "context": {"net_10m": round(float(net), 2)},
                                       "priority": 9999}})

                send_triggers(triggers)
        except Exception as e:   # noqa: BLE001 — сервис не должен умирать
            global client
            client = None
            print(f"[rt] tick error: {e}", flush=True)
        time.sleep(max(0.0, POLL_MS / 1000.0 - (time.monotonic() - t0)))


if __name__ == "__main__":
    main()
