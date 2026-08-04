#!/bin/zsh
# Управление локальным аналитическим стеком (ClickHouse + Metabase)
# Использование: ./stack.sh {start|stop|status|ch|metabase-logs}
set -e
ROOT="/Users/admin/Developer/Dima_ret"
CH_BIN="/opt/homebrew/bin/clickhouse"
CH_CFG="$ROOT/ch/config.xml"
export DOCKER_HOST="unix://$HOME/.colima/docker.sock"

case "$1" in
  start)
    if ! lsof -nP -iTCP:9000 -sTCP:LISTEN >/dev/null 2>&1; then
      echo "Starting ClickHouse..."
      nohup "$CH_BIN" server --config-file="$CH_CFG" > "$ROOT/ch/logs/stdout.log" 2>&1 &
      disown; sleep 6
    else echo "ClickHouse already running"; fi
    colima status >/dev/null 2>&1 || colima start
    docker start metabase-retention >/dev/null 2>&1 && echo "Metabase started" || echo "Metabase container missing (recreate)"
    echo "ClickHouse: 127.0.0.1:9000 (HTTP 8123) | Metabase: http://localhost:3000"
    ;;
  stop)
    echo "Stopping Metabase..."; docker stop metabase-retention >/dev/null 2>&1 || true
    echo "Stopping ClickHouse..."; pkill -f "clickhouse server --config-file=$CH_CFG" || true
    echo "Stopped (data preserved in $ROOT/ch/data)"
    ;;
  status)
    echo "ClickHouse:"; lsof -nP -iTCP:9000 -sTCP:LISTEN >/dev/null 2>&1 && echo "  UP 127.0.0.1:9000" || echo "  DOWN"
    echo "Metabase:"; docker ps --filter name=metabase-retention --format "  {{.Status}} {{.Ports}}" 2>/dev/null || echo "  DOWN"
    ;;
  ch)   shift; "$CH_BIN" client --host 127.0.0.1 "$@" ;;
  metabase-logs) docker logs -f metabase-retention ;;
  *) echo "Usage: ./stack.sh {start|stop|status|ch|metabase-logs}"; exit 1 ;;
esac
