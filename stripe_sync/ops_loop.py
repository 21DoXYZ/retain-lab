"""Планировщик джобов SaaS-контура (Phase 6): «cron в compose» без cron-демона.

Каждую минуту проверяет расписание и запускает созревшие джобы подпроцессом
(тот же образ, те же env). Джоб не может запуститься дважды за минуту; упавший
джоб логируется и не валит цикл. Расписание (UTC):

  campaign_tick   — каждые 15 минут
  stitch          — каждый час, :05
  scoring         — ежедневно 03:10
  uplift_report   — понедельник 08:00

Каждый джоб гоняется ПО КАЖДОМУ пространству (tenant) отдельным процессом с
TENANT_ID в окружении: список берётся из secrets/tokens.json + tenants.json,
поэтому новый клиент подхватывается сам, без правки расписания.

Compose-сервис saas-ops (restart: unless-stopped) держит цикл живым.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone

JOBS = [
    ("campaign_tick", ["python", "campaign_tick.py"],
     lambda t: t.minute % 15 == 0),
    ("stitch", ["python", "stitch.py"],
     lambda t: t.minute == 5),
    ("contacts", ["python", "contacts_sync.py"],
     lambda t: t.minute == 5),
    # планы (цена из Stripe + лимит из опросника) - вход для burn_rate/UPGRADE
    ("plans", ["python", "plans_sync.py"],
     lambda t: t.minute == 5),
    ("scoring", ["python", "scoring.py"],
     lambda t: t.hour == 3 and t.minute == 10),
    ("uplift_report", ["python", "uplift_report.py"],
     lambda t: t.weekday() == 0 and t.hour == 8 and t.minute == 0),
    # ИИ-аналитик читает свежий uplift -> рекомендации владельцу
    ("ai_analyst", ["python", "ai_analyst.py"],
     lambda t: t.weekday() == 0 and t.hour == 8 and t.minute == 10),
    # разбор причин отмены (свободный текст юзеров -> категории)
    ("cancel_reasons", ["python", "cancel_reasons.py"],
     lambda t: t.minute == 20),
    # база юзеров из источника клиента (провайдер авторизации / его API)
    ("users_sync", ["python", "users_sync.py"],
     lambda t: t.minute == 35),
]


def run_job(name: str, argv: list[str], tenant: str) -> None:
    started = time.monotonic()
    env = {**os.environ, "TENANT_ID": tenant}
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=1800, env=env)
        out = (proc.stdout or "").strip().splitlines()
        tail = out[-1] if out else ""
        print(f"[ops] {name} tenant={tenant} rc={proc.returncode} "
              f"{time.monotonic() - started:.1f}s {tail}", flush=True)
        if proc.returncode != 0:
            err = (proc.stderr or "").strip().splitlines()
            print(f"[ops] {name} tenant={tenant} stderr: {err[-1] if err else '?'}",
                  flush=True)
    except subprocess.TimeoutExpired:
        print(f"[ops] {name} tenant={tenant} TIMEOUT", flush=True)
    except Exception as exc:
        print(f"[ops] {name} tenant={tenant} error: {type(exc).__name__}: {exc}",
              flush=True)


def main() -> None:
    print("[ops] scheduler up (UTC): tick */15m · stitch+contacts+plans :05 · scoring 03:10 · uplift Mon 08:00 · analyst Mon 08:10 · reasons :20",
          flush=True)
    from provision_util import load_known_tenants

    last_key, warned = "", False
    while True:
        now = datetime.now(tz=timezone.utc)
        key = now.strftime("%Y%m%d%H%M")
        if key != last_key:
            last_key = key
            due_jobs = [(n, a) for n, a, due in JOBS if due(now)]
            if due_jobs:
                tenants = load_known_tenants()
                if not tenants:
                    if not warned:
                        print("[ops] пространств нет (secrets/tokens.json пуст) - "
                              "джобы пропускаю", flush=True)
                        warned = True
                else:
                    warned = False
                    for name, argv in due_jobs:
                        for tenant in tenants:
                            run_job(name, argv, tenant)
        time.sleep(10)


if __name__ == "__main__":
    main()
