#!/usr/bin/env python3
"""Выгрузка агрегатов Microsoft Clarity (Data Export API).

Токен берётся из CLARITY_API_TOKEN (env или retain-lab/.env).

ЛИМИТЫ API (жёсткие, обойти нельзя):
  - 10 запросов на проект в СУТКИ;
  - только последние 1-3 дня, истории нет;
  - максимум 3 измерения на запрос;
  - 1000 строк в ответе без пагинации.

Поэтому каждый сырой ответ кладётся в data/clarity/raw/ и повторно НЕ запрашивается:
разбирать и переразбирать его можно сколько угодно, не тратя суточную квоту.

    python3 tools/clarity_export.py pages          # трение по страницам
    python3 tools/clarity_export.py --list         # какие пресеты есть
    python3 tools/clarity_export.py --show pages   # разобрать уже скачанное, без запроса
"""
import argparse
import base64
import collections
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://www.clarity.ms/export-data/api/v1/project-live-insights"
ROOT = pathlib.Path(__file__).resolve().parent.parent
CLARITY_DIR = ROOT / "data" / "clarity"
DAILY_QUOTA = 10

PRESETS = {
    "totals": [],
    "pages": ["URL"],
    "acquisition": ["Source", "Medium", "Channel"],
    "tech": ["Device", "OS", "Browser"],
    "geo": ["Country/Region"],
    "campaign": ["Campaign", "Source"],
}


def load_token():
    if os.environ.get("CLARITY_API_TOKEN"):
        return os.environ["CLARITY_API_TOKEN"]
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("CLARITY_API_TOKEN=") and not line.startswith("#"):
                value = line.split("=", 1)[1].strip().strip("'\"")
                if value:
                    return value
    sys.exit("Нет CLARITY_API_TOKEN — впишите токен в retain-lab/.env")


def project_id(token):
    """sub из JWT = id проекта Clarity. Кэш и счётчик квоты разводим по проектам:
    у каждого проекта свои 10 запросов в сутки, и мешать их данные нельзя."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return str(json.loads(base64.urlsafe_b64decode(payload))["sub"])
    except Exception:
        return "unknown"


def raw_dir(pid):
    return CLARITY_DIR / "raw" / pid


def log_path(pid):
    return CLARITY_DIR / f"requests_{pid}.json"


def quota_used_today(pid):
    LOG = log_path(pid)
    if not LOG.exists():
        return 0, []
    log = json.loads(LOG.read_text())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    todays = [r for r in log if r["at"].startswith(today)]
    return len(todays), log


def record_request(pid, preset, days):
    LOG = log_path(pid)
    _, log = quota_used_today(pid)
    log.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "preset": preset, "days": days})
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(log, indent=1))


def http_get(url, token):
    """curl первым: системный python3.9 идёт с LibreSSL 2.8.3 и рвёт TLS с рядом хостов."""
    if shutil.which("curl"):
        config = "\n".join([
            f'url = "{url}"',
            f'header = "Authorization: Bearer {token}"',
            'header = "Content-Type: application/json"',
            'max-time = 60', 'silent', 'show-error',
            'write-out = "\\n%{http_code}"',
        ])
        proc = subprocess.run(["curl", "--config", "-"], input=config,
                              capture_output=True, text=True)
        if proc.returncode == 0:
            body, _, status = proc.stdout.rpartition("\n")
            return body, int(status or 0)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode(), resp.status
    except urllib.error.HTTPError as e:
        return e.read().decode(errors="replace"), e.code
    except urllib.error.URLError as e:
        sys.exit(f"Сеть недоступна: {e.reason}")


def cache_path(pid, preset, days):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return raw_dir(pid) / f"{stamp}_{preset}_{days}d.json"


def pull(preset, days, token, force=False):
    pid = project_id(token)
    path = cache_path(pid, preset, days)
    if path.exists() and not force:
        print(f"уже скачано сегодня, квоту не тратим: {path.name}", file=sys.stderr)
        return json.loads(path.read_text())

    used, _ = quota_used_today(pid)
    if used >= DAILY_QUOTA:
        sys.exit(f"Суточная квота проекта {pid} исчерпана ({used}/{DAILY_QUOTA}). Продолжить можно завтра (UTC).")

    params = {"numOfDays": days}
    for i, dim in enumerate(PRESETS[preset], start=1):
        params[f"dimension{i}"] = dim
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"

    body, status = http_get(url, token)
    record_request(pid, preset, days)
    used += 1
    if status != 200:
        hint = {401: "  → токен недействителен или истёк",
                403: "  → у токена нет прав на эту операцию",
                429: "  → суточный лимит запросов исчерпан на стороне Clarity"}.get(status, "")
        sys.exit(f"HTTP {status}: {body.strip()[:400]}{hint}\nПотрачено запросов сегодня: {used}/{DAILY_QUOTA}")
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        sys.exit(f"Ответ не JSON: {body.strip()[:300]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(f"сохранено {pid}/{path.name}; запросов сегодня {used}/{DAILY_QUOTA}", file=sys.stderr)
    return data


def as_rows(data):
    """Ответ: [{metricName, information:[{...значения..., <измерение>: ...}]}]."""
    out = collections.OrderedDict()
    for block in data if isinstance(data, list) else []:
        out[block.get("metricName")] = block.get("information") or []
    return out


def show(data, top):
    rows = as_rows(data)
    if not rows:
        print("пусто — Clarity не вернул ни одной метрики (обычно значит: за период нет трафика)")
        return
    for metric, info in rows.items():
        print(f"\n=== {metric} ({len(info)} строк) ===")
        for item in info[:top]:
            print("   " + json.dumps(item, ensure_ascii=False)[:300])
        if len(info) > top:
            print(f"   ... ещё {len(info) - top}")


def main():
    p = argparse.ArgumentParser(description="Агрегаты Microsoft Clarity")
    p.add_argument("preset", nargs="?", choices=sorted(PRESETS))
    p.add_argument("--days", type=int, default=3, choices=[1, 2, 3])
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--show", metavar="PRESET", help="разобрать уже скачанное, без запроса")
    p.add_argument("--list", action="store_true")
    p.add_argument("--force", action="store_true", help="перезапросить, потратив квоту")
    args = p.parse_args()

    if args.list:
        pid = project_id(load_token())
        used, _ = quota_used_today(pid)
        print(f"проект {pid}, запросов сегодня: {used}/{DAILY_QUOTA}\nпресеты:")
        for k, v in sorted(PRESETS.items()):
            print(f"  {k:12} {', '.join(v) or '(без разбивки)'}")
        print("\nскачано:")
        rd = raw_dir(pid)
        for f in sorted(rd.glob("*.json")) if rd.exists() else []:
            print(f"  {f.name}")
        return

    if args.show:
        pid = project_id(load_token())
        path = cache_path(pid, args.show, args.days)
        if not path.exists():
            rd = raw_dir(pid)
            candidates = sorted(rd.glob(f"*_{args.show}_*.json")) if rd.exists() else []
            if not candidates:
                sys.exit(f"нет скачанных данных для «{args.show}»")
            path = candidates[-1]
        print(f"# {path.name}")
        show(json.loads(path.read_text()), args.top)
        return

    if not args.preset:
        p.error("укажите пресет, или --list, или --show")
    show(pull(args.preset, args.days, load_token(), args.force), args.top)


if __name__ == "__main__":
    main()
