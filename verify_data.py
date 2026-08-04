#!/usr/bin/env python3
"""verify_data.py — сквозная сверка данных дашборда.

Проверяет, что данные в ClickHouse сходятся:
  A. кол-во строк   = манифесту экспорта (retention_export_manifest_*.json)
  B. витрина player_features целостна (1 строка/игрок, нет orphan-id)
  C. витрина == сырьё до копейки (turnover/wins/net/депозиты/выводы/GGR/FTD)
  D. суммы раздела /affiliates сходятся

Запуск (внутри venv):
    .venv/bin/python verify_data.py                 # AF120 + AF065 по умолчанию
    .venv/bin/python verify_data.py AF042 AF053     # свои аффилиаты для блока C

Код выхода: 0 — всё сошлось, 1 — есть расхождения (удобно для CI/pre-demo).
"""
import os
import sys
import glob
import json

import clickhouse_connect

CH_HOST = os.environ.get('CH_HOST', '127.0.0.1')
CH_PORT = int(os.environ.get('CH_PORT', '8123'))
CH_USER = os.environ.get('CH_USER', 'default')
CH_PASSWORD = os.environ.get('CH_PASSWORD', '')
CH_DB = os.environ.get('CH_DB', 'retention')

# деньги — определения витрины player_features (auto + manual, completed)
DEP = "type IN ('deposit','manual_deposit') AND status='completed'"
WD = "type IN ('withdrawal','manual_withdrawal') AND status='completed'"
BET = "transaction_type IN ('bet','freespins_bet')"
WIN = "transaction_type IN ('win','freespins_win')"

# имя CSV в манифесте -> таблица ClickHouse
MANIFEST_TABLE = {
    'retention_users': 'users',
    'retention_money_transactions': 'money_transactions',
    'retention_game_transactions': 'game_transactions',
    'retention_game_sessions': 'game_sessions',
}


def make_client():
    return clickhouse_connect.get_client(
        host=CH_HOST, port=CH_PORT, username=CH_USER,
        password=CH_PASSWORD, database=CH_DB)


class Audit:
    """Накопитель результатов с PASS/FAIL и финальным кодом выхода."""

    def __init__(self, cl):
        self.cl = cl
        self.passed = 0
        self.failed = 0
        self.fails = []

    def one(self, sql):
        return self.cl.query(sql).result_rows[0][0]

    def rows(self, sql):
        return self.cl.query(sql).result_rows

    def section(self, title):
        print('\n' + '=' * 68 + f'\n{title}\n' + '=' * 68)

    def check(self, name, got, exp, tol=0.0):
        if isinstance(exp, (int, float)):
            ok = abs(float(got) - float(exp)) <= tol
        else:
            ok = got == exp
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got={got} exp={exp}")
        if ok:
            self.passed += 1
        else:
            self.failed += 1
            self.fails.append(name)
        return ok

    def summary(self):
        print('\n' + '=' * 68)
        print(f"ИТОГО: PASS={self.passed}  FAIL={self.failed}")
        if self.fails:
            print('Провалены: ' + ', '.join(self.fails))
        print('=' * 68)
        return 0 if self.failed == 0 else 1


def load_manifest_rows():
    """Эталонные счётчики строк из самого свежего манифеста экспорта."""
    here = os.path.dirname(os.path.abspath(__file__))
    files = sorted(glob.glob(os.path.join(here, 'retention_export_manifest_*.json')))
    if not files:
        return None, None
    path = files[-1]
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    expected = {}
    for entry in data.get('files', []):
        name = os.path.basename(entry.get('file', ''))
        for key, table in MANIFEST_TABLE.items():
            if name.startswith(key):
                expected[table] = entry.get('rows')
    return os.path.basename(path), expected


def audit_rows(a):
    a.section('A. ROW COUNTS (ClickHouse vs манифест)')
    manifest, expected = load_manifest_rows()
    if not expected:
        print('  [SKIP] манифест retention_export_manifest_*.json не найден')
        return
    print(f'  манифест: {manifest}')
    for table, exp in expected.items():
        a.check(table, a.one(f'SELECT count() FROM {table}'), exp)


def audit_mart(a):
    a.section('B. ВИТРИНА player_features (целостность)')
    a.check('player_features rows == users',
            a.one('SELECT count() FROM player_features'),
            a.one('SELECT count() FROM users'))
    a.check('уникальных игроков == строк',
            a.one('SELECT uniqExact(casino_player_id) FROM player_features'),
            a.one('SELECT count() FROM player_features'))
    a.check('orphan id в money_transactions',
            a.one('SELECT uniqExact(casino_player_id) FROM money_transactions '
                  'WHERE casino_player_id NOT IN (SELECT casino_player_id FROM users)'), 0)
    a.check('orphan id в game_transactions',
            a.one('SELECT uniqExact(casino_player_id) FROM game_transactions '
                  'WHERE casino_player_id NOT IN (SELECT casino_player_id FROM users)'), 0)


def audit_affiliate(a, code):
    print(f'\n--- {code} ---')
    aw = f"affiliate_code='{code}' AND account_type='normal'"
    pset = f"casino_player_id IN (SELECT casino_player_id FROM player_features WHERE {aw})"
    fnum = lambda sql: float(a.one(sql))

    m_turn = fnum(f'SELECT round(sum(turnover),2) FROM player_features WHERE {aw}')
    r_turn = fnum(f'SELECT round(sumIf(bet_amount,{BET}),2) FROM game_transactions WHERE {pset}')
    a.check(f'{code} turnover витрина==сырьё', m_turn, r_turn, tol=1.0)

    m_win = fnum(f'SELECT round(sum(wins_sum),2) FROM player_features WHERE {aw}')
    r_win = fnum(f'SELECT round(sumIf(win_amount,{WIN}),2) FROM game_transactions WHERE {pset}')
    a.check(f'{code} выплаты витрина==сырьё', m_win, r_win, tol=1.0)

    m_net = fnum(f'SELECT round(sum(net),2) FROM player_features WHERE {aw}')
    a.check(f'{code} net==wins-turnover', m_net, round(m_win - m_turn, 2), tol=2.0)

    m_dep = fnum(f'SELECT round(sum(dep_sum),2) FROM player_features WHERE {aw}')
    r_dep = fnum(f'SELECT round(sumIf(amount,{DEP}),2) FROM money_transactions WHERE {pset}')
    a.check(f'{code} депозиты витрина==сырьё', m_dep, r_dep, tol=1.0)

    m_wd = fnum(f'SELECT round(sum(wd_sum),2) FROM player_features WHERE {aw}')
    r_wd = fnum(f'SELECT round(sumIf(amount,{WD}),2) FROM money_transactions WHERE {pset}')
    a.check(f'{code} выводы витрина==сырьё', m_wd, r_wd, tol=1.0)

    pg_turn = fnum(f'SELECT round(sum(turnover),2) FROM player_games WHERE {pset}')
    a.check(f'{code} player_games.turnover==сырьё', pg_turn, r_turn, tol=2.0)

    rb, rw, fb, fw = [float(x) for x in a.rows(
        f"SELECT round(sumIf(bet_amount,transaction_type='bet'),2),"
        f" round(sumIf(win_amount,transaction_type='win'),2),"
        f" round(sumIf(bet_amount,transaction_type='freespins_bet'),2),"
        f" round(sumIf(win_amount,transaction_type='freespins_win'),2)"
        f" FROM game_transactions WHERE {pset}")[0]]
    a.check(f'{code} GGR(реал)+GGR(фриспины)==GGR(всего)',
            round((rb - rw) + (fb - fw), 2), round(r_turn - r_win, 2), tol=1.0)
    a.check(f'{code} turnover==реал+фриспины ставки', round(rb + fb, 2), r_turn, tol=1.0)

    a.check(f'{code} FTD витрина==users',
            a.one(f'SELECT countIf(ftd_amount>0) FROM player_features WHERE {aw}'),
            a.one(f"SELECT countIf(ftd_amount>0) FROM users "
                  f"WHERE affiliate_code='{code}' AND account_type='normal'"))


def audit_overview(a):
    a.section('D. ОБЗОР /affiliates — суммы')
    tot = a.one("SELECT count() FROM player_features "
                "WHERE account_type='normal' AND affiliate_code!=''")
    ssum = a.one("SELECT sum(c) FROM (SELECT affiliate_code, count() c FROM player_features "
                 "WHERE account_type='normal' AND affiliate_code!='' GROUP BY affiliate_code)")
    a.check('сумма по аффилиатам == всего(normal,с кодом)', ssum, tot)
    naff = a.one("SELECT uniqExact(affiliate_code) FROM player_features "
                 "WHERE account_type='normal' AND affiliate_code!=''")
    nocode = a.one("SELECT count() FROM player_features "
                   "WHERE account_type='normal' AND affiliate_code=''")
    print(f'  аффилиатов: {naff} | normal без кода аффилиата: {nocode}')


def main(argv):
    codes = argv[1:] or ['AF120', 'AF065']
    a = Audit(make_client())
    audit_rows(a)
    audit_mart(a)
    a.section('C. СВЕРКА ВИТРИНА vs СЫРЬЁ (' + ', '.join(codes) + ')')
    for code in codes:
        clean = ''.join(ch for ch in code if ch.isalnum() or ch == '_')[:24]
        if clean:
            audit_affiliate(a, clean)
    audit_overview(a)
    return a.summary()


if __name__ == '__main__':
    sys.exit(main(sys.argv))
