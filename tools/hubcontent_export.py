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
import time
import urllib.error
import urllib.parse
import urllib.request

# Запасной список на случай, если summary недоступен. Боевой перечень берётся из
# summary.datasets — эндпоинт пополняют, и захардкоженный список молча отстаёт.
FALLBACK_DATASETS = [
    "users",
    "projects",
    "jobs",
    "credit_transactions",
    "subscriptions",
    "plan_changes",
    "feedback",
    "support_conversations",
    "support_messages",
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


class TransportError(Exception):
    """Соединение не состоялось (TLS/сеть) — ответа от API вообще не было."""


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
        raise TransportError(f"curl: {proc.stderr.strip()[:300]}")
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
        raise TransportError(f"python: {e.reason}")


def fetch(url, key, auth_mode, params, transport, attempts=6):
    """Хост периодически отвечает на рукопожатие TLS-алертом (curl 35), поэтому
    повторяем и чередуем транспорты — то, что упало на curl, обычно проходит
    следующей попыткой."""
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    full_url = f"{url}?{query}"
    header = auth_header(key, auth_mode)
    if transport == "curl":
        chain = [fetch_curl]
    elif transport == "python":
        chain = [fetch_urllib]
    elif shutil.which("curl"):
        chain = [fetch_curl, fetch_urllib]
    else:
        chain = [fetch_urllib]

    last = None
    for attempt in range(attempts):
        try:
            body, status = chain[attempt % len(chain)](full_url, header)
            break
        except TransportError as e:
            last = e
            time.sleep(min(2 ** attempt, 8) * 0.25)
    else:
        sys.exit(f"Соединение с API не поднялось за {attempts} попыток: {last}")
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
    """Достаёт список строк и курсор.

    Фактическая обёртка API: {"ok": true, "data": {"dataset", "rows", "count", "cursor"}}.
    У summary внутри data лежит не список, а один объект со счётчиками."""
    if isinstance(payload, list):
        return payload, None
    if not isinstance(payload, dict):
        return [payload], None

    inner = payload.get("data")
    node = inner if isinstance(inner, dict) else payload
    if isinstance(inner, list):
        return inner, find_cursor(payload)

    cursor = find_cursor(node) or find_cursor(payload)
    for key in ("rows", "items", "results", dataset):
        value = node.get(key)
        if isinstance(value, list):
            return value, cursor
    return [node], cursor


def find_cursor(node):
    if not isinstance(node, dict):
        return None
    for key in ("cursor", "next_cursor", "nextCursor"):
        value = node.get(key)
        if isinstance(value, (str, int)) and value != "":
            return value
    meta = node.get("meta")
    if isinstance(meta, dict):
        return meta.get("cursor") or meta.get("next_cursor")
    return None


def row_key(row):
    if isinstance(row, dict) and row.get("id") is not None:
        return row["id"]
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def pull(dataset, args, key):
    """Страницы: cursor в ответе — это created_at последней строки, его надо
    отдать обратно параметром since (параметр cursor сервер игнорирует).
    Граница since включающая, поэтому строки дедуплицируем по id."""
    url = os.environ.get("HUBCONTENT_EXPORT_URL", DEFAULT_URL)
    limit = min(args.limit, MAX_LIMIT)
    rows, seen, since, pages = [], set(), args.since, 0
    while True:
        payload = fetch(url, key, args.auth, {
            "dataset": dataset,
            "since": since,
            "limit": limit,
        }, args.transport)
        page, cursor = unwrap(payload, dataset)
        pages += 1
        if dataset == "summary":
            return page

        fresh = [r for r in page if row_key(r) not in seen]
        seen.update(row_key(r) for r in fresh)
        rows.extend(fresh)

        exhausted = not fresh or not cursor or cursor == since or len(page) < limit
        if exhausted or pages >= args.max_pages:
            if not exhausted:
                print(f"  ! {dataset}: остановился на {args.max_pages} стр., курсор ещё есть ({cursor})",
                      file=sys.stderr)
            break
        since = cursor
    return rows


def discover_datasets(args, key):
    """Перечень датасетов спрашиваем у самого API: список пополняется на их стороне."""
    try:
        payload = fetch(os.environ.get("HUBCONTENT_EXPORT_URL", DEFAULT_URL), key, args.auth,
                        {"dataset": "summary"}, args.transport)
        rows, _ = unwrap(payload, "summary")
        found = rows[0].get("datasets") if rows and isinstance(rows[0], dict) else None
        if isinstance(found, list) and found:
            new = [d for d in found if d not in FALLBACK_DATASETS]
            if new:
                print(f"  ! в API появились новые датасеты: {', '.join(new)}", file=sys.stderr)
            return found
    except SystemExit:
        pass
    return FALLBACK_DATASETS


def main():
    p = argparse.ArgumentParser(description="Read-only выгрузка hubcontent.ai")
    p.add_argument("dataset", nargs="?")
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

    targets = discover_datasets(args, key) if args.all else [args.dataset]
    if args.all and "summary" not in targets:
        targets = ["summary"] + targets
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
