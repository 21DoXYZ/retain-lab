#!/usr/bin/env bash
# ============================================================================
# Перенос обученных моделей (каталог models/) на сервер.
# Нужен ТОЛЬКО для скоринга НА VPS (Pattern A из MODELS.md, требует catboost на сервере).
# Чаще проще Pattern B: заскорить локально и залить таблицы предсказаний
# (remote()/restore_ml_tables.sh) — тогда модели на VPS не нужны вообще.
#
# Использование:
#   ./transfer_models.sh user@server:/path/retention-board
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

DEST="${1:?Использование: ./transfer_models.sh user@server:/path/retention-board}"
[ -d models ] || { echo "!! Нет каталога models/ — сначала обучи: ./train_all.sh"; exit 1; }

echo "==> Переношу models/ → ${DEST%/}/models/"
rsync -avz --delete models/ "${DEST%/}/models/"
echo "✓ Готово. На сервере можно скорить без переобучения:"
echo "    SCORE_ONLY=1 ./train_all.sh        # загрузит .cbm, заскорит, наполнит ML-таблицы"
