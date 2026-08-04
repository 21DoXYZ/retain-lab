#!/usr/bin/env bash
# ============================================================================
# Монитор интеграции с казино + уведомления в Telegram.
#
# Проверяет ТРИ независимые вещи (сайт может жить, а поток — стоять):
#   1) SITE    — публичный сайт казино (billionbahis279.com)
#   2) STREAM  — идут ли к нам события (свежесть live_events по ingested_at)
#   3) CALLBACK— их приёмник сигналов модели (api/retention-board/health)
#
# Шлёт в Telegram только при СМЕНЕ состояния (up→down, down→up), не спамит.
# Состояние — в /var/tmp/retention_monitor.state
#
# Настройка (в .env):
#   TELEGRAM_BOT_TOKEN=123456:AA...      # у @BotFather
#   TELEGRAM_CHAT_ID=-1001234567890      # id чата/канала (бот должен быть в нём)
#   MONITOR_STREAM_MAX_SILENCE=900       # сек тишины в потоке до тревоги (по умолч. 15 мин)
#
# Запуск: ./monitor.sh          (разово)
# Cron:   */2 * * * * /home/retention-board/monitor.sh >> /home/retention-board/monitor.log 2>&1
# ============================================================================
set -uo pipefail
cd "$(dirname "$0")"

SITE_URL="${MONITOR_SITE_URL:-https://billionbahis279.com}"
CB_URL="$(sed -n 's/^CALLBACK_HEALTH_URL=//p' .env)"
CB_TOKEN="$(sed -n 's/^RETENTION_BOARD_CALLBACK_TOKEN=//p' .env)"
BOT="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' .env)"
CHAT="$(sed -n 's/^TELEGRAM_CHAT_ID=//p' .env)"
MAX_SILENCE="$(sed -n 's/^MONITOR_STREAM_MAX_SILENCE=//p' .env)"; MAX_SILENCE="${MAX_SILENCE:-900}"
CHPASS="$(sed -n 's/^CH_PASSWORD=//p' .env)"

STATE_FILE=/var/tmp/retention_monitor.state
ts() { date '+%F %T'; }

CHATS_FILE="${TG_CHATS_FILE:-secrets/tg_chats.json}"

tg() {  # $1 = текст. Шлём во ВСЕ чаты, подписавшиеся через /add у бота.
  if [ -z "$BOT" ]; then echo "[$(ts)] (telegram не настроен) $1"; return; fi
  # список получателей: подписки бота + запасной TELEGRAM_CHAT_ID из .env
  ids=$(python3 -c "
import json,sys
try: ids=[str(c['id']) for c in json.load(open('$CHATS_FILE'))]
except Exception: ids=[]
if '$CHAT' and '$CHAT' not in ids: ids.append('$CHAT')
print('\n'.join(i for i in ids if i))" 2>/dev/null)
  if [ -z "$ids" ]; then echo "[$(ts)] (нет подписчиков — напишите боту /add) $1"; return; fi
  while IFS= read -r cid; do
    curl -s -o /dev/null --max-time 15 -X POST \
      "https://api.telegram.org/bot${BOT}/sendMessage" \
      --data-urlencode "chat_id=${cid}" \
      --data-urlencode "text=$1" \
      --data-urlencode "parse_mode=HTML" || echo "[$(ts)] telegram: не отправлено в $cid"
  done <<< "$ids"
}

# ---------------------------------------------------------------- 1) сайт
site_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -L "$SITE_URL" 2>/dev/null)
[ "$site_code" = "200" ] && SITE=up || SITE=down

# ---------------------------------------------------------------- 2) поток событий
silence=$(docker exec retention-board-clickhouse-1 clickhouse client --password "$CHPASS" \
  -q "SELECT toInt64(ifNull(dateDiff('second', max(ingested_at), now64(3)), 999999)) FROM retention.live_events" 2>/dev/null)
silence="${silence:-999999}"
[ "$silence" -le "$MAX_SILENCE" ] && STREAM=up || STREAM=down

# ---------------------------------------------------------------- 3) их колбэк
if [ -n "$CB_URL" ]; then
  cb_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "Authorization: Bearer ${CB_TOKEN}" "$CB_URL" 2>/dev/null)
  [ "$cb_code" = "200" ] && CALLBACK=up || CALLBACK=down
else
  cb_code="n/a"; CALLBACK=up
fi

# ---------------------------------------------------------------- 4) OOM-падения запросов CH
# Симптом бага Б1 («Деньги не открываются»): при одновременных тяжёлых запросах
# OvercommitTracker убивал один с MEMORY_LIMIT_EXCEEDED -> 500 на странице.
# Митигация — спилл на диск + лимит на запрос (ch_users.d/profiles.xml). Здесь
# следим за РЕАЛЬНЫМ симптомом: сколько запросов реально упало по памяти за 10 мин.
# ВАЖНО: НЕ по метрике MemoryTracking — она в этой версии CH врёт (показывает
# больше, чем вся RAM машины), и тревога по ней была бы ложной.
oom=$(docker exec retention-board-clickhouse-1 clickhouse client --password "$CHPASS" \
  -q "SELECT count() FROM system.query_log WHERE type='ExceptionWhileProcessing'
      AND exception LIKE '%MEMORY_LIMIT%' AND event_time > now() - INTERVAL 10 MINUTE" 2>/dev/null)
oom="${oom:-0}"
if [ "$oom" -gt 0 ]; then CHMEM=oom; else CHMEM=ok; fi

NOW="SITE=$SITE STREAM=$STREAM CALLBACK=$CALLBACK CHMEM=$CHMEM"
PREV=$(cat "$STATE_FILE" 2>/dev/null || echo "")
echo "[$(ts)] $NOW (site=$site_code, тишина=${silence}с, cb=$cb_code, OOM-запросов/10мин=${oom})"

# ---------------------------------------------------------------- уведомления при смене состояния
if [ -z "$PREV" ] && [ "$SITE" = up ] && [ "$STREAM" = up ] && [ "$CALLBACK" = up ] && [ "$CHMEM" = ok ]; then
  echo "$NOW" > "$STATE_FILE"          # первый запуск, всё в норме — молча запоминаем
elif [ "$NOW" != "$PREV" ]; then
  mins=$((silence / 60))
  if [ "$SITE" = down ] || [ "$STREAM" = down ] || [ "$CALLBACK" = down ]; then
    msg="🔴 <b>Retention Board — проблема</b>%0A"
  else
    msg="✅ <b>Retention Board — всё восстановлено</b>%0A"
  fi
  msg="${msg}%0A<b>Сайт казино:</b> $([ "$SITE" = up ] && echo "работает ($site_code)" || echo "НЕДОСТУПЕН ($site_code)")"
  msg="${msg}%0A<b>Поток событий:</b> $([ "$STREAM" = up ] && echo "идёт (последнее ${silence}с назад)" || echo "ТИШИНА ${mins} мин")"
  msg="${msg}%0A<b>Их приёмник сигналов:</b> $([ "$CALLBACK" = up ] && echo "отвечает ($cb_code)" || echo "НЕ ОТВЕЧАЕТ ($cb_code)")"
  if [ "$STREAM" = down ]; then
    msg="${msg}%0A%0A⚠️ Пока событий нет, витрина считает игроков уходящими (lifecycle от today()). Проверьте, не шлём ли казино ложные SAVE-сигналы."
  fi
  tg "$(printf '%b' "${msg//%0A/\\n}")"
  echo "$NOW" > "$STATE_FILE"
fi
