#!/usr/bin/env python3
"""Сверка: игроки Tegsoft (звонилка) ↔ наш ClickHouse. Запускать НА ПРОДЕ.

Тянет номера, по которым Tegsoft звонил недавно (страница «Голосовые записи» /
CDR-эндпоинт), и матчит с retention.users по телефону — показывает casino_player_id
и username, считает процент совпадения. На проде данные свежие → процент честный.

ENV: TEGSOFT_BASE_URL, TEGSOFT_TOKEN, CH_HOST/CH_PORT/CH_USER/CH_PASSWORD/CH_DB.
Использование: python tools/tegsoft_match_check.py [--from YYYY-MM-DD] [--limit N]
"""
import os, sys, json, argparse
import urllib.request
import clickhouse_connect

def tg_recent_numbers(base, token, days_from):
    """Номера из активных каналов + (если доступно) CDR. Возвращает set строк."""
    nums = set()
    def _get(path):
        req = urllib.request.Request(base.rstrip('/') + path,
                                     headers={'Authorization': f'Bearer {token}'})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    # активные звонки прямо сейчас
    try:
        d = _get('/Tobe/view/RealTimeEndPointData')
        for ch in d.get('activeVoiceChannels', []):
            for k in ('callerIdNumber', 'phone', 'DST', 'connectedLineNum'):
                v = str(ch.get(k, '')).strip()
                if v.isdigit() and len(v) >= 10:
                    nums.add(v)
    except Exception as e:
        print('  active channels err:', e)
    # TODO(prod): добрать CDR-выборку за период (Reports?fileName=cc_cdr) — на проде
    # у разраба есть точные параметры отчёта; сюда добавить парсинг getColumnData.
    return nums

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='dfrom', default='')
    ap.add_argument('--limit', type=int, default=200)
    a = ap.parse_args()
    base = os.environ['TEGSOFT_BASE_URL']; token = os.environ['TEGSOFT_TOKEN']
    ch = clickhouse_connect.get_client(
        host=os.environ.get('CH_HOST','127.0.0.1'), port=int(os.environ.get('CH_PORT','8123')),
        username=os.environ.get('CH_USER','default'), password=os.environ.get('CH_PASSWORD',''),
        database=os.environ.get('CH_DB','retention'))
    nums = list(tg_recent_numbers(base, token, a.dfrom))[:a.limit]
    if not nums:
        print('Tegsoft не отдал номеров (нет активных звонков / добери CDR).'); return
    found = 0
    print(f"{'номер Tegsoft':<14} {'у нас':<6} {'casino_player_id':<18} username")
    for p in nums:
        tail = p[-10:]
        r = ch.query(f"SELECT casino_player_id, username FROM users WHERE phone LIKE '%{tail}%' LIMIT 1").result_rows
        if r:
            found += 1
            print(f"{p:<14} {'ЕСТЬ':<6} {str(r[0][0]):<18} {r[0][1]}")
        else:
            print(f"{p:<14} {'—':<6}")
    print(f"\nСОВПАЛО: {found}/{len(nums)} ({found*100//len(nums)}%)")

if __name__ == '__main__':
    main()
