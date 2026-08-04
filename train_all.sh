#!/usr/bin/env bash
# ============================================================================
# Обучение всех моделей и наполнение ML-таблиц в ClickHouse (база retention).
# Запускать ПОСЛЕ schema.sql + данные + player_features.sql + marts.sql.
#
#   pip install -r requirements-ml.txt
#   ./train_all.sh
#
# Каждый скрипт делает DROP+CREATE+INSERT своей ML-таблицы — повторный запуск
# безопасен (переобучает на свежих данных). Конфиг ClickHouse — через env:
#   CH_HOST (def 127.0.0.1) CH_PORT (8123) CH_USER (default) CH_PASSWORD CH_DB (retention)
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || PY="python3"

echo "==> Python: $PY"
for m in ltv_model ltv_quantiles repeat_model churn_model deposit_ladder_model bonus_model \
         vip_churn_model non_promising_vip_model early_vip_model; do
  echo ""
  echo "════════════════════════════════════════════════════════"
  echo "==> $m.py"
  echo "════════════════════════════════════════════════════════"
  "$PY" "$m.py"
done

echo ""
echo "✓ Все модели обучены. ML-таблицы наполнены:"
echo "  player_ltv_ml · player_ltv_quantiles · player_repeat_ml · player_churn_ml ·"
echo "  player_next_deposit_ml · player_bonus_ml · bonus_uplift · bonus_effectiveness_t"
