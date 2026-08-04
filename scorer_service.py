#!/usr/bin/env python3
"""Warm-сервис скоринга: Python и тяжёлые библиотеки (catboost/pandas) загружены
один раз, по запросу выполняет ТЕ ЖЕ САМЫЕ скрипты моделей (*_model.py) без правок.

  POST /score   — прогнать все 6 моделей (SCORE_ONLY), вернуть тайминги
  GET  /health  — жив ли сервис

Почему быстро: первый прогон холодный (импорт catboost и т.п. внутри скриптов),
дальше импорты сидят в sys.modules процесса и каждый прогон = только
CH-выгрузка + predict + insert. Скрипты перечитывают .cbm с диска при каждом
запуске — после переобучения новые модели подхватываются без рестарта сервиса.
"""
import os
import runpy
import threading
import time

from flask import Flask, jsonify

os.environ.setdefault("SCORE_ONLY", "1")   # только скоринг, без обучения

MODELS = ["ltv_model", "ltv_quantiles", "repeat_model",
          "churn_model", "deposit_ladder_model", "bonus_model",
          # VIP-скоры (страница «VIP-риск», секция карточки, выгрузка КЦ). Без них
          # /api/v1/vip-risk падает 500: нет таблиц player_vip_churn_ml /
          # player_non_promising_vip_ml / player_early_vip_ml.
          "vip_churn_model", "non_promising_vip_model", "early_vip_model"]

app = Flask(__name__)
_lock = threading.Lock()          # не даём скорить параллельно
_last = {"finished_at": None, "took_s": None, "timings": {}, "error": None}


@app.get("/health")
def health():
    return jsonify(status="ok", last=_last), 200


@app.post("/score")
def score():
    if not _lock.acquire(blocking=False):
        return jsonify(error="scoring already in progress"), 409
    try:
        t0 = time.monotonic()
        timings = {}
        for m in MODELS:
            t = time.monotonic()
            try:
                runpy.run_path(f"{m}.py", run_name="__main__")
            except SystemExit as e:          # скрипт мог завершиться sys.exit(0)
                if e.code not in (0, None):
                    raise RuntimeError(f"{m}: exit code {e.code}")
            timings[m] = round(time.monotonic() - t, 2)
            print(f"[scorer] {m}: {timings[m]}s", flush=True)
        took = round(time.monotonic() - t0, 2)
        _last.update(finished_at=time.strftime("%F %T"), took_s=took,
                     timings=timings, error=None)
        return jsonify(status="ok", took_s=took, timings=timings), 200
    except Exception as e:                   # noqa: BLE001 — отдать ошибку наружу
        _last.update(error=str(e))
        print(f"[scorer] ERROR: {e}", flush=True)
        return jsonify(error=str(e)), 500
    finally:
        _lock.release()


if __name__ == "__main__":
    # однопоточный dev-сервер осознанно: скоринг всё равно строго последовательный
    app.run(host="0.0.0.0", port=8099)
