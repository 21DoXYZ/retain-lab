#!/usr/bin/env python3
"""Read-only выгрузка из hubcontent.ai (GET /api/retivo-export).

Ключ берётся из HUBCONTENT_API_KEY (env или retain-lab/.env).
Только GET, только чтение. Пишет NDJSON — по файлу на датасет.

    python3 tools/hubcontent_export.py summary
    python3 tools/hubcontent_export.py users --out data/hubcontent
    python3 tools/hubcontent_export.py --all --since 2026-07-01T00:00:00Z
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

DATASETS = [
    "summary",
    "users",
    "projects",
    "jobs",
    "credit_transactions",
    "subscriptions",
    "plan_changes",
]
DEFAULT_URL = "https://hubcontent.ai/api/retivo-export"
MAX_LIMIT = 1000
ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env_key():
    for name in ("HUBCONTENT_API_KEY", "HUBCONTENT_EXPORT_URL"):
        if os.environ.get(name):
            continue
        env_file = ROOT / ".env"
        if not env_file.exists():
            break
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}=") and not line.startswith("#"):
                value = line.split("=", 1)[1].strip().strip("'\"")
                if value:
                    os.environ[name] = value


def auth_header(key, auth_mode):
    return f"Authorization: Bearer {key}" if auth_mode == "bearer" else f"X-API-Key: {key}"


def fetch_curl(full_url, header):
    """Транспорт по умолчанию: системный python3.9 идёт с LibreSSL 2.8.3 и рвёт
    TLS-рукопожатие с этим хостом, curl на том же маке ходит нормально.
    Ключ передаём через stdin-конфиг, чтобы он не светился в списке процессов."""
    config = "\n".join([
        f'url = "{full_url}"',
        f'header = "{header}"',
        'max-time = 60',
        'silent',
        'show-error',
        'write-out = "\\n%{http_code}"',
    ])
    proc = subprocess.run(["curl", "--config", "-"], input=config,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"curl не смог сходить к API: {proc.stderr.strip()[:400]}")
    body, _, status = proc.stdout.rpartition("\n")
    return body, int(status or 0)


def fetch_urllib(full_url, header):
    name, _, value = header.partition(": ")
    req = urllib.request.Request(full_url, method="GET", headers={name: value})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode(), resp.status
    except urllib.error.HTTPError as e:
        return e.read().decode(errors="replace"), e.code
    except urllib.error.URLError as e:
        sys.exit(f"Сеть недоступна: {e.reason}")


def fetch(url, key, auth_mode, params, transport):
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    full_url = f"{url}?{query}"
    header = auth_header(key, auth_mode)
    use_curl = transport == "curl" or (transport == "auto" and shutil.which("curl"))
    body, status = (fetch_curl if use_curl else fetch_urllib)(full_url, header)
    if status != 200:
        hint = ""
        if status == 401:
            hint = "  → проверьте HUBCONTENT_API_KEY в retain-lab/.env (лишний пробел/обрезан)"
        sys.exit(f"HTTP {status} на {params.get('dataset')}: {body.strip()[:500]}{hint}")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        sys.exit(f"Ответ не JSON на {params.get('dataset')}: {body.strip()[:300]}")


def unwrap(payload, dataset):
    """Достаёт список строк и курсор, не завязываясь на точное имя обёртки."""
    if isinstance(payload, list):
        return payload, None
    cursor = None
    for key in ("cursor", "next_cursor", "nextCursor"):
        if isinstance(payload.get(key), (str, int)):
            cursor = payload[key]
            break
    if cursor is None and isinstance(payload.get("meta"), dict):
        meta = payload["meta"]
        cursor = meta.get("cursor") or meta.get("next_cursor")
    for key in ("data", "rows", "items", "results", dataset):
        value = payload.get(key)
        if isinstance(value, list):
            return value, cursor
        if isinstance(value, dict):
            return [value], cursor
    return [payload], cursor


def pull(dataset, args, key):
    url = os.environ.get("HUBCONTENT_EXPORT_URL", DEFAULT_URL)
    rows, cursor, pages = [], None, 0
    while True:
        payload = fetch(url, key, args.auth, {
            "dataset": dataset,
            "since": args.since,
            "limit": min(args.limit, MAX_LIMIT),
            "cursor": cursor,
        }, args.transport)
        page, cursor = unwrap(payload, dataset)
        rows.extend(page)
        pages += 1
        if dataset == "summary" or not cursor or not page or pages >= args.max_pages:
            if cursor and pages >= args.max_pages:
                print(f"  ! остановился на {args.max_pages} страницах, курсор ещё есть: {cursor}",
                      file=sys.stderr)
            break
    return rows


def main():
    p = argparse.ArgumentParser(description="Read-only выгрузка hubcontent.ai")
    p.add_argument("dataset", nargs="?", choices=DATASETS)
    p.add_argument("--all", action="store_true", help="выгрузить все датасеты")
    p.add_argument("--since", help="ISO-таймстамп для инкрементальной выгрузки")
    p.add_argument("--limit", type=int, default=MAX_LIMIT, help=f"размер страницы (макс {MAX_LIMIT})")
    p.add_argument("--max-pages", type=int, default=1000)
    p.add_argument("--auth", choices=["header", "bearer"], default="header")
    p.add_argument("--transport", choices=["auto", "curl", "python"], default="auto",
                   help="auto = curl, если он есть (обход старого LibreSSL в python3.9)")
    p.add_argument("--out", help="каталог для NDJSON; без него — печать в stdout")
    args = p.parse_args()

    if not args.dataset and not args.all:
        p.error("укажите датасет или --all")

    load_env_key()
    key = os.environ.get("HUBCONTENT_API_KEY")
    if not key:
        sys.exit("Нет HUBCONTENT_API_KEY — впишите ключ в retain-lab/.env")

    targets = DATASETS if args.all else [args.dataset]
    out_dir = pathlib.Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    for dataset in targets:
        rows = pull(dataset, args, key)
        if out_dir:
            path = out_dir / f"{dataset}.ndjson"
            with path.open("w") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"{dataset}: {len(rows)} → {path}")
        else:
            print(f"== {dataset} ({len(rows)}) ==")
            for row in rows[:5]:
                print(json.dumps(row, ensure_ascii=False)[:600])
            if len(rows) > 5:
                print(f"... ещё {len(rows) - 5}")


if __name__ == "__main__":
    main()
