"""Планировщик джобов SaaS-контура (Phase 6): «cron в compose» без cron-демона.

Каждую минуту проверяет расписание и запускает созревшие джобы подпроцессом
(тот же образ, те же env). Джоб не может запуститься дважды за минуту; упавший
джоб логируется и не валит цикл. Расписание (UTC):

  campaign_tick   — каждые 15 минут
  stitch          — каждый час, :05
  scoring         — ежедневно 03:10
  uplift_report   — понедельник 08:00

Compose-сервис saas-ops (restart: unless-stopped) держит цикл живым.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone

JOBS = [
    ("campaign_tick", ["python", "campaign_tick.py"],
     lambda t: t.minute % 15 == 0),
    ("stitch", ["python", "stitch.py"],
     lambda t: t.minute == 5),
    ("scoring", ["python", "scoring.py"],
     lambda t: t.hour == 3 and t.minute == 10),
    ("uplift_report", ["python", "uplift_report.py"],
     lambda t: t.weekday() == 0 and t.hour == 8 and t.minute == 0),
]


def run_job(name: str, argv: list[str]) -> None:
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
        out = (proc.stdout or "").strip().splitlines()
        tail = out[-1] if out else ""
        print(f"[ops] {name} rc={proc.returncode} {time.monotonic() - started:.1f}s {tail}",
              flush=True)
        if proc.returncode != 0:
            err = (proc.stderr or "").strip().splitlines()
            print(f"[ops] {name} stderr: {err[-1] if err else '?'}", flush=True)
    except subprocess.TimeoutExpired:
        print(f"[ops] {name} TIMEOUT", flush=True)
    except Exception as exc:
        print(f"[ops] {name} error: {type(exc).__name__}: {exc}", flush=True)


def main() -> None:
    print("[ops] scheduler up (UTC): tick */15m · stitch :05 · scoring 03:10 · uplift Mon 08:00",
          flush=True)
    last_key = ""
    while True:
        now = datetime.now(tz=timezone.utc)
        key = now.strftime("%Y%m%d%H%M")
        if key != last_key:
            last_key = key
            for name, argv, due in JOBS:
                if due(now):
                    run_job(name, argv)
        time.sleep(10)


if __name__ == "__main__":
    main()
