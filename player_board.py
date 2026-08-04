#!/usr/bin/env python3
"""Retention Board — единый дашборд (обзор + игроки + аналитика), live из ClickHouse.
   Дизайн: Sellrise (dark sidebar / blue accent). Run inside .venv → http://127.0.0.1:8050"""
import os
import hmac
import json
import time
import ipaddress
import secrets as _secrets
import threading
import statistics
import clickhouse_connect
from flask import Flask, request, abort, Response
from markupsafe import escape

app = Flask(__name__)
_local = threading.local()

# ── конфиг через env (дефолты = локальный запуск) ──
CH_HOST = os.environ.get('CH_HOST', '127.0.0.1')
CH_PORT = int(os.environ.get('CH_PORT', '8123'))
CH_USER = os.environ.get('CH_USER', 'default')
CH_PASSWORD = os.environ.get('CH_PASSWORD', '')
CH_DB = os.environ.get('CH_DB', 'retention')
BOARD_HOST = os.environ.get('BOARD_HOST', '127.0.0.1')
BOARD_PORT = int(os.environ.get('BOARD_PORT', '8050'))
BOARD_USER = os.environ.get('BOARD_USER', '')   # если пусто — авторизация выключена (только локально)
BOARD_PASS = os.environ.get('BOARD_PASS', '')
# fail-closed: в проде (BOARD_REQUIRE_AUTH=1) пустой BOARD_USER = ошибка, а не тихое отключение auth
REQUIRE_AUTH = os.environ.get('BOARD_REQUIRE_AUTH', '').strip().lower() in ('1', 'true', 'yes', 'on')

def _client():
    c = getattr(_local, 'ch', None)
    if c is None:
        c = clickhouse_connect.get_client(host=CH_HOST, port=CH_PORT, username=CH_USER,
                                          password=CH_PASSWORD, database=CH_DB)
        _local.ch = c
    return c

@app.before_request
def _require_auth():
    """HTTP Basic Auth. Fail-closed: если BOARD_REQUIRE_AUTH=1, а логин не задан — отказ (503),
    а не тихое отключение защиты. Локально (без REQUIRE_AUTH) при пустом BOARD_USER — auth выкл."""
    # JSON-API (/api/*) идёт МИМО basic-auth: у него своя, более строгая защита —
    # Supabase-JWT (@require_auth по ролям, fail-closed) либо shared-secret у
    # вебхука Tegsoft. Пропускать сюда нельзя технически: basic-auth и Bearer
    # используют один заголовок Authorization, и токен SPA затирал бы креды —
    # любой запрос SPA получал бы 401 basic-auth, не доходя до проверки JWT.
    if request.path.startswith('/api/'):
        return
    if not BOARD_USER:
        if REQUIRE_AUTH:
            return Response('Сервер сконфигурирован небезопасно: BOARD_USER/BOARD_PASS не заданы', 503)
        return
    a = request.authorization
    ok = a and hmac.compare_digest(a.username or '', BOARD_USER) and hmac.compare_digest(a.password or '', BOARD_PASS)
    if not ok:
        return Response('Требуется авторизация', 401, {'WWW-Authenticate': 'Basic realm="Retention Board"'})

@app.after_request
def _no_cache(resp):
    """Браузер всегда берёт свежую версию (никакого кэша) + защитные заголовки."""
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    resp.headers['X-Frame-Options'] = 'DENY'                          # анти-clickjacking
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers.setdefault('Content-Security-Policy', "frame-ancestors 'none'")
    return resp

@app.errorhandler(Exception)
def _on_error(e):
    """Любой необработанный сбой (ClickHouse недоступен, таймаут, деление и т.п.) →
    аккуратная страница + лог, а не голый стектрейс. HTTP-ошибки (401/404/503) пропускаем."""
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    import traceback
    app.logger.error('route error on %s: %s\n%s', request.path, e, traceback.format_exc())
    # мёртвый thread-local клиент CH сбрасываем — следующий запрос переподключится
    try: _local.ch = None
    except Exception: pass
    return Response('<div style="font:15px/1.5 system-ui,sans-serif;padding:48px;max-width:640px;margin:auto;color:#334155">'
                    '<h2 style="color:#dc2626">⚠️ Временная ошибка</h2>'
                    '<p>Не удалось получить данные (ClickHouse недоступен или запрос упал). '
                    'Обнови страницу через пару секунд. Если повторяется — проверь, что ClickHouse жив.</p>'
                    '<p><a href="/overview" style="color:#2563eb">← на обзор</a></p></div>', 500)

def q(sql, params=None):
    r = _client().query(sql, parameters=params or {})
    return r.column_names, r.result_rows

def GN(col='game_uuid'):
    """SQL: название игры по её id. Справочник retention.game_names копится из потока
    (казино шлёт game_name с v2.1), словарь обновляется раз в 5 мин. Для игр, ещё не
    встреченных в потоке (старый дамп), показываем усечённый id — иначе была бы пустота."""
    return (f"if(dictGetOrDefault('{CH_DB}.dict_game_names','game_name',tuple({col}),'')!='',"
            f"dictGet('{CH_DB}.dict_game_names','game_name',tuple({col})),"
            f"concat('id ',substring({col},1,10)))")

def f(n):
    if n is None: return '—'
    if isinstance(n, float):
        if n != n: return '—'   # NaN
        n = round(n)
    return f'{int(n):,}'.replace(',', ' ')

def mn(n):
    if n is None: return '—'
    return f'{n/1_000_000:.1f} Mn ₺'

# ============================================================================
# ФИНАНСОВЫЕ ФОРМУЛЫ — единый источник правды (спека казино, см. FORMULAS.md).
# ============================================================================
# Вокабуляр казино (типы/статусы) — из api/casino_vocab.py, per-tenant через env
# (дефолты = BillionBahis, SQL эквивалентен прежнему). На другом казино (VivaJack)
# достаточно выставить CASINO_*-переменные, без правки кода.
from api import casino_vocab as _v
# Успешные операции: v2 = completed; legacy = approved/success тоже успех
SUCCESS = _v.in_list("status", _v.SUCCESS_STATUSES)
GSUCCESS = _v.in_list("status", _v.GAME_SUCCESS_STATUSES)   # игровые: pending/rejected НЕ в итоги
# money (спека казино): кэш-депозит/вывод — только базовые типы (manual_* = бонус, не кэш)
DEP_OK = _v.in_list("type", _v.DEPOSIT_TYPES) + " AND " + SUCCESS
WD_OK = _v.in_list("type", _v.WITHDRAWAL_TYPES) + " AND " + SUCCESS
BONUS_OK = _v.in_list("type", _v.BONUS_TYPES) + " AND " + SUCCESS
# game-типы
BET_T = _v.in_list("transaction_type", _v.BET_TYPES)
WIN_T = _v.in_list("transaction_type", _v.WIN_TYPES)

# Ставки provider/affiliate — из СПРАВОЧНИКОВ (provider_rates, affiliate_rates), не из транзакций.
def _has_table(name):
    try: return q(f"SELECT count() FROM system.tables WHERE database='{CH_DB}' AND name='{name}'")[1][0][0] > 0
    except Exception: return False

def provider_cost_total(where='1'):
    """Provider cost = Σ по студиям max(GGR_студии,0)×(engr+infra+rev)%. Студия — dict_game_names по game_uuid.
    Нужен наполненный справочник игр (на проде); без него провайдер не резолвится → 0."""
    if not _has_table('provider_rates'):
        return 0.0
    try:
        return float(q(f"""
        WITH prov AS (
          SELECT dictGetOrDefault('{CH_DB}.dict_game_names','provider',tuple(game_uuid),'') AS provider,
            sumIf(bet_amount,{BET_T})-sumIf(win_amount,{WIN_T}) AS ggr
          FROM game_transactions WHERE {GSUCCESS} AND game_uuid!='' AND {where}
          GROUP BY provider HAVING provider!='')
        SELECT ifNull(round(sum(greatest(prov.ggr,0)*(pr.engr_percent+pr.infra_percent+pr.revshare_percent)/100)),0)
        FROM prov INNER JOIN {CH_DB}.provider_rates pr ON prov.provider=pr.provider""")[1][0][0] or 0)
    except Exception:
        return 0.0

def affiliate_commission_total(where="u.account_type='normal'"):
    """Affiliate commission = Σ по аффилиатам max(net,0)×rate%. net = успешные deposits−withdrawals игроков аффилиата."""
    if not _has_table('affiliate_rates'):
        return 0.0
    try:
        return float(q(f"""
        WITH aff AS (
          SELECT u.affiliate_code AS code, sumIf(m.amount,{DEP_OK})-sumIf(abs(m.amount),{WD_OK}) AS net
          FROM money_transactions m INNER JOIN users u USING(casino_player_id)
          WHERE u.affiliate_code!='' AND {where} GROUP BY code)
        SELECT ifNull(round(sum(greatest(aff.net,0)*ar.commission_rate_percent/100)),0)
        FROM aff INNER JOIN {CH_DB}.affiliate_rates ar ON aff.code=ar.affiliate_code""")[1][0][0] or 0)
    except Exception:
        return 0.0

_AFF_RATE = None
def aff_rate(code):
    """Ставка комиссии аффилиата (%) по коду — из справочника affiliate_rates (кэш)."""
    global _AFF_RATE
    if _AFF_RATE is None:
        try:
            _AFF_RATE = ({r[0]: float(r[1] or 0) for r in
                          q("SELECT affiliate_code, commission_rate_percent FROM affiliate_rates")[1]}
                         if _has_table('affiliate_rates') else {})
        except Exception:
            _AFF_RATE = {}
    return _AFF_RATE.get(code, 0.0)

def aff_commission_row(net, code):
    """Комиссия одного аффилиата: max(net,0) × его ставка%."""
    return max(net or 0.0, 0.0) * aff_rate(code) / 100.0

def calc_ngr(ggr, bonus_cost, provider_cost=0.0, aff_commission=0.0):
    """NGR = GGR − Bonus cost − Provider cost − Affiliate commission."""
    return (ggr or 0) - (bonus_cost or 0) - (provider_cost or 0) - (aff_commission or 0)

def jsdump(obj):
    """JSON для встраивания в <script>: экранируем < и JS-разделители строк (U+2028/U+2029),
    чтобы данные из БД (affiliate_code и пр.) не могли разорвать тег и внедрить скрипт (XSS)."""
    return (json.dumps(obj, ensure_ascii=False)
            .replace('<', '\u003c').replace(chr(0x2028), '\u2028').replace(chr(0x2029), '\u2029'))

_ASOF = None
def data_asof():
    """Последний день, за который есть данные в датасете (кэшируется)."""
    global _ASOF
    if _ASOF is None:
        cand = []
        for sql in ("SELECT max(toTimezone(last_active,'Europe/Istanbul')) FROM users",
                    "SELECT max(toTimezone(created_at,'Europe/Istanbul')) FROM money_transactions",
                    "SELECT max(toTimezone(created_at,'Europe/Istanbul')) FROM game_transactions"):
            try:
                v = q(sql)[1][0][0]
                if v: cand.append(v)
            except Exception:
                pass
        _ASOF = max(cand) if cand else None
    return _ASOF

def dmy(d):
    if not d: return '—'
    try: return d.strftime('%d.%m.%Y')
    except Exception: return str(d)[:10]

def asof_pill():
    d = data_asof()
    if not d:
        return ''
    return (f"<span class=pill title='Последние данные — {dmy(d)} включительно. 5 июня и позже в выгрузе нет. "
            f"Для сверки с партнёркой ставь End Date = {dmy(d)}, иначе разойдётся на хвост.'>"
            f"📅 данные по {dmy(d)} · 5-го+ нет</span>")

def money2(n):
    """Деньги в формате панели: 88 636,51 ₺ (пробел-разряды, запятая-копейки)."""
    if n is None: return '—'
    try: s = f'{float(n):,.2f}'
    except Exception: return str(n)
    return s.replace(',', ' ').replace('.', ',') + ' ₺'

_AFF_GGR = None
def aff_ggr_split():
    """{affiliate_code: (real_bets, real_wins, fs_bets, fs_wins)} — кэш (снимок статичен, ~0.5с)."""
    global _AFF_GGR
    if _AFF_GGR is None:
        _, rws = q("""SELECT u.affiliate_code,
            sumIf(g.bet_amount, g.transaction_type='bet' AND g.status='completed'),
            sumIf(g.win_amount, g.transaction_type='win' AND g.status='completed'),
            sumIf(g.bet_amount, g.transaction_type='freespins_bet' AND g.status='completed'),
            sumIf(g.win_amount, g.transaction_type='freespins_win' AND g.status='completed')
          FROM game_transactions g
          INNER JOIN (SELECT casino_player_id, affiliate_code FROM users
                      WHERE account_type='normal' AND affiliate_code!='') u USING(casino_player_id)
          GROUP BY u.affiliate_code""")
        _AFF_GGR = {r[0]: (float(r[1] or 0), float(r[2] or 0), float(r[3] or 0), float(r[4] or 0)) for r in rws}
    return _AFF_GGR

# lifecycle → (badge bg, text color, label) — sunset/cream/ink palette only
LIFE = {
 'active':  ('#dcfce7', '#166534', 'активен'),
 'cooling': ('#dbeafe', '#1e40af', 'остывает'),
 'at_risk': ('#fef9c3', '#854d0e', 'под риском'),
 'dormant': ('#f1f5f9', '#475569', 'спящий'),
 'churned': ('#fee2e2', '#991b1b', 'отток'),
 'never':   ('#f1f5f9', '#94a3b8', 'не играл')}
def life_badge(s):
    bg, fg, t = LIFE.get(s, ('#ededed', '#8a8a8a', s or '—'))
    return f'<span class=badge style="background:{bg};color:{fg}">{t}</span>'

AT_BADGE = {'service':        ('🛡 служебный/админ', '#e0e7ff', '#4338ca'),
            'test_or_service':('🧪 тест',            '#fef9c3', '#854d0e'),
            'blocked':        ('⛔ заблокирован',     '#fee2e2', '#991b1b')}
def at_badge(at):
    if not at or at == 'normal': return ''
    t, bg, fg = AT_BADGE.get(at, (at, '#f1f5f9', '#64748b'))
    return f' <span class=badge style="background:{bg};color:{fg}">{t}</span>'

ACCT_TYPES = {'normal', 'service', 'test_or_service', 'blocked', 'all'}

CSS = """
:root{--cream:#eff6ff;--cream-l:#ffffff;--cream-d:#eff6ff;--canvas:#ffffff;--surface:#f8fafc;
 --primary:#2563eb;--primary-d:#1d4ed8;--sun5:#3b82f6;--sun8:#1d4ed8;--yellow:#60a5fa;
 --ink:#1e293b;--slate:#334155;--steel:#64748b;--stone:#94a3b8;--muted:#94a3b8;
 --hair:#f1f5f9;--hair2:#e5e7eb;--hair3:#d1d5db;--beige:#dbeafe;
 --appbg:#f3f4f6;--sb:#121626;--sb-line:#1e2336;--sb-line2:#2a3045;--sb-hover:#252b41;--sb-card:#1a1f33}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--appbg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
 -webkit-font-smoothing:antialiased;min-height:100vh;display:flex;flex-direction:column}
a{text-decoration:none;color:inherit}
.app{flex:1;display:flex;min-height:0}
.side{width:260px;flex:none;background:var(--sb);color:#9aa3b2;border-right:1px solid var(--sb-line);padding:22px 16px;display:flex;flex-direction:column}
.brand{display:flex;align-items:center;gap:12px;background:linear-gradient(180deg,var(--sb-hover),var(--sb-card));border-radius:16px;padding:11px 12px;margin-bottom:22px}
.brand .m{width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,#60a5fa,#3b82f6);display:grid;place-items:center;color:#fff;font-weight:800;font-size:16px;box-shadow:0 8px 20px rgba(59,130,246,.25)}
.brand .bt{font-weight:600;font-size:14px;color:#fff;line-height:1.2}
.brand .bs{font-size:12px;color:#7e889b;margin-top:2px}
.nav{display:flex;flex-direction:column;gap:5px}
.nav a{display:flex;align-items:center;gap:12px;color:#9aa3b2;font-size:14px;font-weight:500;padding:11px 14px;border-radius:14px;transition:all .15s}
.nav a:hover{background:var(--sb-hover);color:#e6e9f0}
.nav a.on{background:var(--primary);color:#fff;box-shadow:0 8px 20px rgba(37,99,235,.28)}
.nav a .i{width:20px;height:20px;display:grid;place-items:center}
.nav a svg{width:19px;height:19px}
.nav .grp{color:#586074;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;padding:18px 12px 6px}
.main{flex:1;padding:26px 32px 54px;min-width:0;background:var(--canvas);overflow:auto}
.h1{font-weight:800;font-size:30px;letter-spacing:-.6px;color:#1e293b}
.h1 em{font-style:normal;color:var(--primary)}
.lead{color:var(--steel);font-size:14.5px;margin-top:6px}
.topbar{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap}
.pills{display:flex;gap:8px;flex-wrap:wrap}
.pill{font-size:12.5px;color:var(--ink);background:var(--cream-d);border-radius:999px;padding:6px 12px;font-weight:500}
.pill.live{color:#fff;background:var(--primary)}
.eyebrow{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:var(--primary);margin:30px 0 13px;display:flex;align-items:center;gap:12px}
.eyebrow::after{content:"";flex:1;height:1px;background:var(--hair2)}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.scard{background:var(--canvas);border:1px solid var(--hair);border-radius:12px;padding:18px 20px;position:relative;overflow:hidden;min-height:128px}
.scard.cream{background:var(--cream);border-color:var(--beige)}
.scard.alert{background:var(--cream);border:1.5px solid var(--primary)}
.scard .l{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:var(--steel)}
.scard .v{font-weight:800;font-size:32px;line-height:1.05;margin-top:9px;letter-spacing:-1px;color:#1e293b}
.scard .s{font-size:12px;color:var(--steel);margin-top:8px;position:relative;z-index:2}
.scard .ic{position:absolute;top:15px;right:18px;font-size:16px;opacity:.45}
.scard .spark{position:absolute;left:0;right:0;bottom:0;height:30px;opacity:.9;z-index:1}
.scard.orange .v{color:var(--primary)}
.panel{background:var(--canvas);border:1px solid var(--hair);border-radius:12px;overflow:hidden}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:right;padding:11px 14px;border-bottom:1px solid var(--hair);white-space:nowrap}
th{color:var(--steel);font-size:11px;text-transform:uppercase;letter-spacing:.5px;background:var(--surface);position:sticky;top:0}
th a{color:var(--steel)} th a:hover{color:var(--primary)}
td:first-child,th:first-child{text-align:left}
tbody tr:hover{background:var(--cream-l);cursor:pointer}
td.id{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;color:var(--primary);font-weight:500}
.num{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace}
.neg{color:#dc2626} .pos{color:#1f9d57} .scard .v.neg{color:#dc2626} .scard .v.pos{color:#1f9d57}
.badge{font-size:11px;font-weight:600;border-radius:999px;padding:3px 10px}
input,select{background:var(--canvas);border:1px solid var(--hair3);color:var(--ink);border-radius:8px;padding:0 12px;font-size:13.5px;font-family:inherit;height:42px}
input:focus,select:focus{outline:none;border:2px solid var(--primary)}
.btn{background:var(--ink);color:#fff;border:none;border-radius:8px;padding:0 18px;height:42px;font-weight:500;cursor:pointer;font-family:inherit;font-size:14px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:16px 0 16px}
.chip{font-size:12.5px;border:1px solid var(--hair2);border-radius:999px;padding:7px 13px;color:var(--steel);background:var(--canvas)}
.chip.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.pager{display:flex;gap:10px;align-items:center;margin-top:16px;justify-content:center;color:var(--steel);font-size:13px}
.pager a{border:1px solid var(--hair2);border-radius:8px;padding:8px 14px;background:var(--canvas)}
.pager a:hover{border-color:var(--primary);color:var(--primary)}
.kgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:18px 0 8px}
.fields{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:9px}
#ptip{position:fixed;display:none;z-index:9999;max-width:320px;background:#0f172a;color:#f1f5f9;font-size:12.5px;font-weight:400;line-height:1.5;letter-spacing:0;padding:9px 12px;border-radius:9px;border:1px solid #334155;box-shadow:0 10px 30px rgba(15,23,42,.32);pointer-events:none}
[data-tip]{cursor:help}
.fld{display:flex;justify-content:space-between;align-items:center;gap:10px;background:var(--canvas);border:1px solid var(--hair);border-radius:8px;padding:9px 13px;font-size:13px}
.fld .k{color:var(--steel);flex:none;white-space:nowrap}
.fld .v{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;text-align:right;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* блюр данных (по умолчанию) — наведи на ячейку/строку чтобы раскрыть, или кнопка в сайдбаре */
.fld .v,.scard .v,.scard .s,.cohcard .tv,.cohcard .tl,.journey .jrow:not(.head) .n,.journey .jrow:not(.head) .muted,tbody td.num,td.id,.cnt,.bd,.lead b,.banner b,.arcard b{filter:blur(5px);transition:filter .1s}
.fld:hover .v,.scard:hover .v,.scard:hover .s,.cohcard .trow:hover .tv,.cohcard .trow:hover .tl,.journey .jrow:not(.head) .n:hover,.journey .jrow:not(.head) .muted:hover,tbody td.num:hover,tbody tr:hover td.id,.cnt:hover,.bd:hover,.lead b:hover,.banner b:hover,.arcard:hover b{filter:none}
body.noblur .fld .v,body.noblur .scard .v,body.noblur .scard .s,body.noblur .cohcard .tv,body.noblur .cohcard .tl,body.noblur .journey .jrow .n,body.noblur .journey .jrow .muted,body.noblur tbody td.num,body.noblur td.id,body.noblur .cnt,body.noblur .bd,body.noblur .lead b,body.noblur .banner b,body.noblur .arcard b{filter:none}
/* цифры/подписи внутри графиков (SVG-рендер) — фигуры графиков не трогаем */
.chart text,.cohchart text{filter:blur(4px);transition:filter .1s}
.chart:hover text,.cohchart:hover text{filter:none}
body.noblur .chart text,body.noblur .cohchart text{filter:none}
.blureye{position:fixed;top:16px;right:22px;z-index:60;width:40px;height:40px;border-radius:50%;border:1px solid var(--hair);background:var(--canvas);font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 10px rgba(15,23,42,.10);line-height:1;padding:0}
.blureye:hover{border-color:var(--primary);box-shadow:0 3px 14px rgba(37,99,235,.22)}
.journey{display:flex;flex-direction:column;gap:5px}
.jrow{position:relative;display:grid;grid-template-columns:96px 200px 1fr 74px 62px;gap:10px;align-items:center;padding:9px 13px;border-radius:8px;font-size:13px;background:var(--canvas);border:1px solid var(--hair);overflow:hidden}
.jrow.stuck{border-color:var(--primary);background:var(--cream)}
.jrow i{position:absolute;left:0;top:0;bottom:0;background:rgba(37,99,235,.10);z-index:0}
.jrow>*{position:relative;z-index:1}
.jrow .g{color:var(--primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.jrow .d,.jrow .n{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;color:var(--steel)}
.jrow.head{background:transparent;border:none;color:var(--stone);font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;padding:0 13px 2px}
.jrow.head span{font-family:inherit}
.back{color:var(--steel);font-size:13px}
.sec{margin-top:24px}
.sec h2{font-weight:700;font-size:20px;margin-bottom:12px;color:#1e293b}
.sec.coll>summary{cursor:pointer;list-style:none;font-weight:700;font-size:20px;color:#1e293b;margin-bottom:12px;display:flex;align-items:center;gap:10px;user-select:none;padding:9px 14px;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:10px;transition:background .12s}
.sec.coll>summary:hover{background:#e6edf5}
.sec.coll>summary::-webkit-details-marker{display:none}
.sec.coll>summary::before{content:'\25B8';color:#2563eb;font-size:18px;line-height:1;transition:transform .15s;flex:none}
.sec.coll[open]>summary::before{transform:rotate(90deg)}
.sec.coll>summary::after{content:'нажми, чтобы развернуть \25BE';margin-left:auto;font-size:11px;color:#94a3b8;font-weight:400}
.sec.coll[open]>summary::after{content:'свернуть \25B4'}
.sec.coll>summary .muted{font-weight:400}
.muted{color:var(--steel);font-size:13px}
.chgrid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.chartbox{background:var(--canvas);border:1px solid var(--hair);border-radius:12px;padding:18px 20px}
.chartbox h3{font-size:14px;font-weight:600;margin-bottom:2px}
.chartbox .cap{font-size:12px;color:var(--steel);margin-bottom:10px}
.chart{width:100%;height:300px}
.banner{background:var(--cream);border:1px solid var(--beige);border-left:3px solid var(--primary);border-radius:12px;padding:15px 18px;margin-top:24px;font-size:13.5px;line-height:1.6}
.banner b{color:var(--ink)}
.stripe{display:none}
.foot{background:var(--cream);color:var(--steel);font-size:12.5px;padding:13px 34px;border-top:1px solid var(--beige);display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
.foot b{color:var(--primary)}
@media(max-width:1000px){.side{display:none}.cards{grid-template-columns:repeat(2,1fr)}.chgrid{grid-template-columns:1fr}}
"""

NAVITEMS = [
 ('grp','Ретеншн-отдел'),
 ('desk','/desk','🎛','Пульт (очередь)'),
 ('live','/live','🔴','Играют сейчас'),
 ('report','/report','📑','Отчёт отдела'),
 ('exports','/exports','📋','Проверка выгрузок'),
 ('grp','Главное'),
 ('overview','/overview','📊','Обзор'),
 ('players','/','👥','Игроки'),
 ('affiliates','/affiliates','🤝','Аффилиаты'),
 ('analytics','/analytics','📈','Аналитика'),
 ('ltv','/ltv','💎','LTV-прогноз'),
 ('dist','/dist','📐','Распределения'),
 ('funnel','/funnel','🫗','Воронка депозитов'),
 ('rfm','/rfm','🎯','RFM-сегменты'),
 ('cohorts','/cohorts','🧩','Все когорты'),
 ('archetypes','/archetypes','🧬','Архетипы'),
 ('games','/games','🎮','Игры'),
 ('schema','/schema','🗺','Схема данных'),
 ('formulas','/formulas','📐','Формулы расчётов'),
 ('glossary','/glossary','📖','Обозначения (словарь)'),
 ('grp','Маркетинг'),
 ('actions','/actions','🎯','Действия / Офферы'),
 ('bonus','/bonus','🎁','Бонусы: эффект'),
 ('bonuses','/bonuses','🎯','Бонусы: каталог'),
 ('campaigns','/campaigns','📣','Бонус-кампании'),
 ('grp','Деньги и риск'),
 ('ggr','/ggr','📈','GGR и доход'),
 ('cash','/analytics#cash','💰','Деньги'),
 ('risk','/audit','🚨','Аудит выводов'),
 ('grp','Интеграция'),
 ('signals','/signals','🧠','Сигналы модели'),
 ('keys','/keys','🔑','Ключи интеграции'),
]

_SP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
ICONS = {
 'formulas': _SP+'<path d="M18 4H7l7 8-7 8h11"/></svg>',
 'glossary': _SP+'<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
 'rfm': _SP+'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/></svg>',
 'overview': _SP+'<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/></svg>',
 'players': _SP+'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
 'affiliates': _SP+'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/><path d="M20 8v6M23 11h-6"/></svg>',
 'analytics': _SP+'<path d="M3 3v18h18"/><rect x="7" y="11" width="3" height="6" rx=".5"/><rect x="12" y="7" width="3" height="10" rx=".5"/><rect x="17" y="4" width="3" height="13" rx=".5"/></svg>',
 'ltv': _SP+'<path d="M6 3h12l4 6-10 12L2 9z"/><path d="M2 9h20M9 3 6 9l6 12 6-12-3-6"/></svg>',
 'cohorts': _SP+'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/></svg>',
 'archetypes': _SP+'<circle cx="6" cy="7" r="3"/><circle cx="18" cy="7" r="3"/><circle cx="12" cy="17" r="3"/><path d="M9 7h6M7.5 9.5 10.5 15M16.5 9.5 13.5 15"/></svg>',
 'games': _SP+'<rect x="2" y="6" width="20" height="12" rx="4"/><line x1="7" y1="12" x2="11" y2="12"/><line x1="9" y1="10" x2="9" y2="14"/><circle cx="16" cy="11" r="0.6" fill="currentColor"/><circle cx="18.5" cy="13.5" r="0.6" fill="currentColor"/></svg>',
 'schema': _SP+'<line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>',
 'desk': _SP+'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 9v12"/><circle cx="6" cy="6" r="0.6" fill="currentColor"/></svg>',
 'live': _SP+'<circle cx="12" cy="12" r="3"/><path d="M5 12a7 7 0 0 1 14 0M2 12a10 10 0 0 1 20 0"/></svg>',
 'report': _SP+'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/></svg>',
 'dist': _SP+'<path d="M3 21V3"/><path d="M7 21v-6M11 21v-10M15 21v-7M19 21v-13"/></svg>',
 'funnel': _SP+'<path d="M3 4h18l-7 8v7l-4-2v-5z"/></svg>',
 'actions': _SP+'<path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z"/></svg>',
 'bonus': _SP+'<rect x="3" y="8" width="18" height="13" rx="1"/><path d="M3 12h18M12 8v13M12 8S9 3 6.5 4.5 9 8 12 8 15 6 14.5 4.5 12 8 12 8z"/></svg>',
 'campaigns': _SP+'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/></svg>',
 'cash': _SP+'<rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>',
 'risk': _SP+'<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
}

def layout(active, content, head_extra=''):
    nav = ''
    for it in NAVITEMS:
        if it[0] == 'grp':
            nav += f'<div class=grp>{it[1]}</div>'
        else:
            key, href, ic, label = it
            on = ' on' if key == active else ''
            nav += f'<a class="{on.strip()}" href="{href}"><span class=i>{ICONS.get(key, ic)}</span>{label}</a>'
    return ("<!DOCTYPE html><html lang=ru><head><meta charset=UTF-8>"
      "<meta http-equiv='Cache-Control' content='no-cache, no-store, must-revalidate'>"
      "<meta http-equiv='Pragma' content='no-cache'><meta http-equiv='Expires' content='0'>"
      "<meta name=viewport content='width=device-width,initial-scale=1'>"
      "<style>" + CSS + "</style>" + head_extra + "</head><body>"
      "<script>try{if(localStorage.getItem('blur')!=='1')document.body.classList.add('noblur')}catch(e){}"
      "try{if(window.echarts){var _ei=echarts.init;echarts.init=function(el,t,o){return _ei(el,t,Object.assign({renderer:'svg'},o||{}))}}}catch(e){}</script>"
      "<button id=blurbtn class=blureye onclick='tgBlur()' title='скрыть/показать данные'>🙈</button>"
      "<div class=app><div class=side><div class=brand><span class=m>R</span><div><div class=bt>Retention</div><div class=bs>ClickHouse · live</div></div></div>"
      "<div class=nav>" + nav + "</div></div>"
      "<div class=main>" + content + "</div></div>"
      "<div class=stripe></div>"
      f"<div class=foot><span>Retention Board · <b>live</b> из ClickHouse · только real-игроки · <b>данные по {dmy(data_asof())}</b> (включительно) · PII не хранится</span>"
      "<span>дизайн: Sellrise</span></div>"
      "<script>function tgBlur(){var b=document.body.classList.toggle('noblur');try{localStorage.setItem('blur',b?'0':'1')}catch(e){}blbtn()}"
      "function blbtn(){var e=document.getElementById('blurbtn');if(e)e.textContent=document.body.classList.contains('noblur')?'👁':'🙈'}blbtn();</script>"
      "<div id=ptip></div>"
      "<script>(function(){var t=document.getElementById('ptip');"
      "document.addEventListener('mouseover',function(e){var el=e.target.closest('[data-tip]');if(el){t.textContent=el.getAttribute('data-tip');t.style.display='block';}});"
      "document.addEventListener('mouseout',function(e){var el=e.target.closest('[data-tip]');if(el&&!el.contains(e.relatedTarget))t.style.display='none';});"
      "document.addEventListener('mousemove',function(e){if(t.style.display!=='block')return;var x=e.clientX+14,y=e.clientY+18,w=t.offsetWidth,h=t.offsetHeight;if(x+w>innerWidth-10)x=e.clientX-w-14;if(y+h>innerHeight-10)y=e.clientY-h-18;t.style.left=x+'px';t.style.top=y+'px';});})();</script>"
      "</body></html>")

def spark(vals, color='#2563eb'):
    vals = [float(v or 0) for v in vals]
    if len(vals) < 2: return ''
    lo, hi = min(vals), max(vals); rng = (hi - lo) or 1
    n = len(vals)
    pts = ' '.join(f'{i/(n-1)*150:.1f},{33-(v-lo)/rng*30:.1f}' for i, v in enumerate(vals))
    return (f'<svg class=spark viewBox="0 0 150 36" preserveAspectRatio=none>'
            f'<polyline points="{pts}" fill=none stroke="{color}" stroke-width=2/></svg>')

def scard(cls, ic, lbl, val, sub, sp=''):
    return (f'<div class="scard {cls}"><div class=ic>{ic}</div><div class=l>{lbl}</div>'
            f'<div class=v>{val}</div><div class=s>{sub}</div>{sp}</div>')

SORTS = {'turnover','bets','net','recency_days','dep_sum','active_days','casino_player_id','bonus_sum'}

# только реальные игроки (исключаем service/admin, test_or_service, blocked)
NRM = "casino_player_id IN (SELECT casino_player_id FROM users WHERE account_type='normal')"

# ============================ ПРОВЕРКА ВЫГРУЗОК (журнал segment_exports) ============================
_DEP_COND = "type IN ('deposit','manual_deposit') AND status='completed'"
_BON_COND = "type IN ('freespin','manual_bonus','bonus') AND status='completed'"
_WD_COND  = "type IN ('withdrawal','manual_withdrawal') AND status='completed'"

@app.route('/exports')
def exports_view():
    from urllib.parse import quote
    exp = request.args.get('exp'); seg = request.args.get('seg')

    def fdt(d):
        if not d: return '—'
        try: return d.strftime('%d.%m %H:%M')
        except Exception: return str(d)[:16]

    # ---------- ДЕТАЛЬ выбранной выгрузки ----------
    if exp and seg:
        rows = q("""
        WITH ex AS (SELECT casino_player_id, rec_bonus FROM segment_exports
                    WHERE toString(export_ts)={ts:String} AND segment={seg:String}),
        thr AS (SELECT any(export_ts) t FROM segment_exports
                WHERE toString(export_ts)={ts:String} AND segment={seg:String}),
        mon AS (
          SELECT m.casino_player_id cid,
            countIf(""" + _DEP_COND + """) dep_n, round(sumIf(toFloat64(amount), """ + _DEP_COND + """)) dep_sum,
            minIf(created_at, """ + _DEP_COND + """) dep_first,
            countIf(""" + _BON_COND + """) bonus_n, minIf(created_at, """ + _BON_COND + """) bonus_first,
            round(sumIf(toFloat64(amount), """ + _WD_COND + """)) wd_sum
          FROM money_transactions m INNER JOIN ex ON m.casino_player_id=ex.casino_player_id
          WHERE m.created_at > (SELECT t FROM thr) GROUP BY cid),
        gam AS (
          SELECT g.casino_player_id cid, count() bets_after
          FROM game_transactions g INNER JOIN ex ON g.casino_player_id=ex.casino_player_id
          WHERE g.created_at > (SELECT t FROM thr) AND g.transaction_type IN ('bet','freespins_bet') GROUP BY cid)
        SELECT ex.casino_player_id, ex.rec_bonus,
          ifNull(m.dep_n,0), ifNull(m.dep_sum,0), m.dep_first,
          ifNull(m.bonus_n,0), m.bonus_first, ifNull(g.bets_after,0), ifNull(m.wd_sum,0)
        FROM ex LEFT JOIN mon m ON ex.casino_player_id=m.cid LEFT JOIN gam g ON ex.casino_player_id=g.cid
        ORDER BY (ifNull(m.dep_n,0)>0) DESC, ifNull(m.dep_sum,0) DESC, (ifNull(g.bets_after,0)>0) DESC
        """, {'ts': exp, 'seg': seg})[1]
        total = len(rows); dep = sum(1 for r in rows if r[2] > 0); bon = sum(1 for r in rows if r[5] > 0)
        ret = sum(1 for r in rows if r[7] > 0); dnp = sum(1 for r in rows if r[2] > 0 and r[7] == 0)
        dep_try = sum(float(r[3] or 0) for r in rows)          # внесли после выгрузки
        wd_try  = sum(float(r[8] or 0) for r in rows)          # вывели после выгрузки
        net_try = dep_try - wd_try                             # чистыми
        cards = ('<div class=cards>'
          + scard('', '📋', 'Игроков в выгрузке', f(total), 'передано в кол-центр')
          + scard('cream', '💰', 'Депнули после', f(dep),
                  f'{round(dep / total * 100) if total else 0}% списка · внесли <b>{f(dep_try)} ₺</b>')
          + scard('', '💸', 'Вывели после', mn(wd_try), 'выводы этих же игроков')
          + scard('orange' if net_try >= 0 else 'alert', '💵', 'Чистыми (деп − вывод)', mn(net_try), 'сколько реально принесли')
          + scard('', '🎮', 'Вернулись к игре', f(ret), 'сделали ставку')
          + scard('alert', '⚠️', 'Депнул, но не играл', f(dnp), 'внёс, но без ставок')
          + '</div>')
        trs = ''
        for cid, recb, dep_n, dep_sum, dep_first, bonus_n, bonus_first, bets, wd_sum in rows:
            res = ('🟢 депозит' if dep_n > 0 else ('🎮 вернулся' if bets > 0 else ('🎁 бонус' if bonus_n > 0 else '—')))
            dnp_b = ' <span class=neg>· не играл</span>' if (dep_n > 0 and bets == 0) else ''
            pnet = float(dep_sum or 0) - float(wd_sum or 0)
            has_money = (dep_n > 0 or (wd_sum or 0) > 0)
            trs += ('<tr onclick="location.href=\'/player/' + str(cid) + '\'">'
              '<td class=id>' + str(cid) + '</td>'
              '<td class="num ' + ('pos' if dep_n > 0 else '') + '">' + (('+' + f(dep_sum) + ' ₺') if dep_n > 0 else '—') + '</td>'
              '<td class="num ' + ('neg' if (wd_sum or 0) > 0 else '') + '">' + (('−' + f(wd_sum) + ' ₺') if (wd_sum or 0) > 0 else '—') + '</td>'
              '<td class="num ' + ('pos' if pnet >= 0 else 'neg') + '"><b>' + (f(pnet) + ' ₺' if has_money else '—') + '</b></td>'
              '<td>' + (fdt(dep_first) if dep_n > 0 else '—') + '</td>'
              '<td>' + (('🎁 ' + fdt(bonus_first)) if bonus_n > 0 else '—') + '</td>'
              '<td>' + (('да (' + f(bets) + ')') if bets > 0 else 'нет') + '</td>'
              '<td>' + res + dnp_b + '</td>'
              '<td class=muted>' + str(escape(str(recb or '—')))[:22] + '</td></tr>')
        table = ('<div class=panel style="overflow-x:auto"><table><thead><tr>'
          '<th>Игрок</th><th>Внёс после</th><th>Вывел после</th>'
          '<th title="депозиты минус выводы после выгрузки">Чистыми</th>'
          '<th>Когда депнул</th><th>Бонус после</th>'
          '<th>Вернулся к игре</th><th>Результат</th><th>Реком. бонус</th></tr></thead><tbody>'
          + (trs or '<tr><td colspan=9 class=muted>нет игроков</td></tr>') + '</tbody></table></div>')
        dsp = q("SELECT formatDateTime(toTimezone(any(export_ts),'Europe/Istanbul'),'%d.%m.%Y %H:%i') "
                "FROM segment_exports WHERE toString(export_ts)={ts:String} AND segment={seg:String}",
                {'ts': exp, 'seg': seg})[1]
        dsp = dsp[0][0] if dsp else exp[:16]
        content = ('<a class=back href="/exports">← ко всем выгрузкам</a>'
          '<div class=topbar><div><div class=h1>📋 Выгрузка <em class=bd>' + str(escape(seg)) + '</em> '
          '<span class=muted>от ' + str(escape(dsp)) + '</span></div>'
          '<div class=lead>что случилось с игроками из этого списка ПОСЛЕ передачи в кол-центр</div></div></div>'
          + cards + table)
        return layout('exports', content)

    # ---------- СПИСОК выгрузок (журнал) ----------
    rows = q("""
    WITH pl AS (SELECT DISTINCT casino_player_id cid FROM segment_exports),
    mp AS (
      SELECT casino_player_id cid, maxIf(created_at,""" + _DEP_COND + """) last_dep,
             maxIf(created_at,""" + _BON_COND + """) last_bon
      FROM money_transactions WHERE casino_player_id IN (SELECT cid FROM pl) GROUP BY cid),
    gp AS (
      SELECT casino_player_id cid, maxIf(created_at, transaction_type IN ('bet','freespins_bet')) last_bet
      FROM game_transactions WHERE casino_player_id IN (SELECT cid FROM pl) GROUP BY cid)
    , dm AS (
      SELECT e2.export_ts ets2, e2.segment seg2,
             round(sumIf(toFloat64(m2.amount), m2.""" + _DEP_COND.replace(" AND ", " AND m2.") + """)) dep_try,
             round(sumIf(toFloat64(m2.amount), m2.""" + _WD_COND.replace(" AND ", " AND m2.") + """)) wd_try
      FROM segment_exports e2
      INNER JOIN money_transactions m2 ON m2.casino_player_id = e2.casino_player_id
      WHERE m2.created_at > e2.export_ts
      GROUP BY ets2, seg2)
    SELECT toString(e.export_ts) ets,
      any(formatDateTime(toTimezone(e.export_ts,'Europe/Istanbul'),'%d.%m.%Y %H:%i')) disp,
      e.segment, count() n,
      countIf(mp.last_dep > e.export_ts) deposited,
      countIf(mp.last_bon > e.export_ts) bonus_given,
      countIf(gp.last_bet > e.export_ts) returned,
      countIf(mp.last_dep > e.export_ts AND NOT (gp.last_bet > e.export_ts)) dep_no_play,
      max(e.is_demo) is_demo,
      ifNull(any(dm.dep_try), 0) dep_try,
      ifNull(any(dm.wd_try), 0) wd_try
    FROM segment_exports e LEFT JOIN mp ON mp.cid=e.casino_player_id LEFT JOIN gp ON gp.cid=e.casino_player_id
    LEFT JOIN dm ON dm.ets2=e.export_ts AND dm.seg2=e.segment
    GROUP BY ets, e.segment ORDER BY ets DESC, e.segment
    """)[1]
    n_exp = len(rows); n_players = sum(r[3] for r in rows); n_dep = sum(r[4] for r in rows)
    n_try = sum(float(r[9] or 0) for r in rows)      # депозиты после выгрузок
    n_wd  = sum(float(r[10] or 0) for r in rows)     # выводы после выгрузок
    n_net = n_try - n_wd                             # «чистыми» = депозиты − выводы
    netc = 'orange' if n_net >= 0 else 'alert'
    cards = ('<div class=cards>'
      + scard('', '📋', 'Выгрузок в журнале', f(n_exp), 'переданных списков')
      + scard('', '👥', 'Игроков всего', f(n_players), 'по всем выгрузкам')
      + scard('cream', '💰', 'Депнули после', f(n_dep), f'внесли <b>{f(n_try)} ₺</b>')
      + scard('', '💸', 'Вывели после', mn(n_wd), 'выводы этих же игроков')
      + scard(netc, '💵', 'Чистыми (деп − вывод)', mn(n_net), 'сколько реально принесли')
      + '</div>')
    trs = ''
    for ets, disp, segn, n, dep, bon, ret, dnp, is_demo, dtry, wtry in rows:
        demo = (' <span class=pill style="background:#fef3c7;color:#92400e">ДЕМО</span>' if is_demo else '')
        href = '/exports?exp=' + quote(ets) + '&seg=' + quote(segn)
        pct = round(dep / n * 100) if n else 0
        net = float(dtry or 0) - float(wtry or 0)
        trs += ('<tr onclick="location.href=\'' + href + '\'">'
          '<td class=muted>' + str(escape(disp)) + '</td>'
          '<td><b>' + str(escape(segn)) + '</b>' + demo + '</td>'
          '<td class=num>' + f(n) + '</td>'
          '<td class="num pos">' + f(dep) + ' <span class=muted>(' + str(pct) + '%)</span></td>'
          '<td class="num pos">' + f(dtry) + ' ₺</td>'
          '<td class="num neg">' + f(wtry) + ' ₺</td>'
          '<td class="num ' + ('pos' if net >= 0 else 'neg') + '"><b>' + f(net) + '</b> ₺</td>'
          '<td class=num>' + f(bon) + '</td>'
          '<td class=num>' + f(ret) + '</td>'
          '<td class="num ' + ('neg' if dnp else '') + '">' + f(dnp) + '</td>'
          '<td>→</td></tr>')
    table = ('<div class=panel style="overflow-x:auto"><table><thead><tr>'
      '<th>Дата выгрузки</th><th>Сегмент</th><th>Игроков</th><th>Депнули после</th>'
      '<th title="сумма депозитов этих игроков после передачи списка">Внесли ₺</th>'
      '<th title="сумма выводов этих же игроков после передачи списка">Вывели ₺</th>'
      '<th title="депозиты минус выводы — сколько реально принесли">Чистыми ₺</th>'
      '<th>Бонус дали</th><th>Вернулись</th><th>Депнул, не играл</th><th></th></tr></thead><tbody>'
      + (trs or '<tr><td colspan=11 class=muted>выгрузок нет — запусти load_exports.py</td></tr>') + '</tbody></table></div>')
    content = ('<div class=topbar><div><div class=h1>📋 Проверка выгрузок <em class=bd>· результаты кол-центра</em></div>'
      '<div class=lead>журнал переданных списков и что вышло ПОСЛЕ выгрузки: депозит / бонус / возврат к игре · клик по строке — детали</div></div></div>'
      + cards + table)
    return layout('exports', content)


# ============================ GGR & REVENUE ANALYTICS (реплика родного борда казино) ============================
GGR_TABS = [('dashboard','Обзор'), ('provider','Провайдеры'), ('game','Игры'),
            ('segments','Сегменты'), ('bonus','Бонусы и расходы'), ('rates','Ставки провайдеров'),
            ('settle','Расчёты и выплаты'), ('reports','Отчёты и экспорт')]

def _ggr_kpis(gw, mw, dwm, pfilt_sql, dw_date):
    """Считает блок KPI для окна: (bet,win,rounds,active,ggr,rtp,avg_bet,bonus,pcost,affcost,ngr,bratio)."""
    bet, win, rounds, active = [float(x or 0) for x in q(
        f"SELECT round(sumIf(bet_amount,{BET_T})), round(sumIf(win_amount,{WIN_T})), "
        f"countIf({BET_T}), uniqExactIf(casino_player_id,{BET_T}) FROM game_transactions WHERE {gw}")[1][0]]
    ggr = bet - win
    bonus = float(q(f"SELECT round(sumIf(abs(amount),{BONUS_OK})) FROM money_transactions WHERE {mw}")[1][0][0] or 0)
    pcost = provider_cost_total(f"{pfilt_sql} AND {dw_date}")
    affc = float(q(
        f"WITH aff AS (SELECT u.affiliate_code code, "
        f"sumIf(m.amount,{DEP_OK} AND {dwm})-sumIf(abs(m.amount),{WD_OK} AND {dwm}) net "
        f"FROM money_transactions m INNER JOIN users u USING(casino_player_id) "
        f"WHERE u.affiliate_code!='' AND {pfilt_sql} GROUP BY code) "
        f"SELECT ifNull(round(sum(greatest(aff.net,0)*ar.commission_rate_percent/100)),0) "
        f"FROM aff INNER JOIN affiliate_rates ar ON aff.code=ar.affiliate_code")[1][0][0] or 0)
    ngr = ggr - bonus - pcost - affc
    return dict(bet=bet, win=win, rounds=rounds, active=active, ggr=ggr,
                rtp=round(win/bet*100, 2) if bet else 0, avg_bet=round(bet/rounds, 2) if rounds else 0,
                bonus=bonus, pcost=pcost, affc=affc, ngr=ngr,
                bratio=round(bonus/ggr*100, 1) if ggr else 0)

@app.route('/ggr')
def ggr_page():
    import re as _re
    import datetime as _dt
    from datetime import timedelta
    def _vd(s, d): return s if s and _re.fullmatch(r'\d{4}-\d{2}-\d{2}', s) else d  # строгая маска YYYY-MM-DD
    dmax = data_asof()
    if isinstance(dmax, _dt.datetime): dmax = dmax.date()          # data_asof может вернуть datetime
    elif isinstance(dmax, str): dmax = _dt.date.fromisoformat(dmax[:10])
    frm = _vd(request.args.get('from'), str(dmax - timedelta(days=29)))
    to = _vd(request.args.get('to'), str(dmax))
    prov = ''.join(c for c in request.args.get('provider', '') if c.isalnum() or c in ' _-&.')[:40]
    country = ''.join(c for c in request.args.get('country', '') if c.isalnum())[:8].upper()
    aff = ''.join(c for c in request.args.get('aff', '') if c.isalnum() or c == '_')[:64]
    lim = min(max(int(request.args.get('limit', '25') or 25), 5), 200)
    tab = request.args.get('tab', 'dashboard')
    tab = tab if tab in dict(GGR_TABS) else 'dashboard'

    PROV = "dictGetOrDefault('{CH_DB}.dict_game_names','provider',tuple(game_uuid),'')"
    GNAME = GN('game_uuid')
    pfilt = ["account_type='normal'"]
    if country: pfilt.append(f"country_iso_estimated='{country}'")
    if aff: pfilt.append(f"affiliate_code='{aff}'")
    NRMg = f"casino_player_id IN (SELECT casino_player_id FROM users WHERE {' AND '.join(pfilt)})"
    def dwin(f, t): return f"toDate(toTimezone(created_at,'Europe/Istanbul')) BETWEEN '{f}' AND '{t}'"
    dw = dwin(frm, to)
    gw = f"{GSUCCESS} AND currency='TRY' AND {NRMg} AND {dw}"
    if prov: gw += f" AND {PROV}='{escape(prov)}'"
    mw = f"{NRMg} AND {dw}"

    k = _ggr_kpis(gw, mw, dw, NRMg, dw)
    # дельта к предыдущему равному периоду
    from datetime import date as _date
    d0 = _date.fromisoformat(frm); d1 = _date.fromisoformat(to); span = (d1 - d0).days + 1
    pf, pt = str(d0 - timedelta(days=span)), str(d0 - timedelta(days=1))
    pgw = f"{GSUCCESS} AND currency='TRY' AND {NRMg} AND {dwin(pf,pt)}" + (f" AND {PROV}='{escape(prov)}'" if prov else '')
    pmw = f"{NRMg} AND {dwin(pf,pt)}"
    pk = _ggr_kpis(pgw, pmw, dwin(pf, pt), NRMg, dwin(pf, pt))
    def dlt(cur, prev):
        if not prev: return ''
        p = round((cur - prev) / abs(prev) * 100, 1)
        cls = 'pos' if p >= 0 else 'neg'
        return f'<span class="badge {cls}">{p:+.1f}%</span>'

    kc = (f'<div class=cards>'
      + scard('', '🎲', 'СУММА СТАВОК', mn(k['bet']), f'оборот · {f(k["rounds"])} ставок {dlt(k["bet"],pk["bet"])}')
      + scard('', '🏆', 'ВЫИГРЫШИ', mn(k['win']), f'выплачено игрокам {dlt(k["win"],pk["win"])}')
      + scard('orange', '🎯', 'GGR — доход казино', mn(k['ggr']), f'Ставки − Выигрыши {dlt(k["ggr"],pk["ggr"])}')
      + scard('', '📊', 'RTP — возврат игрокам', f'{k["rtp"]}%', f'Выигрыш / Ставка × 100 {dlt(k["rtp"],pk["rtp"])}')
      + scard(('alert' if k['ngr'] < 0 else 'cream'), '💠', 'NGR — чистый доход', mn(k['ngr']), f'GGR − бонусы − провайдер − аффилиат {dlt(k["ngr"],pk["ngr"])}')
      + '</div>')
    kc2 = (f'<div class=cards>'
      + scard('', '🎁', 'РАСХОД НА БОНУСЫ', mn(k['bonus']), f"{k['bratio']}% от GGR {dlt(k['bonus'],pk['bonus'])}")
      + scard('', '🏭', 'РАСХОД НА ПРОВАЙДЕРОВ', mn(k['pcost']), f'ENGR+Infra+RevShare {dlt(k["pcost"],pk["pcost"])}')
      + scard('', '🤝', 'РАСХОД НА АФФИЛИАТОВ', mn(k['affc']), f'CPA + RevShare {dlt(k["affc"],pk["affc"])}')
      + scard('', '🟢', 'АКТИВНЫХ ИГРОКОВ', f(k['active']), f'уникальных за период {dlt(k["active"],pk["active"])}')
      + scard('', '🎫', 'СРЕДНЯЯ СТАВКА', f'₺{k["avg_bet"]}', f'на одну ставку {dlt(k["avg_bet"],pk["avg_bet"])}')
      + '</div>')

    # ---- фильтр-панель ----
    provs = [r[0] for r in q(f"SELECT DISTINCT {PROV} p FROM game_transactions WHERE {gw} AND {PROV}!='' ORDER BY p")[1]]
    countries = [r[0] for r in q("SELECT DISTINCT country_iso_estimated c FROM users WHERE account_type='normal' AND country_iso_estimated!='' ORDER BY c")[1]]
    def opts(vals, cur):
        o = f'<option value="">Все</option>'
        for v in vals: o += f'<option value="{escape(str(v))}"{" selected" if str(v)==cur else ""}>{escape(str(v))}</option>'
        return o
    filt = (f'<form class=ggrfilt method=get>'
      f'<input type=hidden name=tab value="{escape(tab)}">'
      f'<label>ДАТА<span><input type=date name=from value="{frm}"> — <input type=date name=to value="{to}"></span></label>'
      f'<label>ПРОВАЙДЕР<select name=provider>{opts(provs, prov)}</select></label>'
      f'<label>СТРАНА<select name=country>{opts(countries, country)}</select></label>'
      f'<label>АФФИЛИАТ<input name=aff value="{escape(aff)}" placeholder="код" style="width:110px"></label>'
      f'<label>ЛИМИТ<select name=limit>{opts([25,50,100,200], str(lim))}</select></label>'
      f'<button class=btn type=submit>Применить</button>'
      f'<a class="btn ghost" href="/ggr">Сбросить</a></form>')

    # ---- табы ----
    tabbar = '<div class=ggrtabs>' + ''.join(
        f'<a class="{"on" if t==tab else ""}" href="/ggr?tab={t}&from={frm}&to={to}'
        + (f'&provider={quote(prov)}' if prov else '') + (f'&country={country}' if country else '')
        + f'">{escape(lbl)}</a>' for t, lbl in GGR_TABS) + '</div>'

    # ---- контент таба ----
    if tab == 'dashboard':
        daily = q(f"SELECT toString(toDate(toTimezone(created_at,'Europe/Istanbul'))) d, round(sumIf(bet_amount,{BET_T})-sumIf(win_amount,{WIN_T})) g FROM game_transactions WHERE {gw} GROUP BY d ORDER BY d")[1]
        neg_days = sum(1 for _, g in daily if (g or 0) < 0)
        hrtp = q(f"SELECT {PROV} p, round(sumIf(win_amount,{WIN_T})*100/nullIf(sumIf(bet_amount,{BET_T}),0),1) rtp FROM game_transactions WHERE {gw} AND {PROV}!='' GROUP BY p HAVING rtp>85 ORDER BY rtp DESC LIMIT 30")[1]
        sig = ''
        if neg_days: sig += f'<div class="rsig warn"><b>⚠ Отрицательный GGR</b><br><span class=muted>{neg_days} дн. с отрицательным GGR в периоде (игроки выиграли больше, чем поставили)</span></div>'
        if hrtp: sig += f'<div class="rsig warn"><b>🔺 Провайдеры с высоким RTP</b><br><span class=muted>{escape(", ".join(p for p,_ in hrtp))} — возврат игрокам выше 85%</span></div>'
        if k['bratio'] > 12: sig += f'<div class="rsig warn"><b>🎁 Доля бонусов выше нормы</b><br><span class=muted>Расход на бонусы = {k["bratio"]}% от GGR (норма ≤ 12%)</span></div>'
        if not sig: sig = '<div class=muted>сигналов нет — всё в норме</div>'
        DATA = jsdump({'d': [x[0][5:] for x in daily], 'g': [float(x[1] or 0) for x in daily]})
        body = (f'<div class=ggrgrid>'
          f'<div class=sec><h2>GGR по дням</h2><div id=ggrchart style="height:300px"></div></div>'
          f'<div class=sec><h2>Сигналы риска</h2>{sig}</div></div>'
          f'<script>const GD={DATA};(function(){{var el=document.getElementById("ggrchart");if(!el||!window.echarts)return;'
          f'var c=echarts.init(el);c.setOption({{grid:{{left:8,right:14,top:14,bottom:24,containLabel:true}},'
          f'tooltip:{{trigger:"axis"}},xAxis:{{type:"category",data:GD.d,axisLabel:{{fontSize:10}}}},yAxis:{{type:"value"}},'
          f'series:[{{type:"line",data:GD.g,smooth:true,symbol:"none",lineStyle:{{color:"#2563eb",width:2}},'
          f'areaStyle:{{color:new echarts.graphic.LinearGradient(0,0,0,1,[{{offset:0,color:"rgba(37,99,235,.25)"}},{{offset:1,color:"rgba(37,99,235,0)"}}])}}}}]}});'
          f'addEventListener("resize",function(){{c.resize()}});}})();</script>')
    elif tab in ('provider', 'game'):
        gb = PROV if tab == 'provider' else 'game_uuid'
        nm = PROV if tab == 'provider' else GNAME
        rows = q(f"SELECT {nm} name, round(sumIf(bet_amount,{BET_T})) bet, round(sumIf(win_amount,{WIN_T})) win, "
          f"round(sumIf(bet_amount,{BET_T})-sumIf(win_amount,{WIN_T})) ggr, "
          f"round(sumIf(win_amount,{WIN_T})*100/nullIf(sumIf(bet_amount,{BET_T}),0),1) rtp, "
          f"uniqExactIf(casino_player_id,{BET_T}) players, countIf({BET_T}) rounds "
          f"FROM game_transactions WHERE {gw}" + (f" AND {PROV}!=''" if tab == 'provider' else '')
          + f" GROUP BY {gb}, name ORDER BY bet DESC LIMIT {lim}")[1]
        tr = ''.join(f'<tr><td>{escape(str(nme))}</td><td class=num>{mn(b)}</td><td class=num>{mn(w)}</td>'
          f'<td class="num {"neg" if gg<0 else "pos"}">{mn(gg)}</td><td class=num>{rt or 0}%</td>'
          f'<td class=num>{f(pl)}</td><td class=num>{f(rn)}</td></tr>' for nme, b, w, gg, rt, pl, rn in rows)
        body = (f'<div class=sec><div class=panel style="overflow-x:auto"><table><thead><tr>'
          f'<th>{"Провайдер" if tab=="provider" else "Игра"}</th><th>Ставки</th><th>Выигрыши</th><th>GGR</th><th>RTP</th><th>Игроков</th><th>Раундов</th>'
          f'</tr></thead><tbody>{tr or "<tr><td colspan=7 class=muted>нет данных</td></tr>"}</tbody></table></div></div>')
    elif tab == 'rates':
        rows = q(f"SELECT provider, engr_percent, infra_percent, revshare_percent, fixed_fee, minimum_guarantee, period FROM provider_rates ORDER BY provider LIMIT {lim}")[1]
        tr = ''.join(f'<tr><td>{escape(str(p))}</td><td class=num>{e}%</td><td class=num>{i}%</td><td class=num>{r}%</td>'
          f'<td class=num>{ff}</td><td class=num>{mg}</td><td>{escape(str(pe))}</td></tr>' for p, e, i, r, ff, mg, pe in rows)
        body = (f'<div class=sec><div class=lead>Ставки провайдеров из справочника — по ним считается «Расход на провайдеров»</div>'
          f'<div class=panel style="overflow-x:auto"><table><thead><tr>'
          f'<th>Провайдер</th><th>ENGR%</th><th>Infra%</th><th>RevShare%</th><th>Фикс. плата</th><th>Мин. гарантия</th><th>Период</th>'
          f'</tr></thead><tbody>{tr}</tbody></table></div></div>')
    elif tab == 'segments':
        # ── VIP-сегменты по правилам казино: накопит. успешные депозиты TRY (all-time) ──
        VIPN = {5: '👑 Royal · ≥1M', 4: '💎 Diamond · ≥500k', 3: '💠 Platinum · ≥150k',
                2: '🥇 Gold · ≥50k', 1: '🥈 Silver · ≥100', 0: '⚪ Regular · &lt;100'}
        vrows = q(f"""WITH
          vip AS (
            SELECT cid, dep, multiIf(mx<100 OR dep<100,0,dep>=1000000,5,dep>=500000,4,
              dep>=150000,3,dep>=50000,2,1) lvl
            FROM (SELECT m.casino_player_id cid, sumIf(m.amount,{DEP_OK}) dep, maxIf(m.amount,{DEP_OK}) mx
                  FROM money_transactions m INNER JOIN users u USING(casino_player_id)
                  WHERE u.account_type='normal' AND m.currency='TRY' GROUP BY m.casino_player_id)),
          per AS (SELECT casino_player_id cid, sumIf(bet_amount,{BET_T}) bet, sumIf(win_amount,{WIN_T}) win
                  FROM game_transactions WHERE {gw} GROUP BY casino_player_id)
        SELECT vip.lvl, count() players, round(sum(vip.dep)) deposits, countIf(per.bet>0) active,
          round(sum(ifNull(per.bet,0))) bet, round(sum(ifNull(per.bet,0))-sum(ifNull(per.win,0))) ggr
        FROM vip LEFT JOIN per ON vip.cid=per.cid GROUP BY vip.lvl ORDER BY vip.lvl DESC""")[1]
        vtr = ''.join(f'<tr><td>{VIPN.get(int(lv), lv)}</td><td class=num>{f(pl)}</td><td class=num>{mn(dp)}</td>'
          f'<td class=num>{f(ac)}</td><td class=num>{mn(bt)}</td>'
          f'<td class="num {"neg" if (gg or 0)<0 else "pos"}">{mn(gg)}</td></tr>' for lv, pl, dp, ac, bt, gg in vrows)
        # ── Поведенческие сегменты (за период, пересекаются) ──
        b = q(f"""SELECT count(),
          countIf(isvip), round(sumIf(bet,isvip)), round(sumIf(bet-win,isvip)),
          countIf(bet-win>0), round(sumIf(bet,bet-win>0)), round(sumIf(bet-win,bet-win>0)),
          countIf(win-bet>0), round(sumIf(bet,win-bet>0)), round(sumIf(bet-win,win-bet>0)),
          countIf(bcost>0 OR bbet>0), round(sumIf(bet,bcost>0 OR bbet>0)), round(sumIf(bet-win,bcost>0 OR bbet>0)),
          round(sum(bbet+bcost)*100/nullIf(sum(bet),0),2)
        FROM (
          SELECT per.cid, per.bet bet, per.win win, per.bbet bbet, ifNull(bon.bcost,0) bcost, ifNull(v.isvip,0) isvip
          FROM (SELECT casino_player_id cid, sumIf(bet_amount,{BET_T}) bet, sumIf(win_amount,{WIN_T}) win,
                  sumIf(bet_amount,transaction_type='freespins_bet') bbet
                FROM game_transactions WHERE {gw} GROUP BY casino_player_id) per
          LEFT JOIN (SELECT casino_player_id cid, sumIf(abs(amount),{BONUS_OK}) bcost
                     FROM money_transactions WHERE {mw} GROUP BY casino_player_id) bon ON per.cid=bon.cid
          LEFT JOIN (SELECT casino_player_id cid, toUInt8(maxIf(amount,{DEP_OK})>=100 AND sumIf(amount,{DEP_OK})>=100) isvip
                     FROM money_transactions WHERE currency='TRY' GROUP BY casino_player_id) v ON per.cid=v.cid)""")[1][0]
        bh = [
          ('👑 VIP <span class=muted>(vip_level &gt; 0)</span>', b[1], b[2], b[3]),
          ('📉 High Loss <span class=muted>(Ставки &gt; Выигрыши)</span>', b[4], b[5], b[6]),
          ('📈 Winner <span class=muted>(Выигрыши &gt; Ставки)</span>', b[7], b[8], b[9]),
          ('🎁 Bonus User <span class=muted>(есть бонус/бонусные ставки)</span>', b[10], b[11], b[12]),
        ]
        btr = ''.join(f'<tr><td>{t}</td><td class=num>{f(n)}</td><td class=num>{mn(bt)}</td>'
          f'<td class="num {"neg" if (gg or 0)<0 else "pos"}">{mn(gg)}</td></tr>' for t, n, bt, gg in bh)
        body = (f'<div class=sec><h2>VIP-сегменты <span class=muted>по накопительным успешным депозитам (правила казино)</span></h2>'
          f'<div class=lead>VIP-уровень = накопительная сумма успешных депозитов в TRY за всё время; для уровня ≥ Silver нужен хотя бы один депозит ≥ 100 TRY. Ставки/GGR — за выбранный период.</div>'
          f'<div class=panel style="overflow-x:auto"><table><thead><tr><th>Уровень</th><th>Игроков</th><th>Σ депозитов</th>'
          f'<th>Активных в периоде</th><th>Ставки (период)</th><th>GGR (период)</th></tr></thead>'
          f'<tbody>{vtr or "<tr><td colspan=6 class=muted>нет данных</td></tr>"}</tbody></table></div></div>'
          f'<div class=sec><h2>Поведенческие сегменты <span class=muted>за период · могут пересекаться</span></h2>'
          f'<div class=panel style="overflow-x:auto"><table><thead><tr><th>Сегмент</th><th>Игроков</th><th>Ставки</th><th>GGR</th></tr></thead>'
          f'<tbody>{btr}</tbody></table></div>'
          f'<div class="rsig warn" style="margin-top:12px"><b>⚠ Risk/Abuse рейтинг = {b[13] or 0}%</b><br>'
          f'<span class=muted>(Бонусные ставки + Расход на бонусы) / Ставки × 100 за период. Рейтинговый показатель без фиксированного порога — чем выше, тем сильнее игра завязана на бонусы.</span></div></div>')
    elif tab == 'bonus':
        BT = ("multiIf(type='freespin','🎰 Фриспины',description ILIKE '%deneme%','🎁 Бездепозитный',"
              "description ILIKE '%kay%p%','💸 Кэшбэк',description ILIKE '%dsc%' OR description ILIKE '%yat%','💰 На депозит',"
              "type='manual_bonus','✋ Ручной бонус','Прочие')")
        rows = q(f"SELECT {BT} bt, count() events, uniqExact(casino_player_id) players, round(sum(abs(amount))) cost "
          f"FROM money_transactions WHERE {BONUS_OK} AND {mw} GROUP BY bt ORDER BY cost DESC")[1]
        totc = sum(r[3] or 0 for r in rows) or 1
        tr = ''.join(f'<tr><td>{escape(str(bt))}</td><td class=num>{f(ev)}</td><td class=num>{f(pl)}</td>'
          f'<td class=num>{mn(c)}</td><td class=num>{round((c or 0)/totc*100,1)}%</td></tr>' for bt, ev, pl, c in rows)
        body = (f'<div class=sec><h2>Bonus &amp; Cost <span class=muted>по типам бонуса за период</span></h2>'
          f'<div class=lead>Bonus cost = <b>{mn(totc)}</b> · {k["bratio"]}% от GGR (порог 12%)</div>'
          f'<div class=panel style="overflow-x:auto"><table><thead><tr>'
          f'<th>Тип бонуса</th><th>Начислений</th><th>Игроков</th><th>Стоимость</th><th>% от бонусов</th>'
          f'</tr></thead><tbody>{tr or "<tr><td colspan=5 class=muted>нет бонусов</td></tr>"}</tbody></table></div></div>')
    elif tab == 'settle':
        g = k['ggr'] or 0
        pct = lambda v: round(v / g * 100, 1) if g else 0
        wrows = [
          ('GGR — валовый доход', g, 100.0, 'Ставки − Выигрыши'),
          ('− Расход на бонусы', -k['bonus'], pct(k['bonus']), 'начислено игрокам'),
          ('− Расход на провайдеров', -k['pcost'], pct(k['pcost']), 'ENGR + Infra + RevShare'),
          ('− Расход на аффилиатов', -k['affc'], pct(k['affc']), 'CPA + RevShare'),
          ('= NGR — чистый доход', k['ngr'], pct(k['ngr']), 'остаётся казино'),
        ]
        wf = ''.join(f'<tr><td>{escape(t)}</td><td class="num {"neg" if v<0 else "pos"}">{mn(v)}</td>'
          f'<td class=num>{pc}%</td><td class=muted>{escape(d)}</td></tr>' for t, v, pc, d in wrows)
        arows = q(f"""WITH aff AS (
          SELECT u.affiliate_code code,
            sumIf(m.amount,{DEP_OK} AND {dw})-sumIf(abs(m.amount),{WD_OK} AND {dw}) net
          FROM money_transactions m INNER JOIN users u USING(casino_player_id)
          WHERE u.affiliate_code!='' AND {NRMg} GROUP BY code)
        SELECT aff.code, round(aff.net) net, ar.commission_rate_percent rate,
          round(greatest(aff.net,0)*ar.commission_rate_percent/100) comm
        FROM aff INNER JOIN affiliate_rates ar ON aff.code=ar.affiliate_code
        ORDER BY comm DESC LIMIT {lim}""")[1]
        atr = ''.join(f'<tr><td>{escape(str(c))}</td><td class=num>{mn(nt)}</td><td class=num>{rt}%</td>'
          f'<td class="num pos">{mn(cm)}</td></tr>' for c, nt, rt, cm in arows)
        body = (f'<div class=sec><h2>Воронка дохода <span class=muted>из чего складывается NGR за период</span></h2>'
          f'<div class=panel style="overflow-x:auto"><table><thead><tr><th>Статья</th><th>Сумма</th><th>% от GGR</th><th></th></tr></thead>'
          f'<tbody>{wf}</tbody></table></div></div>'
          f'<div class=sec><h2>Выплаты аффилиатам <span class=muted>комиссия по справочнику ставок</span></h2>'
          f'<div class=panel style="overflow-x:auto"><table><thead><tr><th>Аффилиат</th><th>Чистый депозит</th><th>Ставка</th><th>Комиссия</th></tr></thead>'
          f'<tbody>{atr or "<tr><td colspan=4 class=muted>нет данных по аффилиатам</td></tr>"}</tbody></table></div></div>')
    elif tab == 'reports':
        drows = q(f"""SELECT toString(toDate(toTimezone(created_at,'Europe/Istanbul'))) d,
          round(sumIf(bet_amount,{BET_T})) bet, round(sumIf(win_amount,{WIN_T})) win,
          round(sumIf(bet_amount,{BET_T})-sumIf(win_amount,{WIN_T})) ggr,
          uniqExactIf(casino_player_id,{BET_T}) active, countIf({BET_T}) rounds
          FROM game_transactions WHERE {gw} GROUP BY d ORDER BY d DESC LIMIT 100""")[1]
        dtr = ''.join(f'<tr><td>{escape(str(d))}</td><td class=num>{mn(b)}</td><td class=num>{mn(w)}</td>'
          f'<td class="num {"neg" if (g or 0)<0 else "pos"}">{mn(g)}</td><td class=num>{f(ac)}</td><td class=num>{f(rn)}</td></tr>'
          for d, b, w, g, ac, rn in drows)
        tb = sum(r[1] or 0 for r in drows); tw = sum(r[2] or 0 for r in drows)
        tg = sum(r[3] or 0 for r in drows); trn = sum(r[5] or 0 for r in drows)
        body = (f'<div class=sec><h2>Отчёт по дням <span class=muted>{escape(frm)} → {escape(to)}</span></h2>'
          f'<div class=panel style="overflow-x:auto"><table><thead><tr><th>Дата</th><th>Ставки</th><th>Выигрыши</th><th>GGR</th><th>Активных</th><th>Раундов</th></tr></thead>'
          f'<tbody>{dtr or "<tr><td colspan=6 class=muted>нет данных</td></tr>"}</tbody>'
          f'<tfoot><tr><td><b>Итого</b></td><td class=num><b>{mn(tb)}</b></td><td class=num><b>{mn(tw)}</b></td>'
          f'<td class="num {"neg" if tg<0 else "pos"}"><b>{mn(tg)}</b></td><td></td><td class=num><b>{f(trn)}</b></td></tr></tfoot>'
          f'</table></div></div>'
          f'<div class=sec><div class=lead>📋 Журнал выгрузок для колл-центра (списки сегментов в xlsx и результаты после передачи) — на отдельной странице <a href="/exports">Проверка выгрузок</a>.</div></div>')
    else:
        body = '<div class=sec><div class=lead>Таб в разработке.</div></div>'

    style = ("<style>"
      ".ggrfilt{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;background:var(--canvas);border:1px solid var(--hair);border-radius:12px;padding:14px 16px;margin:14px 0}"
      ".ggrfilt label{display:flex;flex-direction:column;gap:4px;font-size:11px;color:var(--steel);text-transform:uppercase;letter-spacing:.5px}"
      ".ggrfilt input,.ggrfilt select{height:38px;border:1px solid var(--hair3);border-radius:8px;padding:0 10px;font-size:13px;background:var(--canvas)}"
      ".ggrtabs{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid var(--hair2);margin:16px 0 4px}"
      ".ggrtabs a{padding:9px 14px;font-size:13px;color:var(--steel);border-bottom:2px solid transparent;text-decoration:none}"
      ".ggrtabs a.on{color:var(--primary);border-bottom-color:var(--primary);font-weight:600}"
      ".ggrgrid{display:grid;grid-template-columns:2fr 1fr;gap:16px}@media(max-width:900px){.ggrgrid{grid-template-columns:1fr}}"
      ".rsig{background:var(--cream);border:1px solid var(--beige);border-radius:10px;padding:12px 14px;margin-bottom:10px;font-size:13px}"
      ".badge{font-size:11px;padding:1px 6px;border-radius:999px;margin-left:4px}.badge.pos{background:#dcfce7;color:#15803d}.badge.neg{background:#fee2e2;color:#dc2626}"
      ".btn.ghost{background:transparent;color:var(--steel);border:1px solid var(--hair3)}"
      "</style>")
    top = ("<div class=topbar><div><div class=h1>GGR и доход — аналитика</div>"
      "<div class=lead>Провайдер · игра · аффилиат · расчёты — единый экран дохода</div></div>"
      f"<div class=pills><span class='pill live'>{escape(frm)} → {escape(to)}</span><span class=pill>{escape(prov or 'ВСЕ ПРОВАЙДЕРЫ')}</span></div></div>")
    content = top + kc + filt + kc2 + tabbar + body
    return layout('ggr', content, head_extra=ECHARTS + style)

# ============================ OVERVIEW ============================
@app.route('/overview')
def overview():
    dep, wd, mwd, bonus_cost, dep_manual = q(f"""SELECT
       round(sumIf(amount, {DEP_OK})),
       round(sumIf(abs(amount), {WD_OK})),
       round(sumIf(amount, type='manual_withdrawal' AND {SUCCESS})),
       round(sumIf(abs(amount), {BONUS_OK})),
       round(sumIf(amount, type='manual_deposit' AND {SUCCESS}))
       FROM money_transactions WHERE {NRM}""")[1][0]
    bets, wins, bonus_usage = q(f"""SELECT
       round(sumIf(bet_amount, {BET_T} AND {GSUCCESS})),
       round(sumIf(win_amount, {WIN_T} AND {GSUCCESS})),
       round(sumIf(bet_amount, {BET_T} AND {GSUCCESS} AND balance_source='bonus'))
       FROM game_transactions WHERE currency='TRY' AND {NRM}""")[1][0]
    players, new30 = q("""SELECT count(), countIf(reg_date >= '2026-05-06')
       FROM users WHERE account_type='normal'""")[1][0]
    played, depositors, active30, active7, vip = q("""SELECT countIf(ever_played), countIf(dep_count>0),
       countIf(recency_days<=30), countIf(recency_days<=7),
       countIf(dep_count>0 AND avg_bet>=200 AND recency_days BETWEEN 14 AND 90)
       FROM player_features WHERE account_type='normal'""")[1][0]
    dep_rej = q(f"SELECT round(sumIf(amount, type='deposit' AND status IN ('rejected','failed'))) FROM money_transactions WHERE {NRM}")[1][0][0]
    winners = q("SELECT countIf(net>0) FROM player_features WHERE account_type='normal'")[1][0][0]
    def mser(sql): return [r[1] for r in q(sql)[1]]
    dep_m = mser(f"SELECT toStartOfMonth(created_at) m, round(sumIf(amount, {DEP_OK})) FROM money_transactions WHERE {NRM} GROUP BY m ORDER BY m")
    wd_m  = mser(f"SELECT toStartOfMonth(created_at) m, round(sumIf(abs(amount), {WD_OK})) FROM money_transactions WHERE {NRM} GROUP BY m ORDER BY m")
    ggr_m = mser(f"SELECT toStartOfMonth(toTimezone(created_at,'Europe/Istanbul')) m, round(sumIf(bet_amount, {BET_T} AND {GSUCCESS})-sumIf(win_amount, {WIN_T} AND {GSUCCESS})) FROM game_transactions WHERE currency='TRY' AND {NRM} GROUP BY m ORDER BY m")
    mau_m = mser(f"SELECT toStartOfMonth(toTimezone(created_at,'Europe/Istanbul')) m, uniqExact(casino_player_id) FROM game_transactions WHERE {BET_T} AND {NRM} GROUP BY m ORDER BY m")
    dep, wd, mwd, bonus_cost, dep_manual, bets, wins, bonus_usage = (
        float(x or 0) for x in (dep, wd, mwd, bonus_cost, dep_manual, bets, wins, bonus_usage))
    ggr = bets - wins; net_cash = dep - wd
    rtp = round(wins/bets*100, 2) if bets else 0
    hold = round(ggr/bets*100, 2) if bets else 0
    margin = round(net_cash/dep*100, 1) if dep else 0
    bonus_ratio = round(bonus_cost/ggr*100, 1) if ggr else 0
    pcost = provider_cost_total(NRM)                    # по справочнику provider_rates (студия из dict_game_names)
    aff_comm = affiliate_commission_total()             # по справочнику affiliate_rates
    ngr = calc_ngr(ggr, bonus_cost, pcost, aff_comm)

    sp = (f'<div class=eyebrow>Игроки и активность</div><div class=cards>'
      + scard('', '👥', 'Всего игроков', f(players), 'real-игроки')
      + scard('', '🎮', 'Реально играли', f(played), f'{round(played/players*100) if players else 0}% от всех')
      + scard('', '💳', 'Депозиторов', f(depositors), f'{round(100*depositors/players,1) if players else 0}% платят')
      + scard('cream', '🔥', 'Активны 30 дней', f(active30), f'за 7 дней: {f(active7)}', spark(mau_m))
      + '</div>')
    sm = (f'<div class=eyebrow id=cash>Деньги (кэш) <span class=muted style="text-transform:none;letter-spacing:0">· Deposits − Withdrawals по успешным операциям</span></div><div class=cards>'
      + scard('', '💰', 'Deposits', mn(dep), 'SUM · type=deposit · успешные', spark(dep_m))
      + scard('', '💸', 'Withdrawals', mn(wd), 'SUM(ABS) · type=withdrawal', spark(wd_m))
      + scard('cream', '🎯', 'Net (кэш-нетто)', mn(net_cash), f'Deposits − Withdrawals · Margin {margin}%')
      + scard('cream', '🎁', 'Bonus cost', mn(bonus_cost), f'bonus/manual_bonus/freespin · ratio {bonus_ratio}%')
      + '</div>')
    sg = (f'<div class=eyebrow>Игра</div><div class=cards>'
      + scard('orange', '🎯', 'GGR', mn(ggr), f'Bet − Win · hold {hold}%', spark(ggr_m))
      + scard('', '📊', 'RTP', f'{rtp}%', 'Win / Bet × 100%')
      + scard('', '🎲', 'Bet (оборот)', mn(bets), 'сумма всех ставок')
      + scard('', '🏆', 'Win', mn(wins), 'сумма всех выигрышей')
      + '</div>')
    # DDL справочника dict_game_names теперь в schema.sql (паритет локали с продом);
    # пустой справочник = провайдеры не резолвятся → наполнить потоком v2.1 или ручным INSERT.
    _pnote = ('Σ по студиям × ставку (provider_rates)' if pcost else '⚠ справочник игр пуст — наполняется потоком v2.1 или ручным INSERT')
    sn = (f'<div class=eyebrow>NGR и издержки</div><div class=cards>'
      + scard('orange', '💠', 'NGR', mn(ngr), 'GGR − Bonus − Provider − Commission')
      + scard('', '🏭', 'Provider cost', mn(pcost), _pnote)
      + scard('', '🤝', 'Affiliate commission', mn(aff_comm), 'Σ max(net,0)×ставку (affiliate_rates)')
      + scard('', '🎮', 'Bonus usage', mn(bonus_usage), 'ставки с bonus-баланса')
      + '</div>')
    sr = (f'<div class=eyebrow id=risk>Бонус-списания и риск</div><div class=cards>'
      + scard('alert orange', '🧾', 'Бонус-списания', mn(mwd), 'отмена бонусов · не кэш')
      + scard('', '🚨', 'VIP под риском', f(vip), 'срочно удержать')
      + scard('', '⛔', 'Отклонено деп.', mn(dep_rej), 'платёжное трение')
      + scard('', '💵', 'Игроки в плюсе', f(winners), 'выиграли у казино')
      + '</div>')
    top = ("<div class=topbar><div><div class=h1>Обзор <em>· реал-тайм</em></div>"
      "<div class=lead>здоровье бизнеса в одном экране: депозиты, выводы, GGR, активность и риск · KPI только по реальным игрокам (тест/админ исключены) · дек 2025 → июнь 2026</div></div>"
      "<div class=pills><span class='pill live'>live ClickHouse</span><span class=pill>TRY</span></div></div>")
    return layout('overview', top + sp + sm + sg + sn + sr)

# ============================ PLAYERS LIST ============================
def _players_filter(args):
    """WHERE-условие списка игроков из query-параметров.
    Общее для страницы «Игроки» и экспорта сегментов — фильтры всегда 1:1."""
    qid = args.get('q','').strip()
    life = args.get('life',''); dep = args.get('dep','')
    at = args.get('at','normal'); at = at if at in ACCT_TYPES else 'normal'
    seg = args.get('seg','')
    game = ''.join(c for c in args.get('game','') if c.isalnum() or c=='_')[:24]
    where=[] if at=='all' else [f"account_type='{at}'"]; params={}
    aff = args.get('aff','').strip()[:64]
    # Исключение игроков конкретного аффилиата (запрос клиента): ad-hoc из UI
    # (?xaff=104,207) + постоянный список из env PLAYERS_EXCLUDE_AFFILIATES.
    # Коды санируем (alnum/_/-) — идут инлайном в NOT IN, не через биндинг.
    xaff = args.get('xaff','').strip()[:256]
    exp = args.get('exp','')            # '' все · 'no' не выгружались · 'yes' уже выгружены
    vip = args.get('vip','')            # '' все · '1'..'5' = vip_level >= N (правила казино)
    if qid.isdigit(): where=["casino_player_id={pid:UInt32}"]; params['pid']=int(qid)
    else:
        if seg in SEG_MAP: where.append(SEG_MAP[seg][5])
        if vip.isdigit() and 1 <= int(vip) <= 5: where.append(f"vip_level >= {int(vip)}")
        if game: where.append(f"casino_player_id IN (SELECT casino_player_id FROM player_games WHERE startsWith(game_uuid,'{game}'))")
        if aff: where.append("affiliate_code={aff:String}"); params['aff']=aff
        _xcodes = xaff.split(',') + os.getenv('PLAYERS_EXCLUDE_AFFILIATES','').split(',')
        _xcodes = [''.join(c for c in x.strip() if c.isalnum() or c in '_-')[:64] for x in _xcodes]
        _xcodes = list(dict.fromkeys(c for c in _xcodes if c))[:50]   # уникальные, непустые
        if _xcodes:
            where.append("affiliate_code NOT IN (" + ",".join("'"+c+"'" for c in _xcodes) + ")")
        if life in LIFE: where.append(f"lifecycle='{life}'")
        elif life=='churning': where.append("lifecycle IN ('at_risk','dormant','churned')")   # «уходящие» одним фильтром
        if dep=='yes': where.append("dep_count>0")
        elif dep=='no': where.append("dep_count=0")
        # уже передавали в кол-центр или ещё нет (журнал segment_exports)
        if exp=='no':  where.append("casino_player_id NOT IN (SELECT casino_player_id FROM segment_exports)")
        elif exp=='yes': where.append("casino_player_id IN (SELECT casino_player_id FROM segment_exports)")
    return (' AND '.join(where) or '1'), params, dict(q=qid, life=life, dep=dep, at=at, seg=seg, game=game, aff=aff, xaff=xaff, exp=exp, vip=vip)

@app.route('/')
def index():
    W, params, flt = _players_filter(request.args)
    qid, life, dep, at, seg, game, exp, vip = (flt['q'], flt['life'], flt['dep'], flt['at'],
                                          flt['seg'], flt['game'], flt['exp'], flt['vip'])
    sort = request.args.get('sort','turnover'); sort = sort if sort in SORTS else 'turnover'
    dr = 'ASC' if request.args.get('dir')=='asc' else 'DESC'
    page = max(0, int(request.args.get('p','0') or 0))
    total=q(f"SELECT count() FROM player_features WHERE {W}",params)[1][0][0]
    cols,rows=q(f"""SELECT casino_player_id,lifecycle,is_depositor,bets,turnover,net,recency_days,
       dep_count,dep_sum,bonus_sum,distinct_games,churned_30d,account_type,net_cash
       FROM player_features WHERE {W} ORDER BY {sort} {dr} NULLS LAST LIMIT 50 OFFSET {page*50}""",params)
    base=f"&life={life}&dep={dep}&at={at}&seg={seg}&game={game}&exp={exp}&vip={vip}"
    def sh(c,label):
        nd='asc' if (sort==c and dr=='DESC') else 'desc'
        arrow=' ▾' if (sort==c and dr=='DESC') else (' ▴' if sort==c else '')
        return f'<th><a href="?sort={c}&dir={nd}{base}&p=0">{label}{arrow}</a></th>'
    head=('<th>ID</th><th>Стадия</th>'+sh('bets','Ставок')+sh('turnover','Оборот')+sh('net','Net')
          +sh('recency_days','Recency')+sh('dep_count','Деп')+sh('dep_sum','Деп ₺')+sh('bonus_sum','Бонус ₺')
          +sh('distinct_games','Игр')+'<th title="нет ставок более 30 дней">Неактив 30д+</th>')
    # кого уже передавали в кол-центр (для пометки) — только по показанным игрокам
    expd = {}
    if rows:
        _idl = ','.join(str(int(r[0])) for r in rows)
        expd = {int(a): b for a, b in q(
            f"SELECT casino_player_id, formatDateTime(toTimezone(max(export_ts),'Europe/Istanbul'),'%d.%m.%Y') "
            f"FROM segment_exports WHERE casino_player_id IN ({_idl}) GROUP BY casino_player_id")[1]}
    trs=''
    for r in rows:
        (pid,lf,isd,bets,turn,net,rec,dc,ds,bs,dg,ch30,atp,ncash)=r
        netc='neg' if (net or 0)<0 else 'pos'
        eb = (f' <span class=badge style="background:#e0e7ff;color:#4338ca" title="уже передан в кол-центр">📤 {expd[pid]}</span>'
              if pid in expd else '')
        wm = (' <span title="обыгрывает казино: в плюсе по кассе и по игре — бонусы не рекомендуются" style="cursor:help">🎯</span>'
              if ((ncash or 0)<0 and (net or 0)>0) else '')
        trs+=(f'<tr onclick="location.href=\'/player/{pid}\'"><td class=id>{pid}{at_badge(atp)}{wm}{eb}</td><td>{life_badge(lf)}</td>'
          f'<td class=num>{f(bets)}</td><td class=num>{f(turn)}</td><td class="num {netc}">{f(net)}</td>'
          f"<td class=num>{'—' if rec is None else f(rec)+'д'}</td><td class=num>{f(dc)}</td>"
          f'<td class=num>{f(ds)}</td><td class=num>{f(bs)}</td><td class=num>{f(dg)}</td>'
          f"<td class=num>{'🔴' if ch30 else '·'}</td></tr>")
    pg=''
    if page>0: pg+=f'<a href="?q={qid}&sort={sort}&dir={dr.lower()}{base}&p={page-1}">← назад</a>'
    pg+=f'<span class=bd>{page*50+1}–{min((page+1)*50,total)} из {f(total)}</span>'
    if (page+1)*50<total: pg+=f'<a href="?q={qid}&sort={sort}&dir={dr.lower()}{base}&p={page+1}">вперёд →</a>'
    chips=''.join(f'<a class="chip {"on" if life==k else ""}" href="?life={k if life!=k else ""}&dep={dep}&at={at}&sort={sort}&dir={dr.lower()}">{v[2]}</a>' for k,v in LIFE.items())
    depc=''.join(f'<a class="chip {"on" if dep==k else ""}" href="?dep={k if dep!=k else ""}&life={life}&at={at}&exp={exp}&sort={sort}&dir={dr.lower()}">{lab}</a>' for k,lab in [('yes','депозиторы'),('no','без депо')])
    # выгружался ли игрок в кол-центр
    expc=''.join(f'<a class="chip {"on" if exp==k else ""}" href="?exp={k if exp!=k else ""}&life={life}&dep={dep}&at={at}&seg={seg}&sort={sort}&dir={dr.lower()}" title="{ttl}">{lab}</a>'
                 for k,lab,ttl in [('no','🆕 невыгруженные','ещё не передавались в кол-центр'),
                                   ('yes','📤 уже выгружены','есть в журнале выгрузок')])
    atc=''.join(f'<a class="chip {"on" if at==k else ""}" href="?at={k}&sort={sort}&dir={dr.lower()}">{lab}</a>' for k,lab in [('normal','обычные'),('service','🛡 служебные'),('test_or_service','🧪 тест'),('blocked','⛔ блок'),('all','все')])
    # VIP-уровень (правила казино) — фильтр «от уровня N и выше»
    vipc=''.join(f'<a class="chip {"on" if vip==k else ""}" href="?vip={k if vip!=k else ""}&life={life}&dep={dep}&at={at}&seg={seg}&exp={exp}&sort={sort}&dir={dr.lower()}" title="{ttl}">{lab}</a>'
                 for k,lab,ttl in [('1','🥈 Silver+','vip_level ≥ 1 · любой VIP (депозиты ≥100 TRY)'),('2','🥇 Gold+','≥ 50k TRY'),
                                   ('3','💠 Platinum+','≥ 150k TRY'),('4','💎 Diamond+','≥ 500k TRY'),('5','👑 Royal','≥ 1M TRY')])
    segbanner = ''
    if seg in SEG_MAP:
        s = SEG_MAP[seg]
        segbanner = (f'<div class=banner style="margin:0 0 14px;display:flex;justify-content:space-between;align-items:center;gap:12px">'
          f'<div>{s[1]} <b>Сегмент: {s[2]}</b> — {s[3]} · 💡 <b>оффер:</b> {s[4]}</div>'
          f'<a href="/" style="color:var(--steel);white-space:nowrap;text-decoration:none">✕ сбросить</a></div>')
    if game:
        segbanner += (f'<div class=banner style="margin:0 0 14px;display:flex;justify-content:space-between;align-items:center;gap:12px">'
          f'<div>🎮 <b>Игроки игры</b> {escape(game)} · 💡 <b>оффер:</b> фриспины на эту игру</div>'
          f'<a href="/" style="color:var(--steel);white-space:nowrap;text-decoration:none">✕ сбросить</a></div>')
    expq = f"q={qid}&life={life}&dep={dep}&at={at}&seg={seg}&game={game}&exp={exp}&vip={vip}"   # фильтры для ссылок экспорта
    content=(f'<div class=topbar><div><div class=h1>Игроки <em class=bd>· {f(total)}</em></div>'
      f'<div class=lead>вся база игроков с фильтрами (стадия, депозиторы) и поиском по ID · клик по строке — полная карточка игрока · 🛡 служебные/админ помечены значком</div></div></div>'
      f'{segbanner}'
      f'<form class=bar method=get><input name=q placeholder="поиск по ID" value="{escape(qid)}" style="width:170px">'
      f'<input type=hidden name=at value="{at}"><button class=btn>Найти</button>'
      f'<span class=muted style="margin-left:6px">тип:</span>{atc}</form>'
      f'<div class=bar style="margin-top:-4px"><span class=muted>стадия:</span>{chips}{depc}'
      f'<span class=muted style="margin-left:10px">VIP:</span>{vipc}'
      f'<span class=muted style="margin-left:10px">кол-центр:</span>{expc}'
      f'<span style="margin-left:auto;display:flex;gap:6px;align-items:center"><span class=muted title="скачать весь текущий сегмент ({f(total)} игроков), не только страницу">выгрузить сегмент:</span>'
      f'<a class=chip href="/players.csv?{expq}">⬇ CSV</a><a class=chip href="/players.xlsx?{expq}">⬇ Excel</a></span></div>'
      f'<div class=panel style="overflow-x:auto"><table><thead><tr>{head}</tr></thead><tbody>{trs}</tbody></table></div>'
      f'<div class=pager>{pg}</div>')
    return layout('players', content)

# ============================ ЭКСПОРТ СЕГМЕНТОВ (CSV / XLSX) ============================
_EXPORT_COLS = ['casino_player_id', 'стадия', 'recency_дней', 'ставок', 'оборот', 'net',
                'деп_кол-во', 'деп_сумма', 'бонус_сумма',
                'LTV_прогноз_90д', 'риск_оттока_%', 'реком_действие', 'реком_бонус', 'условия_бонуса',
                # VIP-скоры (инхаус vip-intelligence): пусто = не в сегменте модели
                'VIP_риск_%', 'VIP_потенциал_%', 'VIP_рост_%']

def _export_rows(W, params):
    """Все игроки текущего сегмента + прогнозы моделей (без пагинации).
    Колонка «реком_бонус» — реальная акция из каталога, а не фраза из marts.sql."""
    raw = q(f"""SELECT pf.casino_player_id, pf.lifecycle, pf.recency_days, pf.bets,
        toInt64(round(pf.turnover)), toInt64(round(pf.net)), pf.dep_count,
        toInt64(round(pf.dep_sum)), toInt64(round(pf.bonus_sum)),
        toInt64(round(coalesce(pa.pred_ltv_d90, 0))),
        if(pa.p_churn IS NULL, '', toString(round(pa.p_churn*100))),
        coalesce(pa.action, ''), coalesce(pa.early_tier, ''), pa.p_churn, toInt64(round(pf.net_cash)),
        if(vc.casino_player_id = 0, '', toString(round(vc.p_vip_churn*100))),
        if(ev.casino_player_id = 0, '', toString(round(ev.p_early_vip*100))),
        if(np.casino_player_id = 0, '', toString(round((1 - np.p_non_promising)*100)))
      FROM player_features pf
      LEFT JOIN player_actions pa USING (casino_player_id)
      LEFT JOIN player_vip_churn_ml vc ON vc.casino_player_id = pf.casino_player_id
      LEFT JOIN player_early_vip_ml ev ON ev.casino_player_id = pf.casino_player_id
      LEFT JOIN player_non_promising_vip_ml np ON np.casino_player_id = pf.casino_player_id
      WHERE {W} ORDER BY pf.turnover DESC""", params)[1]
    out = []
    for r in raw:
        (pid, life, rec, bets, turn, net, dc, ds, bs, ltv, churn_pct, action, tier, pch,
         net_cash, vip_risk, vip_early, vip_growth) = r
        name, terms, _ = offer_for({'lifecycle': life, 'dep_count': dc, 'early_tier': tier,
                                    'pred_ltv_d90': ltv, 'p_churn': pch, 'net': net, 'net_cash': net_cash})
        out.append((pid, life, rec, bets, turn, net, dc, ds, bs, ltv, churn_pct, action, name, terms,
                    vip_risk, vip_early, vip_growth))
    return out

def _export_log(flt, fmt, n):
    try:
        c = _client()
        c.command("""CREATE TABLE IF NOT EXISTS retention.export_log
            (ts DateTime64(3) DEFAULT now64(3), filter String,
             format LowCardinality(String), rows UInt32)
            ENGINE = MergeTree ORDER BY ts""")
        c.insert('export_log', [[json.dumps(flt, ensure_ascii=False), fmt, n]],
                 column_names=['filter', 'format', 'rows'])
    except Exception:
        pass   # аудит не должен ломать выгрузку

def _export_name(flt, ext):
    parts = [p for p in (flt.get('aff',''),
                         flt['life'] or flt['seg'] or ('depositors' if flt['dep'] == 'yes' else ''),
                         {'no': 'new', 'yes': 'exported'}.get(flt.get('exp', ''), '')) if p]
    return f"players_{'_'.join(parts) or 'all'}_{data_asof()}.{ext}"

@app.route('/players.csv')
def players_csv():
    W, params, flt = _players_filter(request.args)
    rows = _export_rows(W, params)
    _export_log(flt, 'csv', len(rows))
    out = ['﻿' + ';'.join(_EXPORT_COLS)]   # BOM — Excel открывает UTF-8 без кракозябр
    for r in rows:
        out.append(';'.join('' if v is None else str(v) for v in r))
    return Response('\r\n'.join(out), mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{_export_name(flt, "csv")}"'})

@app.route('/players.xlsx')
def players_xlsx():
    import io
    from openpyxl import Workbook
    W, params, flt = _players_filter(request.args)
    rows = _export_rows(W, params)
    _export_log(flt, 'xlsx', len(rows))
    wb = Workbook(); ws = wb.active; ws.title = 'players'
    ws.append(_EXPORT_COLS)
    for r in rows:
        ws.append(list(r))
    ws.freeze_panes = 'A2'
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return Response(buf.read(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{_export_name(flt, "xlsx")}"'})

# ============================ PLAYER DETAIL ============================
ECHARTS = "<script src='https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js'></script>"
DOW_RU = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']

def _rhythm(where, params):
    base = f"FROM game_transactions WHERE {where}"
    dow  = q(f"SELECT toDayOfWeek(toTimezone(created_at,'Europe/Istanbul')) d, count() {base} GROUP BY d", params)[1]
    hour = q(f"SELECT toHour(toTimezone(created_at,'Europe/Istanbul')) h, count() {base} GROUP BY h", params)[1]
    hm   = q(f"SELECT toDayOfWeek(toTimezone(created_at,'Europe/Istanbul')) d, toHour(toTimezone(created_at,'Europe/Istanbul')) h, count() {base} GROUP BY d,h", params)[1]
    dts  = q(f"SELECT toDate(toTimezone(created_at,'Europe/Istanbul')) dt {base} GROUP BY dt ORDER BY dt", params)[1]
    dow_a = [0]*7
    for d, c in dow: dow_a[int(d)-1] = c
    hour_a = [0]*24
    for h, c in hour: hour_a[int(h)] = c
    hm_a = [[int(h), int(d)-1, c] for d, h, c in hm]
    ds = [x[0] for x in dts]
    gaps = [(ds[i]-ds[i-1]).days for i in range(1, len(ds))]
    med_gap = round(statistics.median(gaps)) if gaps else 0
    longest = cur = (1 if ds else 0)
    for i in range(1, len(ds)):
        if (ds[i]-ds[i-1]).days == 1: cur += 1; longest = max(longest, cur)
        else: cur = 1
    tot = sum(dow_a)
    st = {'active_days': len(ds), 'med_gap': med_gap, 'longest': longest,
          'bpd': round(tot/len(ds)) if ds else 0,
          'peak_day': DOW_RU[dow_a.index(max(dow_a))] if tot else '—',
          'peak_hour': hour_a.index(max(hour_a)) if tot else 0}
    return {'dow': dow_a, 'hour': hour_a, 'hm': hm_a}, st

def rhythm_html(data, st):
    kc = lambda l, v: f'<div class=scard style="min-height:auto"><div class=l>{l}</div><div class=v style="font-size:24px">{v}</div></div>'
    cards = (kc('Активных дней', f(st['active_days'])) + kc('Любимый день', st['peak_day'])
      + kc('Любимый час', f"{st['peak_hour']}:00") + kc('Обычный интервал', f"~{st['med_gap']} дн")
      + kc('Макс серия подряд', f"{st['longest']} дн") + kc('Ставок в день', f(st['bpd'])))
    body = (f'<div class="cards blurcards" style="grid-template-columns:repeat(6,1fr)">{cards}</div>'
      '<div class=chgrid style="margin-top:14px">'
      '<div class=chartbox><h3>По дням недели</h3><div class=cap>когда чаще ставит</div><div class=chart id=c_dow style="height:210px"></div></div>'
      '<div class=chartbox><h3>По часам суток (Стамбул)</h3><div class=cap>в какое время</div><div class=chart id=c_hour style="height:210px"></div></div></div>'
      '<div class=chartbox style="margin-top:14px"><h3>Тепловая карта: день недели × час</h3><div class=cap>где темнее — больше ставок</div><div class=chart id=c_hm style="height:230px"></div></div>')
    js = "<script>window.RD=" + jsdump(data) + ";" + RHYTHM_JS + "</script>"
    return body, js

RHYTHM_JS = """
const RD=window.RD,OR='#2563eb',ST='#64748b',HA='#e5e7eb',INK='#1e293b';
const DOW=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'],H24=[...Array(24).keys()];
const tip={backgroundColor:'#fff',borderColor:HA,textStyle:{color:INK},confine:true};
const ax=e=>Object.assign({axisLine:{lineStyle:{color:HA}},axisTick:{show:false},splitLine:{lineStyle:{color:HA}},axisLabel:{color:ST}},e||{});
echarts.init(document.getElementById('c_dow')).setOption({grid:{left:6,right:12,top:14,bottom:6,containLabel:true},tooltip:Object.assign({trigger:'axis'},tip),
 xAxis:ax({type:'category',data:DOW}),yAxis:ax({type:'value'}),series:[{type:'bar',data:RD.dow,barWidth:'56%',itemStyle:{color:OR,borderRadius:[4,4,0,0]}}]});
echarts.init(document.getElementById('c_hour')).setOption({grid:{left:6,right:12,top:14,bottom:6,containLabel:true},tooltip:Object.assign({trigger:'axis'},tip),
 xAxis:ax({type:'category',data:H24,boundaryGap:false,axisLabel:{color:ST,interval:2,formatter:v=>v+'h'}}),yAxis:ax({type:'value'}),
 series:[{type:'line',data:RD.hour,smooth:true,symbol:'none',lineStyle:{color:OR,width:2.5},areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:'rgba(37,99,235,.25)'},{offset:1,color:'rgba(37,99,235,0)'}])}}]});
echarts.init(document.getElementById('c_hm')).setOption({grid:{left:6,right:14,top:10,bottom:24,containLabel:true},tooltip:Object.assign({position:'top'},tip),
 xAxis:{type:'category',data:H24,axisLine:{show:false},axisTick:{show:false},axisLabel:{color:ST,interval:2,formatter:v=>v+'h'}},
 yAxis:{type:'category',data:DOW,axisLine:{show:false},axisTick:{show:false},axisLabel:{color:ST}},
 visualMap:{min:0,max:Math.max(1,...RD.hm.map(x=>x[2])),show:false,inRange:{color:['#eff6ff','#bfdbfe','#60a5fa','#2563eb','#1e3a8a']}},
 series:[{type:'heatmap',data:RD.hm,itemStyle:{borderColor:'#fff',borderWidth:1.5}}]});
"""

# Пояснения для всплывающих подсказок (title на ховер): что · формула · смысл.
CARD_TIP = {
    # профиль
    'account_type':'Тип аккаунта. normal = реальный игрок; test_or_service / service / blocked — не реальные (в моделях исключаются).',
    'status':'Статус аккаунта из источника.',
    'country':'Страна (оценка по country_iso_estimated).',
    'reg_date':'Дата регистрации.',
    'tenure_days':'Возраст аккаунта = дней с регистрации.',
    'affiliate_type':'Тип аффилиат-аккаунта (classic и т.п.).',
    'ftd_amount':'Сумма первого депозита (FTD).',
    'balance':'Баланс — снимок на момент выгрузки (не live).',
    'bonus_balance':'Бонусный баланс — снимок на момент выгрузки.',
    'activity_status':'Статус активности из источника.',
    # деньги
    'dep_count':'Число завершённых депозитов (deposit + manual_deposit, status=completed).',
    'dep_sum':'Депозиты ВКЛ. ручные (manual=бонус) — поведенческое поле для моделей. Реальный кэш → «внёс (кэш)».',
    'cash_deposits':'Кэш-депозиты (спека казино): Σ по type=deposit, успешные. БЕЗ manual_deposit. Сверяемо с бордом.',
    'withdrawals_abs':'Выводы (спека): Σ ABS(amount) по type=withdrawal, успешные. БЕЗ manual_withdrawal.',
    'net_cash':'Касса-нетто = кэш-депозиты − выводы (спека казино).',
    'bonus_cost':'Bonus cost = Σ ABS(amount) по bonus/manual_bonus/freespin (успешные, без bonus_conversion).',
    'dep_failed':'Число неуспешных депозитов (rejected / failed).',
    'wd_count':'Число завершённых выводов.',
    'wd_sum':'Сумма завершённых выводов = Σ amount.',
    'wd_rejected':'Число отклонённых выводов.',
    'bonus_count':'Число бонусных начислений.',
    'bonus_sum':'Сумма выданных бонусов.',
    'primary_payment_method':'Основная платёжка (без campaign-тегов).',
    'deposit_recency_days':'Дней с последнего депозита.',
    # игра
    'bets':'Число ставок (bet + freespins_bet).',
    'turnover':'Оборот = Σ bet_amount. Сколько игрок поставил всего.',
    'wins_sum':'Выигрыши = Σ win_amount. Сколько игрок выиграл в игре.',
    'net':'Net игрока = выигрыши − ставки. + в плюсе / − слил (со стороны ИГРОКА).',
    'ggr':'GGR казино = ставки − выигрыши = −net. Доход казино от игры (до вычета бонусов).',
    'avg_bet':'Средняя ставка = avg(bet_amount).',
    'max_bet':'Максимальная ставка.',
    'distinct_games':'Сколько разных игр = uniqExact(game_uuid).',
    'active_days':'Дней с игрой = uniqExact(дата ставки).',
    'recency_days':'Дней с последней ставки = dateDiff(последняя ставка, сегодня).',
    'primary_provider':'Основной провайдер (агрегатор) по числу ставок.',
    'freespin_ratio':'Доля фриспин-ставок = freespins_bets / bets.',
    'night_share':'Доля ночной игры (час < 6 по Стамбулу) = night_bets / bets.',
    'bets_per_active_day':'Интенсивность = ставки / активные дни.',
    'activation_lag_days':'Скорость активации = дней между регистрацией и первой ставкой.',
    # паттерн
    'favourite_game':'Игра с наибольшим числом ставок (основная).',
    'favourite_game_bets':'Сколько ставок в основной игре.',
    'game_concentration':'Концентрация = доля ставок в основной игре.',
    'stuck_game':'Игра, к которой игрок дольше всего возвращался.',
    'stuck_game_days':'Дней до возврата в эту игру.',
    'oneshot_games':'Сколько игр брошено после одного дня.',
}
SCARD_TIP = {
    'Ставок':'Число ставок (bet + freespins_bet).',
    'Оборот ₺':'Оборот = Σ ставок.',
    'Net ₺':'Net игрока = выигрыши − ставки. − = слил (взгляд игрока).',
    'GGR ₺':'GGR казино = ставки − выигрыши = −net. Доход казино от игры (до бонусов).',
    'Депозитов':'Число завершённых депозитов.',
    'Recency':'Дней с последней ставки.',
    'Тир':'Тир по депозиту 1-й недели: A<1k · B<3k · C<10k · D≥10k.',
    'Депозит 1-й нед ₺':'Σ депозитов в первые 7 дней от FTD (фича LTV-модели).',
    'Прогноз D90 ₺':'ML-прогноз суммы депозитов к 90-му дню по поведению 1-й недели.',
    'Диапазон D90 (P10–P90)':'Квантильный прогноз: P10–P90 — честный разброс (киты).',
    'Ещё ожидаем ₺':'Headroom = max(0, прогноз D90 − уже внесено). 0 = прогноз уже превышен.',
    'Сейчас':'Текущая ступень = номер последнего депозита.',
    'P(след. деп) · персон.':'Персональный P(следующий депозит в 30 дн), ML (любая ступень).',
    'по базе на ступени':'Средняя конверсия этой ступени по всей базе. Считается только до #10 (дальше «—»).',
    'Цель':'Следующая ступень = депозит #(N+1).',
}


@app.route('/player/<int:pid>')
def player(pid):
    cols,rows=q("SELECT * FROM player_features WHERE casino_player_id={pid:UInt32}",{'pid':pid})
    if not rows: abort(404)
    d=dict(zip(cols,rows[0]))
    d['ggr']=-(d.get('net') or 0)   # GGR казино = −net игрока (ставки − выигрыши)
    _,jr=q(f"""SELECT toDate(first_played) d, game_uuid, provider, bets, days_played, {GN()} gname
           FROM player_games WHERE casino_player_id={{pid:UInt32}} ORDER BY first_played LIMIT 60""",{'pid':pid})
    maxb=max([x[3] for x in jr], default=1); fav=str(d.get('favourite_game') or '')
    # «основная игра» / «дольше возвращался» в профиле — тоже показываем названием, не хешем
    gmap = {str(r[1]): str(r[5]) for r in jr}
    for _k in ('favourite_game', 'stuck_game'):
        _u = str(d.get(_k) or '')
        if _u and _u in gmap: d[_k] = gmap[_u]
    def fld(k,label,cur=False):
        v=d.get(k)
        if v is None: v='—'
        elif isinstance(v,(int,float)) and not isinstance(v,bool):
            if cur: v=f(v)+' ₺'
            elif isinstance(v,float) and 0<abs(v)<1: v=f'{v:.3f}'.rstrip('0').rstrip('.')
            else: v=f(v)
        full=str(v)
        if full in ('true','True'): full='да'
        elif full in ('false','False'): full='нет'
        disp=full if len(full)<=22 else full[:20]+'…'
        tip=CARD_TIP.get(k)
        attr=f' data-tip="{escape(tip)}"' if tip else f' title="{escape(full)}"'
        return f'<div class=fld{attr}><span class=k>{escape(label)}</span><span class=v>{escape(disp)}</span></div>'
    VIPLBL={0:'⚪ Regular',1:'🥈 Silver',2:'🥇 Gold',3:'💠 Platinum',4:'💎 Diamond',5:'👑 Royal'}
    _vl=int(d.get('vip_level') or 0)
    _viptip=('VIP-уровень (правила казино) по накопительным успешным депозитам в TRY: '
             'Regular <100, Silver ≥100, Gold ≥50k, Platinum ≥150k, Diamond ≥500k, Royal ≥1M. '
             'Для уровня ≥ Silver нужен хотя бы один депозит ≥ 100 TRY.')
    vip_fld=f'<div class=fld data-tip="{escape(_viptip)}"><span class=k>VIP-уровень</span><span class=v>{VIPLBL.get(_vl,_vl)}</span></div>'
    profile=vip_fld+''.join([fld('account_type','тип'),fld('status','статус'),fld('country','страна'),fld('reg_date','регистрация'),
       fld('tenure_days','возраст, дн'),fld('affiliate_type','аффилиат'),
       f'<div class=fld><span class=k>депозитор</span><span class=v>{"да" if (d.get("dep_count") or 0)>0 else "нет"}</span></div>',
       fld('ftd_amount','первый деп',True),fld('phone_verified','phone✓'),fld('email_verified','email✓'),
       fld('balance','баланс (снимок)',True),fld('bonus_balance','бонус (снимок)',True),fld('activity_status','activity_status')])
    money=''.join([fld('dep_count','депозитов'),
       fld('cash_deposits','внёс (кэш)',True),fld('withdrawals_abs','вывел (кэш)',True),
       fld('net_cash','касса-нетто',True),fld('bonus_cost','bonus cost',True),
       fld('dep_sum','внёс (с ручными)',True),fld('dep_failed','отказов деп'),
       fld('wd_count','выводов'),fld('wd_rejected','отказов выв'),
       fld('bonus_count','бонусов'),fld('bonus_sum','бонусов на',True),fld('primary_payment_method','платёжка'),
       fld('deposit_recency_days','деп recency, дн')])
    game=''.join([fld('bets','ставок'),fld('turnover','оборот',True),fld('wins_sum','выиграл',True),fld('net','net',True),fld('ggr','GGR',True),
       fld('avg_bet','ср.ставка',True),fld('max_bet','макс.ставка',True),fld('distinct_games','разных игр'),
       fld('active_days','активных дней'),fld('recency_days','recency, дн'),fld('primary_provider','провайдер'),
       fld('freespin_ratio','доля фриспинов'),fld('night_share','доля ночью'),fld('bets_per_active_day','ставок/день'),
       fld('activation_lag_days','активация, дн')])
    patt=''.join([fld('favourite_game','основная игра'),fld('favourite_game_bets','ставок в ней'),fld('game_concentration','концентрация'),
       fld('stuck_game','🔁 дольше возвращался'),fld('stuck_game_days','дней возврата'),fld('oneshot_games','бросил после 1 дня')])
    def jrow_html(dt, g, prov, b, dys, gname, extra='', star=''):
        return (f'<div class="jrow{extra}" onclick="location.href=\'/player/{pid}/game/{escape(str(g))}\'" style="cursor:pointer" title="детали по этой игре">'
          f'<i style="width:{round(b/maxb*100)}%"></i><span class=d>{star}{dt}</span>'
          f'<span class=g title="{escape(str(gname))}">{escape(str(gname)[:22])}</span><span class=muted>{escape(str(prov or ""))}</span>'
          f'<span class=n>{f(b)} ст</span><span class=n>{f(dys)} дн</span></div>')
    fav_row = next((r for r in jr if str(r[1]) == fav), None)
    pinned = jrow_html(*fav_row, extra=' stuck', star='★ ') if fav_row else ''
    jrows = ''.join(jrow_html(*r) for r in jr)
    rd, rst = _rhythm("casino_player_id={pid:UInt32} AND transaction_type IN ('bet','freespins_bet')", {'pid': pid})
    rbody, rjs = rhythm_html(rd, rst)
    net=d.get('net') or 0
    def kc(l,v,cls=''):
        tip=SCARD_TIP.get(l)
        ta=f' data-tip="{escape(tip)}"' if tip else ''
        return f'<div class=scard{ta}><div class=l>{l}</div><div class="v sm {cls}" style="font-size:26px">{v}</div></div>'
    lv=q("SELECT days_since_ftd,tier_provisional,early_tier,dep_d7,pred_ltv_d30,pred_ltv_d90,pred_ltv_d120,ltv_headroom,ltv_is_ml "
         "FROM player_ltv WHERE casino_player_id={pid:UInt32}",{'pid':pid})[1]
    if lv:
        ds,prov,tier,d7,p30,p90,p120,head,isml=lv[0]
        provn=' <span class=muted>(провизорно, &lt;7 дн с депозита)</span>' if prov else ''
        modn=('прогноз D90 — <b>********</b> (по поведению 1-й недели)' if isml
              else 'прогноз — лукап по тиру (v0)')
        qn=q("SELECT round(ltv_p10),round(ltv_p50),round(ltv_p90) FROM player_ltv_quantiles WHERE casino_player_id={pid:UInt32}",{'pid':pid})[1]
        rng_card=''
        if qn:
            q10,q50,q90=qn[0]
            rng_card=kc('Диапазон D90 (P10–P90)',f'<span style="font-size:16px">{f(q10)}–{f(q90)} ₺</span>')
        ltv_sec=(f'<div class=sec><h2>💎 LTV-прогноз <span class=muted>ожидаемая ценность по депозитам (D90)</span></h2>'
          f'<div class=kgrid>{kc("Тир",tier_badge(tier))}{kc("Депозит 1-й нед ₺",f(d7))}'
          f'{kc("Прогноз D90 ₺",f(p90),"pos")}{rng_card}{kc("Ещё ожидаем ₺",f(head))}</div>'
          f'<div class=lead style="margin-top:6px">Прошло {f(ds)} дн с первого депозита{provn} · {modn} · '
          f'диапазон — квантильная модель (P10/P90), честно про разброс</div></div>')
    else:
        ltv_sec=('<div class=sec><h2>💎 LTV-прогноз</h2>'
          '<div class=lead>Игрок не вносил депозит → депозитный LTV не прогнозируется. '
          'Здесь релевантна другая модель — «сделает ли первый депозит».</div></div>')
    # --- реконструкция сессий (длительность + выиграл/проиграл) ---
    sess=q("SELECT any(" + GN('game_uuid') + "), min(toTimezone(created_at,'Europe/Istanbul')),"
       """ round(dateDiff('second', min(created_at), max(created_at))/60),
       countIf(transaction_type IN ('bet','freespins_bet')),
       round(sumIf(bet_amount,transaction_type IN ('bet','freespins_bet'))),
       round(sumIf(win_amount,transaction_type IN ('win','freespins_win')))
       FROM game_transactions WHERE casino_player_id={pid:UInt32} AND session_id!=''
       GROUP BY session_id HAVING countIf(transaction_type IN ('bet','freespins_bet'))>0
       ORDER BY min(created_at) DESC LIMIT 40""",{'pid':pid})[1]
    srows=[dict(g=g,st=st,dur=float(dur or 0),sp=sp,bet=float(bet or 0),win=float(win or 0),
                net=float(win or 0)-float(bet or 0))
           for g,st,dur,sp,bet,win in sess]
    # моментум (последняя форма)
    recent_net=0.0; streak=0
    if srows:
        top=srows[0]['st']
        recent_net=sum(s['net'] for s in srows if (top-s['st']).days<=14)
        for s in srows:
            if s['net']<0: streak+=1
            else: break
    ab=float(d.get('avg_bet') or 0)
    if ab != ab: ab=0.0                    # avg_bet может быть NaN (нет completed-ставок) → иначе Decimal<NaN падает
    if not srows:                          ctx=''
    elif streak>=3 or recent_net < -ab*20: ctx='🔻 <b>В минусе</b> (серия проигрышей / отрицательный недавний net) → <b>сейчас</b> уместен кэшбэк / бонус на проигрыш, пока не ушёл от фрустрации.'
    elif recent_net > ab*20:               ctx='🔺 <b>На подъёме</b> (недавно в плюсе) → нудж к депозиту на волне выигрыша или фриспины в любимой игре.'
    else:                                  ctx='➖ Ровная динамика — действуем по основному офферу.'
    # лог сессий (последние 15)
    if srows:
        slog=''
        for s in srows[:15]:
            res='🟢' if s['net']>=0 else '🔴'; netc='pos' if s['net']>=0 else 'neg'
            slog+=(f'<tr><td class=muted>{s["st"].strftime("%d.%m %H:%M")}</td><td title="{escape(str(s["g"]))}">{escape(str(s["g"])[:22])}</td>'
                   f'<td class=num>{s["dur"]}м</td><td class=num>{f(s["sp"])}</td>'
                   f'<td class=num>{f(s["bet"])}</td><td class=num>{f(s["win"])}</td>'
                   f'<td class="num {netc}">{f(s["net"])}</td><td>{res}</td></tr>')
        sess_sec=(f'<details class="sec coll"><summary>🕐 Лог сессий ({len(srows)}) <span class=muted>каждая сессия: длительность, спины, выиграл/проиграл</span></summary>'
          '<div class=panel style="overflow-x:auto"><table><thead><tr><th>Когда</th><th>Игра</th><th>Длит.</th>'
          '<th>Спинов</th><th>Ставка ₺</th><th>Выигрыш ₺</th><th>Net ₺</th><th>Итог</th></tr></thead><tbody>'
          +slog+'</tbody></table></div></details>')
    else:
        sess_sec=''
    # лог депозитов: когда вносил, сколько и как (способ/комментарий, тип, статус)
    drows=q("SELECT formatDateTime(toTimezone(created_at,'Europe/Istanbul'),'%d.%m.%y %H:%i') ts, "
            "round(toFloat64(amount),2) amt, "
            "if(payment_method!='' AND payment_method NOT LIKE 'campaign:%', payment_method, description) how, "
            "type, status "
            "FROM money_transactions WHERE casino_player_id={pid:UInt32} "
            "AND type IN ('deposit','manual_deposit') ORDER BY created_at DESC LIMIT 30",{'pid':pid})[1]
    if drows:
        dlog=''
        for ts,amt,how,typ,st in drows:
            stc='pos' if st=='completed' else 'neg'
            tlabel='ручной/бонус' if typ=='manual_deposit' else 'депозит'
            dlog+=(f'<tr><td class=muted>{escape(str(ts))}</td><td class="num">{f(amt)}</td>'
                   f'<td>{escape(str(how or "—"))[:28]}</td><td class=muted>{tlabel}</td>'
                   f'<td class="{stc}">{escape(str(st))}</td></tr>')
        dep_sec=(f'<details class="sec coll"><summary>💳 Депозиты ({len(drows)}) <span class=muted>когда вносил, сколько и как (ручной = бонус, не кэш)</span></summary>'
          '<div class=panel style="overflow-x:auto"><table><thead><tr><th>Когда</th><th>Сумма ₺</th>'
          '<th>Способ / комментарий</th><th>Тип</th><th>Статус</th></tr></thead><tbody>'
          +dlog+'</tbody></table></div></details>')
    else:
        dep_sec='<div class=sec><h2>💳 Депозиты</h2><div class=lead>Депозитов нет.</div></div>'
    # прогресс по депозитам (лестница)
    dc=int(d.get('dep_count') or 0)
    if dc>=1:
        lad=q("SELECT deposit_no, conv_to_next_pct FROM deposit_ladder ORDER BY deposit_no")[1]
        cm={no:cv for no,cv in lad}
        pnext=cm.get(dc) if dc<=10 else None
        pn=q("SELECT round(p_next_deposit*100) FROM player_next_deposit_ml WHERE casino_player_id={pid:UInt32}",{'pid':pid})[1]
        ppers=int(pn[0][0]) if pn else None
        lstr=' · '.join(f'{("["+str(no)+"]") if no==dc else no}→{cv}%' for no,cv in lad)
        prog_sec=(f'<div class=sec><h2>🪜 Прогресс по депозитам <span class=muted>где он на лестнице и шанс дойти дальше</span></h2>'
          f'<div class=kgrid>{kc("Сейчас","деп #"+str(dc))}'
          f'{kc("P(след. деп) · персон.",(str(ppers)+"%") if ppers is not None else "—","pos")}'
          f'{kc("по базе на ступени",(str(pnext)+"%") if pnext is not None else "—")}'
          f'{kc("Цель","деп #"+str(dc+1))}</div>'
          f'<div class=lead style="margin-top:6px">персональный прогноз — ******** (AUC 0.90) · конверсия по базе: {lstr}<br>что нужно: довести до депозита #{dc+1} — см. оффер выше</div></div>')
    else:
        prog_sec=''
    # --- бонусы и их эффект (дал бонус -> что было после) ---
    bon=q("SELECT created_at, multiIf(type='freespin','freespins', description ILIKE '%deneme%','no-deposit', "
          "description ILIKE '%kay%p%','cashback', description ILIKE '%dsc%' OR description ILIKE '%yat%','deposit-match','other'), "
          "round(toFloat64(amount)) FROM money_transactions WHERE casino_player_id={pid:UInt32} "
          "AND type IN ('freespin','manual_bonus','bonus') AND status='completed' ORDER BY created_at DESC LIMIT 12",{'pid':pid})[1]
    if bon:
        deps=[r[0] for r in q("SELECT created_at FROM money_transactions WHERE casino_player_id={pid:UInt32} "
              "AND type IN ('deposit','manual_deposit') AND status='completed'",{'pid':pid})[1]]
        pdays=[r[0] for r in q("SELECT DISTINCT toDate(created_at) FROM game_transactions WHERE casino_player_id={pid:UInt32} "
               "AND transaction_type IN ('bet','freespins_bet')",{'pid':pid})[1]]
        brows=''
        for bts,bt,amt in bon:
            dep_ok=any(bts<dd and (dd-bts).days<=14 for dd in deps)
            play_ok=any(bts.date()<pdd and (pdd-bts.date()).days<=7 for pdd in pdays)
            mark='🟢 депозит' if dep_ok else ('🟡 играл' if play_ok else '⚪ без реакции')
            brows+=f'<tr><td class=muted>{bts.strftime("%d.%m.%y")}</td><td>{escape(str(bt))}</td><td class=num>{f(amt)}</td><td>{mark}</td></tr>'
        bonus_sec=('<div class=sec><h2>🎁 Бонусы и эффект <span class=muted>дал бонус → реакция в 14 дней</span></h2>'
          '<div class=panel style="overflow-x:auto"><table><thead><tr><th>Когда</th><th>Тип</th><th>Сумма ₺</th><th>Реакция</th></tr></thead><tbody>'
          +brows+'</tbody></table></div>'
          '<div class=lead style="margin-top:6px">🟢 внёс депозит · 🟡 играл без депозита · ⚪ без реакции · наблюдательно (не causal)</div></div>')
    else:
        bonus_sec=''
    av=q("SELECT action,bonus,when_to,p_2nd_deposit,p_churn,lifecycle,dep_count,early_tier,pred_ltv_d90 "
         "FROM player_actions WHERE casino_player_id={pid:UInt32}",{'pid':pid})[1]
    if av:
        a_,bonus_,when_,p2_,pch_,life_,dc_,tier_,ltv_=av[0]
        # оффер берём из КАТАЛОГА реальных акций, а не из текстовой лесенки marts.sql
        net_=q("SELECT net, net_cash FROM player_features WHERE casino_player_id={pid:UInt32}",{'pid':pid})[1]
        _nn=net_[0] if net_ else (0,0)
        oname_,oterms_,owhy_ = offer_for({'lifecycle':life_,'dep_count':dc_,'early_tier':tier_,
            'pred_ltv_d90':ltv_,'p_churn':pch_,'net':_nn[0],'net_cash':_nn[1]})
        p2s_='—' if p2_ is None else f'{round(p2_*100)}%'
        if pch_ is None: rsk_='—'
        else:
            rc_='#991b1b' if pch_>=0.7 else ('#854d0e' if pch_>=0.4 else '#166534')
            rsk_=f'<span style="color:{rc_}">{round(pch_*100)}%</span>'
        sm=lambda v:f'<span style="font-size:15px;line-height:1.3">{escape(str(v))}</span>'
        ctxline=f'<div class=banner style="margin-top:8px">{ctx}</div>' if ctx else ''
        obonus_ = (f'<span style="font-size:15px;line-height:1.3">{escape(oname_)}</span>'
          + (f'<div class=muted style="font-size:11px;margin-top:3px">{escape(oterms_)}</div>' if oterms_ else ''))
        act_sec=('<div class=sec><h2>🎯 Рекомендованное действие <span class=muted>движок офферов · кому/когда/какой бонус</span></h2>'
          '<div class=kgrid>'+kc('Действие',act_badge(a_))+kc('Рекоменд. бонус',obonus_)
          +kc('Когда',sm(when_))+kc('Риск ухода (30д)',rsk_)+kc('P(2-й деп, 30д)',p2s_)+'</div>'
          f'<div class=lead style="margin-top:6px">акция из каталога BillionBahis · подобрана: {escape(owhy_)} · '
          '<a href="/bonuses" style="color:var(--steel)">все акции →</a></div>'
          +ctxline+'</div>')
    else:
        ctxline=f'<div class=banner style="margin-top:8px">{ctx}</div>' if ctx else ''
        act_sec=(('<div class=sec><h2>🎯 Контекст по игре</h2>'+ctxline+'</div>') if ctx else '')
    # --- редактируемый оффер (отдел утверждает / правит / отклоняет) ---
    # предложение оператору = реальная акция из каталога (+ условия), а не фраза из marts.sql
    suggested=(f'{oname_} — {oterms_}' if (av and oterms_) else (oname_ if av else ''))
    off=q("SELECT argMax(status,ts), argMax(offer_text,ts), argMax(note,ts) FROM player_offers WHERE casino_player_id={pid:UInt32}",{'pid':pid})[1]
    os_,ot_,on_=(off[0] if off else ('','',''))
    cur_offer=ot_ if os_ else suggested
    obadge=''
    if os_ in OFFER_STATUS:
        t,bg,fg=OFFER_STATUS[os_]; obadge=f' <span class=badge style="background:{bg};color:{fg}">{t}</span>'
    _ti='padding:8px 10px;border:1px solid var(--haze,#e2e8f0);border-radius:8px;font:inherit;width:100%'
    offer_form=(f'<div class=sec><h2>✍️ Оффер игроку{obadge} <span class=muted>система предложила — отдел утверждает или правит</span></h2>'
      f'<form method=post action="/offer/{pid}" style="max-width:580px;display:flex;flex-direction:column;gap:8px">'
      f'<textarea name=offer_text rows=2 style="{_ti}">{escape(cur_offer or "")}</textarea>'
      f'<input name=note placeholder="заметка оператора (необязательно)" value="{escape(on_ or "")}" style="{_ti}">'
      f'<div style="display:flex;gap:8px;flex-wrap:wrap">'
      f'<button class=btn name=status value=approved>✅ Утвердить</button>'
      f'<button class=btn name=status value=edited>✏️ Сохранить правку</button>'
      f'<button class=btn name=status value=sent>📤 Отправлен</button>'
      f'<button class=btn name=status value=rejected>❌ Отклонить</button>'
      f'</div></form></div>')
    # пометка «обыгрывает казино»: вывел кэша больше, чем внёс (net_cash<0), И выиграл на играх (net>0)
    _pnet = float(d.get('net') or 0); _pncash = float(d.get('net_cash') or 0)
    win_badge = ''
    if _pncash < 0 and _pnet > 0:
        _wt = (f'Обыгрывает казино: касса −{mn(abs(_pncash))} (вывел больше, чем внёс) '
               f'и выигрыш на играх +{mn(_pnet)}. Бонусы такому не рекомендуются (на ревью).')
        win_badge = (f'<span title="{escape(_wt)}" style="display:inline-block;margin-left:10px;padding:3px 10px;'
          f'border-radius:999px;background:#fee2e2;color:#b91c1c;font-size:13px;font-weight:600;vertical-align:middle">'
          f'🎯 Обыгрывает казино</span>')
    content=(f'<a class=back href="/">← к списку игроков</a>'
      f'<div class=topbar style="margin-top:10px"><div><div class=h1>Игрок <em class=bd>{pid}</em>{win_badge}</div>'
      f'<div class=lead>{life_badge(d.get("lifecycle"))}{at_badge(d.get("account_type"))} &nbsp; {"депозитор" if (d.get("dep_count") or 0)>0 else "не депозитор"} · {d.get("primary_provider") or "—"}</div></div></div>'
      f'<div class=kgrid>{kc("Ставок",f(d.get("bets")))}{kc("Оборот ₺",f(d.get("turnover")))}'
      f'{kc("Net ₺",f(net),"neg" if net<0 else "pos")}{kc("GGR ₺",f(d["ggr"]),"pos" if d["ggr"]>=0 else "neg")}{kc("Депозитов",f(d.get("dep_count")))}'
      f'{kc("Recency","—" if d.get("recency_days") is None else f(d.get("recency_days"))+"д")}</div>'
      f'{act_sec}'
      f'{offer_form}'
      f'{ltv_sec}'
      f'{prog_sec}'
      f'<div class=sec><h2>👤 Профиль</h2><div class=fields>{profile}</div></div>'
      f'<div class=sec><h2>💰 Деньги</h2><div class=fields>{money}</div></div>'
      f'{dep_sec}'
      f'<div class=sec><h2>🎮 Игра</h2><div class=fields>{game}</div></div>'
      f'<div class=sec><h2>🧭 Паттерн</h2><div class=fields>{patt}</div></div>'
      f'<div class=sec><h2>🕐 Ритм ставок <span class=muted>когда и как часто играет</span></h2>{rbody}</div>'
      f'{sess_sec}'
      f'{bonus_sec}'
      f'<details class="sec coll"><summary>🗺 Траектория игр ({len(jr)}) <span class=muted>(★ основная сверху · ниже — по порядку знакомства · клик = детали)</span></summary>'
      f'<div class=journey>'
      f'{("<div style=\'font-size:12px;color:var(--steel);font-weight:600;margin:0 0 5px\'>★ основная игра — больше всего ставок</div>"+pinned+"<div style=\'font-size:12px;color:var(--steel);margin:12px 0 5px\'>вся траектория по порядку ↓</div>") if pinned else ""}'
      f'<div class="jrow head"><span>первая ставка</span><span>игра (uuid)</span><span>провайдер</span><span class=n>ставок</span><span class=n>дней</span></div>'
      f'{jrows or "<div class=muted>нет игровых данных</div>"}</div></details>')
    return layout('players', content, head_extra=ECHARTS).replace('</body>', rjs + '</body>')

@app.route('/offer/<int:pid>', methods=['POST'])
def save_offer(pid):
    status = request.form.get('status', 'edited')
    if status not in ('approved', 'edited', 'rejected', 'sent'): status = 'edited'
    offer_text = (request.form.get('offer_text', '') or '')[:500]
    note = (request.form.get('note', '') or '')[:500]
    operator = (BOARD_USER or 'operator')[:40]
    _client().insert('player_offers', [[pid, status, offer_text, note, operator]],
                     column_names=['casino_player_id', 'status', 'offer_text', 'note', 'operator'])
    return Response('', 302, {'Location': f'/player/{pid}'})

OFFER_STATUS = {'approved': ('✅ утверждён', '#dcfce7', '#166534'), 'edited': ('✏️ изменён', '#dbeafe', '#1e40af'),
                'rejected': ('❌ отклонён', '#fee2e2', '#991b1b'), 'sent': ('📤 отправлен', '#fef9c3', '#854d0e')}

@app.route('/player/<int:pid>/game/<path:gid>')
def player_game(pid, gid):
    _info = q(f"""SELECT count(), countIf(transaction_type IN ('bet','freespins_bet')),
       round(sumIf(bet_amount,transaction_type IN ('bet','freespins_bet'))),
       uniqExact(toDate(toTimezone(created_at,'Europe/Istanbul'))), any(aggregator), {GN()}
       FROM game_transactions WHERE casino_player_id={{pid:UInt32}} AND game_uuid={{gid:String}}
       GROUP BY game_uuid""",
       {'pid': pid, 'gid': gid})[1]
    if not _info or not _info[0][1]: abort(404)
    info = _info[0]
    rd, rst = _rhythm("casino_player_id={pid:UInt32} AND game_uuid={gid:String} AND transaction_type IN ('bet','freespins_bet')",
                      {'pid': pid, 'gid': gid})
    rbody, rjs = rhythm_html(rd, rst)
    dates = q("""SELECT toDate(toTimezone(created_at,'Europe/Istanbul')) dt, countIf(transaction_type IN ('bet','freespins_bet')) b,
       round(sumIf(bet_amount,transaction_type IN ('bet','freespins_bet'))) turn
       FROM game_transactions WHERE casino_player_id={pid:UInt32} AND game_uuid={gid:String}
       GROUP BY dt ORDER BY dt""", {'pid': pid, 'gid': gid})[1]
    mx = max([r[1] for r in dates] or [1]) or 1
    drows = ''.join(f'<div class=jrow><i style="width:{round(b/mx*100)}%"></i><span class=d>{dt}</span>'
       f'<span class=g></span><span class=muted></span><span class=n>{f(b)} ст</span><span class=n>{f(turn)} ₺</span></div>' for dt, b, turn in dates)
    kc = lambda l, v: f'<div class=scard><div class=l>{l}</div><div class=v style="font-size:24px">{v}</div></div>'
    content=(f'<a class=back href="/player/{pid}">← к игроку {pid}</a>'
      f'<div class=topbar style="margin-top:10px"><div><div class=h1>Игра <em class=bd>{escape(str(info[5]))}</em></div>'
      f'<div class=lead>игрок {pid} · провайдер {info[4]} · когда и как он ставил именно в этой игре</div></div></div>'
      f'<div class=kgrid>{kc("Ставок",f(info[1]))}{kc("Оборот ₺",f(info[2]))}{kc("Активных дней",f(info[3]))}{kc("Любимый день",rst["peak_day"])}{kc("Любимый час",str(rst["peak_hour"])+":00")}</div>'
      f'<div class=sec><h2>🕐 Когда ставил в этой игре</h2>{rbody}</div>'
      f'<div class=sec><h2>📅 По дням <span class=muted>(дата · ставок · оборот)</span></h2>'
      f'<div class=journey><div class="jrow head"><span>дата</span><span></span><span></span><span class=n>ставок</span><span class=n>оборот</span></div>{drows}</div></div>')
    return layout('players', content, head_extra=ECHARTS).replace('</body>', rjs + '</body>')

# ============================ ANALYTICS (charts) ============================
@app.route('/analytics')
def analytics():
    N="casino_player_id IN (SELECT casino_player_id FROM users WHERE account_type='normal')"
    RB="transaction_type IN ('bet','freespins_bet')"
    life=[{'label':LIFE.get(r[0],('','',r[0]))[2],'value':r[1]} for r in q(f"""
      WITH pp AS (SELECT casino_player_id, multiIf(recency_days IS NULL,'never',recency_days<=7,'active',recency_days<=30,'cooling',recency_days<=60,'at_risk',recency_days<=90,'dormant','churned') s FROM player_features WHERE account_type='normal')
      SELECT s, count() FROM pp GROUP BY s ORDER BY multiIf(s='active',1,s='cooling',2,s='at_risk',3,s='dormant',4,s='churned',5,6)""")[1]]
    rc=q(f"""WITH act AS (SELECT DISTINCT casino_player_id, toMonday(toTimezone(created_at,'Europe/Istanbul')) aw FROM game_transactions WHERE {RB} AND {N}),
      first AS (SELECT casino_player_id, min(aw) fw FROM act GROUP BY casino_player_id)
      SELECT round(100*uniqExactIf(f.casino_player_id,dateDiff('week',f.fw,a.aw)=1)/uniqExact(f.casino_player_id),1),
       round(100*uniqExactIf(f.casino_player_id,dateDiff('week',f.fw,a.aw)=2)/uniqExact(f.casino_player_id),1),
       round(100*uniqExactIf(f.casino_player_id,dateDiff('week',f.fw,a.aw)=4)/uniqExact(f.casino_player_id),1),
       round(100*uniqExactIf(f.casino_player_id,dateDiff('week',f.fw,a.aw)=8)/uniqExact(f.casino_player_id),1)
      FROM first f LEFT JOIN act a ON f.casino_player_id=a.casino_player_id WHERE f.fw>='2025-12-01' AND f.fw<'2026-03-01'""")[1][0]
    ret=[{'w':'W1','v':float(rc[0])},{'w':'W2','v':float(rc[1])},{'w':'W4','v':float(rc[2])},{'w':'W8','v':float(rc[3])}]
    rfm=[{'seg':r[0],'players':r[1]} for r in q(f"""
      WITH pp AS (SELECT casino_player_id, dateDiff('day',toDate(max(created_at)),today()) rc, uniqExact(toDate(created_at)) fr, sumIf(bet_amount,{RB}) mo FROM game_transactions WHERE {N} GROUP BY casino_player_id),
      s AS (SELECT *, 6-ntile(5) OVER (ORDER BY rc) R, ntile(5) OVER (ORDER BY fr) F, ntile(5) OVER (ORDER BY mo) M FROM pp)
      SELECT multiIf(R>=4 AND F>=4 AND M>=4,'Champions',R>=3 AND F>=3,'Loyal',R>=4 AND F<=2,'New',R<=2 AND F>=4 AND M>=4,'Cant-Lose',R<=2 AND F>=3,'At-Risk',R<=2,'Hibernating','Need-Att') seg, count() FROM s GROUP BY seg ORDER BY 2 DESC""")[1]]
    cf=[{'m':str(r[0])[:7],'dep':float(r[1]),'wd':float(r[2])} for r in q("""
      SELECT toStartOfMonth(created_at) m, round(sumIf(amount,type IN ('deposit','manual_deposit') AND status='completed')),
       round(sumIf(amount,type IN ('withdrawal','manual_withdrawal') AND status='completed')) FROM money_transactions GROUP BY m ORDER BY m""")[1]]
    days=[{'label':r[0],'value':r[1]} for r in q(f"""WITH pp AS (SELECT casino_player_id, uniqExact(toDate(created_at)) d FROM game_transactions WHERE {RB} AND {N} GROUP BY casino_player_id)
      SELECT multiIf(d=1,'1 день',d<=3,'2-3',d<=7,'4-7',d<=30,'8-30','30+') s, count() FROM pp GROUP BY s ORDER BY min(d)""")[1]]
    DATA = jsdump({'life':life,'ret':ret,'rfm':rfm,'cf':cf,'days':days})
    he = "<script src='https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js'></script>"
    top=("<div class=topbar><div><div class=h1>Аналитика <em>· графики</em></div>"
      "<div class=lead>графики по всей базе: удержание, жизненный цикл, RFM и денежный поток — чтобы видеть тренды и общую картину (не по отдельному игроку)</div></div>"
      "<div class=pills><span class='pill live'>live</span></div></div>")
    boxes=("<div class=eyebrow>Удержание и активность</div><div class=chgrid>"
      "<div class=chartbox><h3>Удержание новых игроков</h3><div class=cap>% вернувшихся к игре через N недель</div><div class=chart id=c_ret></div></div>"
      "<div class=chartbox><h3>Сколько дней играл игрок</h3><div class=cap>две трети — один день</div><div class=chart id=c_days></div></div></div>"
      "<div class=eyebrow>Сегменты</div><div class=chgrid>"
      "<div class=chartbox><h3>Жизненный цикл</h3><div class=cap>от активного до оттока</div><div class=chart id=c_life></div></div>"
      "<div class=chartbox><h3>RFM-сегменты</h3><div class=cap>кто ценный, кто уходит</div><div class=chart id=c_rfm></div></div></div>"
      "<div class=eyebrow id=cash>Денежный поток</div><div class=chgrid>"
      "<div class=chartbox style='grid-column:1/-1'><h3>Депозиты vs Выводы по месяцам</h3><div class=cap id=risk>включая ручные транзакции — виден февральский провал</div><div class=chart id=c_cf style='height:320px'></div></div></div>")
    js = "<script>const D=" + DATA + ";" + ANALYTICS_JS + "</script>"
    return layout('analytics', top + boxes, head_extra=he) .replace('</body>', js + '</body>')

ANALYTICS_JS = """
const OR='#2563eb',YE='#93c5fd',SU='#60a5fa',INK='#1e293b',ST='#64748b',HA='#e5e7eb';
const tip={backgroundColor:'#fff',borderColor:HA,textStyle:{color:INK}};
const ax=e=>Object.assign({axisLine:{lineStyle:{color:HA}},axisTick:{show:false},axisLabel:{color:ST},splitLine:{lineStyle:{color:HA}}},e||{});
function mk(id,opt){const c=echarts.init(document.getElementById(id));c.setOption(opt);addEventListener('resize',()=>c.resize());}
mk('c_ret',{grid:{left:8,right:14,top:18,bottom:8,containLabel:true},tooltip:Object.assign({trigger:'axis'},tip),
 xAxis:ax({type:'category',data:D.ret.map(x=>x.w),boundaryGap:false}),yAxis:ax({type:'value',axisLabel:{formatter:'{value}%',color:ST}}),
 series:[{type:'line',data:D.ret.map(x=>x.v),smooth:true,symbol:'circle',symbolSize:8,lineStyle:{color:OR,width:3},itemStyle:{color:OR},
  areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:'rgba(37,99,235,.22)'},{offset:1,color:'rgba(37,99,235,0)'}])},label:{show:true,color:OR,formatter:'{c}%'}}]});
mk('c_days',{grid:{left:8,right:30,top:10,bottom:8,containLabel:true},tooltip:Object.assign({trigger:'item'},tip),
 xAxis:ax({type:'value',axisLabel:{show:false},splitLine:{show:false}}),yAxis:ax({type:'category',data:D.days.map(x=>x.label).reverse(),axisLine:{show:false}}),
 series:[{type:'bar',data:D.days.map(x=>x.value).reverse(),barWidth:'60%',itemStyle:{color:OR,borderRadius:[0,5,5,0]},label:{show:true,position:'right',color:ST}}]});
mk('c_life',{grid:{left:8,right:30,top:10,bottom:8,containLabel:true},tooltip:Object.assign({trigger:'item'},tip),
 xAxis:ax({type:'value',axisLabel:{show:false},splitLine:{show:false}}),yAxis:ax({type:'category',data:D.life.map(x=>x.label).reverse(),axisLine:{show:false}}),
 series:[{type:'bar',data:D.life.map(x=>x.value).reverse(),barWidth:'62%',itemStyle:{color:SU,borderRadius:[0,5,5,0]},label:{show:true,position:'right',color:ST}}]});
mk('c_rfm',{grid:{left:8,right:30,top:10,bottom:8,containLabel:true},tooltip:Object.assign({trigger:'item'},tip),
 xAxis:ax({type:'value',axisLabel:{show:false},splitLine:{show:false}}),yAxis:ax({type:'category',data:D.rfm.map(x=>x.seg).reverse(),axisLine:{show:false}}),
 series:[{type:'bar',data:D.rfm.map(x=>x.players).reverse(),barWidth:'62%',itemStyle:{color:INK,borderRadius:[0,5,5,0]},label:{show:true,position:'right',color:ST}}]});
mk('c_cf',{grid:{left:8,right:14,top:30,bottom:8,containLabel:true},tooltip:Object.assign({trigger:'axis'},tip),
 legend:{data:['Депозиты','Выводы'],textStyle:{color:ST},top:0},
 xAxis:ax({type:'category',data:D.cf.map(x=>x.m)}),yAxis:ax({type:'value',axisLabel:{color:ST,formatter:v=>(v/1e6)+'M'}}),
 series:[{name:'Депозиты',type:'bar',data:D.cf.map(x=>x.dep),itemStyle:{color:YE,borderRadius:[4,4,0,0]}},
  {name:'Выводы',type:'bar',data:D.cf.map(x=>x.wd),itemStyle:{color:OR,borderRadius:[4,4,0,0]}}]});
"""

COHORTS_JS = """
const OR='#2563eb',SU='#60a5fa',YE='#93c5fd',INK='#1e293b',ST='#64748b',HA='#e5e7eb';
const tip={backgroundColor:'#fff',borderColor:HA,textStyle:{color:INK},confine:true};
const PAL=[OR,SU,'#93c5fd','#1d4ed8','#bfdbfe',INK,'#cbd5e1'];
function copt(it){const t=it.type,d=it.data||[];
 if(t==='bar')return{grid:{left:6,right:40,top:8,bottom:6,containLabel:true},tooltip:Object.assign({trigger:'item'},tip),
  xAxis:{type:'value',axisLine:{show:false},axisTick:{show:false},splitLine:{show:false},axisLabel:{show:false}},
  yAxis:{type:'category',data:d.map(x=>x.label).reverse(),axisLine:{show:false},axisTick:{show:false},axisLabel:{color:ST,fontSize:11}},
  series:[{type:'bar',data:d.map(x=>x.value).reverse(),barWidth:'62%',itemStyle:{color:OR,borderRadius:[0,4,4,0]},label:{show:true,position:'right',color:ST,fontSize:10}}]};
 if(t==='time')return{grid:{left:6,right:8,top:10,bottom:6,containLabel:true},tooltip:Object.assign({trigger:'axis'},tip),
  xAxis:{type:'category',data:d.map(x=>x.label),axisLine:{lineStyle:{color:HA}},axisTick:{show:false},axisLabel:{color:ST,fontSize:9,interval:Math.ceil(d.length/8)}},
  yAxis:{type:'value',axisLine:{show:false},axisTick:{show:false},splitLine:{lineStyle:{color:HA}},axisLabel:{color:ST,fontSize:10}},
  series:[{type:'bar',data:d.map(x=>x.value),barWidth:'58%',itemStyle:{color:OR,borderRadius:[3,3,0,0]}}]};
 if(t==='area')return{grid:{left:6,right:8,top:10,bottom:6,containLabel:true},tooltip:Object.assign({trigger:'axis'},tip),
  xAxis:{type:'category',data:d.map(x=>x.label),boundaryGap:false,axisLine:{lineStyle:{color:HA}},axisTick:{show:false},axisLabel:{color:ST,fontSize:9,interval:3}},
  yAxis:{type:'value',axisLine:{show:false},axisTick:{show:false},splitLine:{show:false},axisLabel:{show:false}},
  series:[{type:'line',data:d.map(x=>x.value),smooth:true,symbol:'none',lineStyle:{color:OR,width:2},areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:'rgba(37,99,235,.3)'},{offset:1,color:'rgba(37,99,235,0)'}])}}]};
 if(t==='donut')return{tooltip:Object.assign({trigger:'item'},tip),series:[{type:'pie',radius:['48%','75%'],center:['50%','52%'],padAngle:2,
  itemStyle:{borderColor:'#fff',borderWidth:2,borderRadius:4},label:{color:ST,fontSize:11,formatter:p=>p.name},
  data:d.map((x,i)=>({name:x.label,value:x.value,itemStyle:{color:PAL[i%PAL.length]}}))}]};
}
(CD.groups||[]).forEach(g=>g.items.forEach(it=>{
 if(['bar','time','area','donut'].includes(it.type)){const el=document.getElementById('ch_'+it.id);
  if(el){const c=echarts.init(el);c.setOption(copt(it));addEventListener('resize',()=>c.resize());}}
}));
"""

# ============================ ДЕЙСТВИЯ / ОФФЕРЫ ============================
ACT_COLORS = {'SAVE':('#fee2e2','#991b1b'),'WINBACK':('#fef9c3','#854d0e'),
              'NUDGE':('#dbeafe','#1e40af'),'CONVERT':('#e0e7ff','#4338ca'),
              'NURTURE':('#dcfce7','#166534'),'наблюдать':('#f1f5f9','#475569')}
def act_badge(a):
    bg,fg = ACT_COLORS.get(str(a).split(' ')[0], ('#ededed','#8a8a8a'))
    return f'<span class=badge style="background:{bg};color:{fg}">{escape(str(a))}</span>'

ACT_FILTERS = [('SAVE','🚨 спасать'),('WINBACK','↩ вернуть'),('NUDGE','👉 2-й деп'),
               ('CONVERT','💳 первый деп'),('NURTURE','🌱 растить'),('all','все')]

@app.route('/actions')
def actions():
    act = request.args.get('act','SAVE'); act = act if act in dict(ACT_FILTERS) else 'SAVE'
    AF = {'SAVE':"startsWith(action,'SAVE')",'WINBACK':"startsWith(action,'WINBACK')",
          'NUDGE':"startsWith(action,'NUDGE')",'CONVERT':"startsWith(action,'CONVERT')",
          'NURTURE':"startsWith(action,'NURTURE')",'all':"action!='наблюдать'"}
    where = AF[act]
    save_n, save_v = q("SELECT count(), round(sum(value_try)) FROM player_actions WHERE startsWith(action,'SAVE')")[1][0]
    wb_n   = q("SELECT count() FROM player_actions WHERE startsWith(action,'WINBACK')")[1][0][0]
    nudge_n= q("SELECT count() FROM player_actions WHERE startsWith(action,'NUDGE')")[1][0][0]
    conv_n = q("SELECT count() FROM player_actions WHERE startsWith(action,'CONVERT')")[1][0][0]
    cards = ('<div class=cards>'
      + scard('alert', '🚨', 'Спасать сейчас', f(save_n), f'ценность под риском {mn(save_v)}')
      + scard('orange', '↩', 'Вернуть (winback)', f(wb_n), 'ушли, но были ценны')
      + scard('cream', '👉', 'Нудж на 2-й деп', f(nudge_n), 'сделали 1, близки ко 2-му')
      + scard('', '💳', 'Конверсия в деп', f(conv_n), 'играют, но не платят')
      + '</div>')
    dist = q("SELECT action, count(), round(sum(value_try)) FROM player_actions GROUP BY action ORDER BY sum(value_try) DESC")[1]
    ndist = sum(r[1] for r in dist)
    drows = ''.join(f'<tr><td>{act_badge(a)}</td><td class=num>{f(n)}</td><td class=num>{f(v)} ₺</td></tr>' for a,n,v in dist)
    dist_panel = (f'<div class=eyebrow>Что система рекомендует <span class=muted>по всем {f(ndist)} игрокам (incl. «наблюдать» — не в работе)</span></div>'
      '<div class=panel style="overflow-x:auto"><table><thead><tr><th>Действие</th><th>Игроков</th><th>Ценность на кону</th></tr></thead><tbody>'
      + drows + '</tbody></table></div>')
    chips = ''.join(f'<a class="chip {"on" if act==k else ""}" href="?act={k}">{lab}</a>' for k,lab in ACT_FILTERS)
    rows = q(f"SELECT pa.casino_player_id, pa.lifecycle, pa.action, round(pa.value_try), pa.p_churn, pa.p_2nd_deposit, "
             f"pa.bonus, pa.when_to, pa.dep_count, pa.early_tier, pa.pred_ltv_d90, toFloat64(ifNull(pf.net,0)) "
             f"FROM player_actions pa LEFT JOIN player_features pf USING (casino_player_id) "
             f"WHERE {where} ORDER BY pa.priority DESC, pa.value_try DESC LIMIT 60")[1]
    def risk_cell(pch):
        if pch is None: return '<td class=muted>—</td>'
        c = '#991b1b' if pch>=0.7 else ('#854d0e' if pch>=0.4 else '#166534')
        return f'<td class=num style="color:{c};font-weight:600">{round(pch*100)}%</td>'
    trs = ''
    for pid, lf, a, val, pch, p2, bonus, when, dc, tier, ltv, net in rows:
        p2s = '—' if p2 is None else f'{round(p2*100)}%'
        oc = offer_cell({'lifecycle': lf, 'dep_count': dc, 'early_tier': tier,
                         'pred_ltv_d90': ltv, 'p_churn': pch, 'net': net})
        trs += (f'<tr onclick="location.href=\'/player/{pid}\'"><td class=id>{pid}</td>'
                f'<td>{life_badge(lf)}</td><td>{act_badge(a)}</td>'
                f'<td class="num pos">{f(val)} ₺</td>{risk_cell(pch)}<td class=num>{p2s}</td>'
                f'<td>{oc}</td><td class=muted>{escape(str(when))}</td></tr>')
    table = ('<div class=panel style="overflow-x:auto"><table><thead><tr>'
      '<th>ID</th><th>Стадия</th><th>Действие</th><th title="прогноз LTV (сколько принесёт за 90 дн) или сколько уже внёс — по этому ранжируем">Ценность</th>'
      '<th title="вероятность ухода в 30 дней (********)">Риск ухода</th>'
      '<th title="вероятность 2-го депозита в 30 дней (********)">P(2-й деп, 30д)</th>'
      '<th>Рекоменд. бонус</th><th>Когда</th></tr></thead><tbody>' + (trs or '<tr><td colspan=8 class=muted>пусто</td></tr>') + '</tbody></table></div>')
    content = ('<div class=topbar><div><div class=h1>Действия / Офферы <em class=bd>· движок решений</em></div>'
      '<div class=lead>кому · когда · какой бонус — приоритет по «ценность × риск ухода». '
      '<b>Канал доставки</b> — нет данных (telegram/whatsapp пусто)</div></div></div>'
      + cards + dist_panel
      + '<div class=eyebrow style="margin-top:18px">Приоритетный список — клик по строке открывает карточку</div>'
      + f'<div class=bar><span class=muted>фильтр:</span>{chips}</div>'
      + table)
    return layout('actions', content)

# ============================ РЕТЕНШН-ПУЛЬТ (очередь работы отдела) ============================
WMAP = {'7': 7, '14': 14, '30': 30, '90': 90, 'all': 3650}
WLBL = {'7': '7д', '14': '14д', '30': '30д', '90': '90д', 'all': 'всё время'}

@app.route('/desk')
def desk():
    act = request.args.get('act', 'SAVE'); act = act if act in dict(ACT_FILTERS) else 'SAVE'
    w = request.args.get('w', '14'); w = w if w in WMAP else '14'; wd = WMAP[w]; wlbl = WLBL[w]
    AFD = {'SAVE': "startsWith(action,'SAVE')", 'WINBACK': "startsWith(action,'WINBACK')",
           'NUDGE': "startsWith(action,'NUDGE')", 'CONVERT': "startsWith(action,'CONVERT')",
           'NURTURE': "startsWith(action,'NURTURE')", 'all': "action!='наблюдать'"}
    where = AFD[act]
    dmax = q("SELECT toDate(max(created_at)) FROM game_transactions")[1][0][0]
    rows = q(f"""SELECT pa.casino_player_id, pa.lifecycle, pa.action, pa.bonus, pa.when_to,
        round(pa.value_try), pa.p_churn, pa.p_2nd_deposit, round(pa.pred_ltv_d90), pa.dep_count, nd.p_next_deposit,
        pa.early_tier, toFloat64(ifNull(pf.net,0))
        FROM player_actions pa LEFT JOIN player_next_deposit_ml nd USING (casino_player_id)
        LEFT JOIN player_features pf USING (casino_player_id)
        WHERE {where} ORDER BY pa.priority DESC, pa.value_try DESC LIMIT 60""")[1]
    ids = [int(r[0]) for r in rows]
    pulse = {}
    if ids:
        idl = ','.join(str(i) for i in ids)
        for cid, rec, rnet, rsp in q(f"""SELECT casino_player_id,
            dateDiff('day', max(toDate(created_at)), toDate('{dmax}')) AS rec,
            round(sumIf(toFloat64(win_amount)-toFloat64(bet_amount), toDate(created_at) > toDate('{dmax}')-{wd})) AS rnet,
            countIf(toDate(created_at) > toDate('{dmax}')-{wd} AND transaction_type IN ('bet','freespins_bet')) AS rsp
            FROM game_transactions WHERE casino_player_id IN ({idl})
              AND transaction_type IN ('bet','freespins_bet','win','freespins_win')
            GROUP BY casino_player_id""")[1]:
            pulse[cid] = (rec, rnet, rsp)
    offst = {r[0]: r[1] for r in q("SELECT casino_player_id, argMax(status,ts) FROM player_offers GROUP BY casino_player_id")[1] if r[1]}
    nq, vq = q(f"SELECT count(), round(sum(value_try)) FROM player_actions WHERE {where}")[1][0]
    nall = q("SELECT countIf(action!='наблюдать'), count() FROM player_actions")[1][0]
    cards = ('<div class=cards>'
      + scard('alert', '📋', 'В этом фильтре', f(nq), f'из {f(nall[0])} в очереди · {f(nall[1])} всего игроков')
      + scard('orange', '💰', 'Ценность в фильтре', mn(vq or 0), 'суммарный LTV/деп')
      + scard('', '🕘', 'Данные по', str(dmax), 'последний день в базе')
      + '</div>')
    chips = ''.join(f'<a class="chip {"on" if act==k else ""}" href="?act={k}&w={w}">{lab}</a>' for k, lab in ACT_FILTERS)
    wchips = ''.join(f'<a class="chip {"on" if w==k else ""}" href="?act={act}&w={k}">{lab}</a>' for k, lab in WLBL.items())
    trs = ''
    for (pid, lf, a, bonus, when, val, pch, p2, ltv, dc, pnd, tier, pnet) in rows:
        bonus = offer_cell({'lifecycle': lf, 'dep_count': dc, 'early_tier': tier,
                            'pred_ltv_d90': ltv, 'p_churn': pch, 'net': pnet})   # акция из каталога
        rec, rnet, rsp = pulse.get(pid, (None, 0, 0))
        if rnet is None or rsp == 0:
            situ = '<span class=muted>нет недавней игры</span>'; why = ''
        elif rnet < 0:
            situ = f'<span class=neg>🔴 −{f(-rnet)} ₺</span> за {wlbl} · {f(rsp)} спинов'; why = 'проиграл → кэшбэк удержит'
        else:
            situ = f'<span class=pos>🟢 +{f(rnet)} ₺</span> за {wlbl} · {f(rsp)} спинов'; why = 'в плюсе → нудж/фриспины на волне'
        recs = '—' if rec is None else f'{f(rec)}д назад'
        deppos = f'#{f(dc)}' if dc else '—'
        pnds = '' if pnd is None else f' · P(след) {round(pnd*100)}%'
        rsk = '—' if pch is None else f'{round(pch*100)}%'
        rskc = 'neg' if (pch is not None and pch >= 0.7) else ''
        ost = offst.get(pid)
        ob = ''
        if ost in OFFER_STATUS:
            t, bg, fg = OFFER_STATUS[ost]; ob = f'<span class=badge style="background:{bg};color:{fg}">{t}</span> '
        trs += (f'<tr onclick="location.href=\'/player/{pid}\'">'
          f'<td class=id>{pid}<br>{life_badge(lf)}</td>'
          f'<td>{situ}<br><span class=muted>играл {recs} · деп {deppos}{pnds}</span></td>'
          f'<td class="num {rskc}">{rsk}</td>'
          f'<td class=num>{f(ltv)} ₺</td>'
          f'<td>{ob}{act_badge(a)}<br>{bonus}<br>'
          f'<span class=muted>{escape(str(when))}{(" · "+why) if why else ""}</span></td></tr>')
    table = ('<div class=panel style="overflow-x:auto"><table><thead><tr>'
      f'<th>Игрок</th><th>Что происходит (net/спины за {wlbl})</th><th title="риск ухода 30д">Риск</th>'
      '<th title="прогноз: сколько игрок принесёт депозитами за 90 дней">LTV прогноз</th><th>Оффер — что дать и когда</th></tr></thead><tbody>'
      + (trs or '<tr><td colspan=5 class=muted>пусто</td></tr>') + '</tbody></table></div>')
    content = ('<div class=topbar><div><div class=h1>Ретеншн-пульт <em class=bd>· рабочая очередь</em></div>'
      '<div class=lead>живая очередь отдела: кого трогать сейчас, что у него происходит и какой оффер дать · клик по строке — карточка · '
      '<a href="/live" style="color:var(--steel)">🔴 кто играет прямо сейчас →</a></div></div></div>'
      + cards
      + f'<div class=bar style="margin-top:4px"><span class=muted>задача:</span>{chips}</div>'
      + f'<div class=bar style="margin-top:-4px"><span class=muted>окно:</span>{wchips}</div>'
      + table)
    return layout('desk', content)

@app.route('/live')
def live():
    dmaxts = q("SELECT max(created_at) FROM game_transactions")[1][0][0]
    dmax = q("SELECT toDate(max(created_at)) FROM game_transactions")[1][0][0]
    # «Сейчас за столом» = игроки со ставкой за последние LIVE_WIN минут (реальное «в моменте»),
    # а не количество строк в таблице (та упиралась в LIMIT и всегда показывала 80).
    LIVE_WIN = int(request.args.get('w') or 30)
    LIVE_WIN = LIVE_WIN if LIVE_WIN in (15, 30, 60, 180) else 30
    n_now = q(f"""SELECT uniqExact(casino_player_id) FROM game_transactions
        WHERE created_at > (SELECT max(created_at) FROM game_transactions) - INTERVAL {LIVE_WIN} MINUTE
          AND transaction_type IN ('bet','freespins_bet')
          AND casino_player_id IN (SELECT casino_player_id FROM users WHERE account_type='normal')""")[1][0][0]
    # текущая (последняя) сессия каждого активного игрока — это и есть «в моменте»
    rows = q(f"""SELECT casino_player_id,
        max(send)                       AS last_bet,
        argMax(net, send)               AS cur_net,
        argMax(spins, send)             AS cur_spins,
        argMax(dur, send)               AS cur_dur,
        {GN('argMax(gid, send)')}       AS cur_game
      FROM (
        SELECT casino_player_id, session_id,
          max(created_at) AS send,
          round(dateDiff('second', min(created_at), max(created_at))/60) AS dur,
          countIf(transaction_type IN ('bet','freespins_bet')) AS spins,
          round(sumIf(toFloat64(win_amount)-toFloat64(bet_amount), 1)) AS net,
          argMax(game_uuid, created_at) AS gid
        FROM game_transactions
        WHERE created_at > (SELECT max(created_at) FROM game_transactions) - INTERVAL {LIVE_WIN} MINUTE
          AND transaction_type IN ('bet','freespins_bet','win','freespins_win')
          AND casino_player_id IN (SELECT casino_player_id FROM users WHERE account_type='normal')
        GROUP BY casino_player_id, session_id HAVING spins > 0
      )
      GROUP BY casino_player_id ORDER BY last_bet DESC LIMIT 200""")[1]
    ids = [int(r[0]) for r in rows]
    eng = {}
    if ids:
        idl = ','.join(map(str, ids))
        for cid, lf, a, bonus, pch, ltv, dc, pnd in q(f"""SELECT pa.casino_player_id, pa.lifecycle, pa.action, pa.bonus,
            pa.p_churn, round(pa.pred_ltv_d90), pa.dep_count, nd.p_next_deposit
            FROM player_actions pa LEFT JOIN player_next_deposit_ml nd USING (casino_player_id)
            WHERE pa.casino_player_id IN ({idl})""")[1]:
            eng[cid] = (lf, a, bonus, pch, ltv, dc, pnd)
    items = []
    for cid, last_bet, cur_net, cur_spins, cur_dur, cur_game in rows:
        lf, a, bonus, pch, ltv, dc, pnd = eng.get(cid, (None, None, '—', None, 0, 0, None))
        ltv = ltv or 0
        alert = (cur_net < 0 and ltv >= 10000)   # ценный + проигрывает сейчас
        items.append((alert, last_bet, cid, last_bet, cur_net, cur_spins, cur_dur, cur_game, lf, a, bonus, pch, ltv, dc, pnd))
    # алерты наверх, далее самые свежие
    items.sort(key=lambda x: (0 if x[0] else 1, -x[1].timestamp()))
    n_alert = sum(1 for x in items if x[0])
    cards = ('<div class=cards>'
      + scard('alert', '🚨', 'СРОЧНО (ценный сливает)', f(n_alert), 'онлайн, в минусе, LTV≥10k — кэшбэк сейчас')
      + scard('', '🔴', 'Сейчас за столом', f(n_now), f'ставили за последние {LIVE_WIN} мин')
      + scard('cream', '🔄', 'Авто-обновление', '20 сек', f'показаны {f(len(rows))} последних · окно {LIVE_WIN} мин')
      + '</div>')
    trs = ''
    for (alert, _s, cid, last_bet, cur_net, cur_spins, cur_dur, cur_game, lf, a, bonus, pch, ltv, dc, pnd) in items:
        secs = (dmaxts - last_bet).total_seconds()
        ago = f'{int(secs//3600)}ч {int((secs%3600)//60)}м назад' if secs >= 3600 else f'{int(secs//60)}м назад'
        if cur_net < 0:
            live_s = f'<span class=neg>🔴 проигрывает −{f(-cur_net)} ₺</span>'; now = '🔻 онлайн и в минусе → <b>кэшбэк / бонус на проигрыш СЕЙЧАС</b>'
        elif cur_net > 0:
            live_s = f'<span class=pos>🟢 выигрывает +{f(cur_net)} ₺</span>'; now = '🔺 онлайн и в плюсе → нудж к депозиту на волне'
        else:
            live_s = '≈ в ноль'; now = '➖ онлайн — наблюдаем'
        rsk = '—' if pch is None else f'{round(pch*100)}%'
        pnds = '' if pnd is None else f' · P(след.деп) {round(pnd*100)}%'
        rstyle = ' style="background:#fff1f2"' if alert else ''
        amark = '🚨 ' if alert else ''
        trs += (f'<tr{rstyle} onclick="location.href=\'/player/{cid}\'">'
          f'<td class=id>{amark}{cid}<br>{life_badge(lf)}</td>'
          f'<td>сессия идёт <b>{f(cur_dur)} мин</b> · {f(cur_spins)} спинов<br>'
          f'<span class=muted>{escape(str(cur_game))} · посл. ставка {ago} · деп #{f(dc)}{pnds}</span></td>'
          f'<td>{live_s}</td>'
          f'<td class="num {"neg" if (pch is not None and pch>=0.7) else ""}">{rsk}</td>'
          f'<td class=num>{f(ltv)} ₺</td>'
          f'<td>{now}<br><span class=muted>оффер: </span>'
          f'{offer_cell({"lifecycle": lf, "dep_count": dc, "pred_ltv_d90": ltv, "p_churn": pch, "net": cur_net})}'
          f'</td></tr>')
    table = ('<div class=panel style="overflow-x:auto"><table><thead><tr>'
      '<th>Игрок</th><th>Текущая сессия (в моменте)</th><th title="выигрывает или проигрывает в этой сессии">Идёт сессия</th><th title="вероятность, что игрок уйдёт в ближайшие 30 дней">Риск</th>'
      '<th title="прогноз: сколько принесёт депозитами за 90 дней">LTV</th><th>Что делать СЕЙЧАС</th></tr></thead><tbody>'
      + (trs or '<tr><td colspan=6 class=muted>сейчас никто не активен</td></tr>') + '</tbody></table></div>')
    content = ('<div class=topbar><div><div class=h1>🔴 Играют сейчас <em class=bd>· живой моментум</em></div>'
      '<div class=lead>текущая сессия каждого: сколько идёт, выигрывает или проигрывает в моменте, и что предложить немедленно · '
      'экран сам обновляется каждые 20 сек · <a href="/desk" style="color:var(--steel)">← вся очередь</a></div></div></div>'
      + cards + '<div class=eyebrow style="margin-top:8px">Самые свежие первыми · клик — карточка</div>' + table)
    return layout('live', content, head_extra='<meta http-equiv="refresh" content="20">')

# ============================ РАСПРЕДЕЛЕНИЯ (перцентили / концентрация) ============================

@app.route('/dist')
def dist():
    ld = q("SELECT decile, players, avg_ltv, sum_ltv, pct_of_value FROM ltv_deciles ORDER BY decile")[1]
    cd = q("SELECT decile, players, avg_risk, lo, hi FROM churn_deciles ORDER BY decile")[1]
    dp = q("SELECT p10,p25,p50,p75,p90,p95,p99,pmax FROM deposit_percentiles")[1][0]
    top_pct = ld[0][4] if ld else 0
    nld = sum(r[1] for r in ld); ncd = sum(r[1] for r in cd)
    ndep = q("SELECT count() FROM player_features WHERE account_type='normal' AND dep_count>0")[1][0][0]
    cards = ('<div class=cards>'
      + scard('orange', '🐋', 'Топ-10% держат', f'{top_pct}%', 'всей прогнозной ценности LTV')
      + scard('', '📐', 'Медиана депозитов', f'{f(dp[2])} ₺', f'P90 {f(dp[4])} · P99 {f(dp[6])}')
      + scard('cream', '📈', 'Макс депозит', mn(dp[7]), 'разброс огромный')
      + '</div>')
    lrows = ''.join(f'<tr><td class=id>{"🐋 " if no==1 else ""}D{no}</td><td class=num>{f(p)}</td>'
                    f'<td class=num>{f(av)} ₺</td><td class=num>{mn(sm)}</td><td class=num>{pc}%</td></tr>'
                    for no, p, av, sm, pc in ld)
    lpanel = (f'<div class=eyebrow>Децили по прогнозному LTV <span class=muted>над {f(nld)} игроками с LTV-прогнозом (депозиторы) · D1 = топ-10%, D10 = низ</span></div>'
      '<div class=panel style="overflow-x:auto"><table><thead><tr><th>Дециль</th><th>Игроков</th>'
      '<th>Средний LTV</th><th>Сумма</th><th>% всей ценности</th></tr></thead><tbody>' + lrows + '</tbody></table></div>'
      '<div class=lead style="margin:6px 0 0">📖 <b>Дециль</b> = база делится на 10 равных групп по 10%. <b>D1 = топ-10%</b> самых ценных, D10 = самые мелкие. Колонка «% всей ценности» показывает, сколько денег держит группа — видно, что верхушка держит почти всё (концентрация на китах).</div>')
    crows = ''.join(f'<tr><td class=id>D{no}</td><td class=num>{f(p)}</td><td class=num>{round(av*100)}%</td>'
                    f'<td class=num>{round(lo*100)}–{round(hi*100)}%</td></tr>' for no, p, av, lo, hi in cd)
    cpanel = (f'<div class=eyebrow style="margin-top:16px">Децили по риску ухода <span class=muted>среди {f(ncd)} активных игроков с churn-скором (не вся база)</span></div>'
      '<div class=panel style="overflow-x:auto"><table><thead><tr><th>Дециль</th><th>Игроков</th>'
      '<th>Ср. риск</th><th>Диапазон</th></tr></thead><tbody>' + crows + '</tbody></table></div>'
      '<div class=lead style="margin:6px 0 0">📖 <b>Как читать:</b> активные игроки поделены на 10 групп по риску ухода. <b>D1 = самый низкий риск</b> (скорее останутся), D10 = самый высокий (скорее уйдут). «Ср. риск» — средняя вероятность ухода в группе.</div>')
    # --- куда делись остальные (почему churn не по всей базе) ---
    sc_n, os_n, gn_n, nv_n = q("""WITH (SELECT toDate(max(created_at)) FROM game_transactions) AS dmax SELECT
        countIf(account_type='normal' AND ever_played AND dateDiff('day',toDate(last_bet_date),dmax)<=30 AND active_days>=2),
        countIf(account_type='normal' AND ever_played AND dateDiff('day',toDate(last_bet_date),dmax)<=30 AND active_days<2),
        countIf(account_type='normal' AND ever_played AND dateDiff('day',toDate(last_bet_date),dmax)>30),
        countIf(account_type='normal' AND NOT ever_played)
      FROM player_features""")[1][0]
    bd = [('🟢 Активны + удерживаемы','≥2 дня, играл ≤30 дн', sc_n, '← только эти и скорятся на churn'),
          ('🔴 Уже ушли','последняя ставка >30 дн назад', gn_n, 'не «удерживать», а возвращать (winback)'),
          ('⚪ Никогда не играли','нет ни одной ставки', nv_n, 'удерживать нечего'),
          ('💨 Разовые','1 активный день — пришёл-ушёл', os_n, 'нечего удерживать (исключены по ML_PLAN)')]
    brk = ''.join(f'<tr><td>{g}</td><td class=num>{f(n)}</td><td class=muted>{escape(d)} · {escape(note)}</td></tr>' for g, d, n, note in bd)
    chbreak = ('<div class=eyebrow style="margin-top:16px">Почему churn не по всей базе — куда делись остальные</div>'
      '<div class=panel style="overflow-x:auto"><table><thead><tr><th>Группа</th><th>Игроков</th><th>Почему / что с ними делать</th></tr></thead>'
      f'<tbody>{brk}</tbody><tfoot><tr style="border-top:2px solid var(--hair)"><td><b>Итого</b></td><td class=num><b>{f(sc_n+os_n+gn_n+nv_n)}</b></td><td class=muted>вся база normal</td></tr></tfoot></table></div>'
      '<div class=lead style="margin:6px 0 0">churn-риск осмыслен только для живых: ушедших — возвращать, не игравших — конвертировать, разовых — онбордить. Это и делает движок на <a href="/desk" style="color:var(--steel)">Пульте</a>.</div>')
    prow = ''.join(f'<tr><td class=id>{lab}</td><td class=num>{f(v)} ₺</td></tr>'
                   for lab, v in zip(['P10','P25','P50','P75','P90','P95','P99','max'], dp))
    ppanel = (f'<div class=eyebrow style="margin-top:16px">Перцентили суммы депозитов <span class=muted>по {f(ndep)} депозиторам (dep_count&gt;0)</span></div>'
      '<div class=panel style="overflow-x:auto"><table><thead><tr><th>Перцентиль</th><th>Сумма ₺</th></tr></thead><tbody>'
      + prow + '</tbody></table></div>'
      '<div class=lead style="margin:6px 0 0">📖 <b>Как читать:</b> «P90 = 11 000» значит <b>90% депозиторов внесли меньше 11 000 ₺</b>, и только 10% — больше. <b>P50 = медиана</b> (типичный игрок). Видно перекос: типичный ~1.3k, а топ-1% (P99) — за 110k. Поэтому «среднее» обманывает (его задирают киты).</div>')
    content = ('<div class=topbar><div><div class=h1>Распределения <em class=bd>· перцентили и концентрация</em></div>'
      '<div class=lead>распределение ценности и риска по децилям/перцентилям — видеть концентрацию (киты держат бóльшую часть), а не обманчивое среднее</div></div></div>'
      + cards + lpanel + cpanel + chbreak + ppanel)
    return layout('dist', content)

# ============================ ВОРОНКА ДЕПОЗИТОВ ============================
@app.route('/funnel')
def funnel():
    reg = q("SELECT count() FROM users WHERE account_type='normal'")[1][0][0]
    played = q("SELECT countIf(ever_played) FROM player_features WHERE account_type='normal'")[1][0][0]
    lad = q("SELECT deposit_no, reached FROM deposit_ladder ORDER BY deposit_no")[1]
    # единая база депозитов из deposit_ladder (по факту завершённых депозитов), включая FTD#1
    stages = [('Регистрация', reg), ('Играл хоть раз', played)]
    for no, reached in lad:
        stages.append(('Депозит #1 (FTD)' if no == 1 else f'Депозит #{no}', reached))
    mx = stages[0][1] or 1
    rows = ''; prev = None
    for name, n in stages:
        step = '' if prev is None else f'{round(100*n/prev) if prev else 0}%'
        rows += (f'<tr><td>{name}</td><td class=num>{f(n)}</td><td class=num>{round(100*n/reg,1) if reg else 0}%</td>'
                 f'<td class=num>{step}</td><td style="min-width:160px"><div style="background:#fde68a;height:16px;border-radius:4px;width:{round(n/mx*100) if mx else 0}%"></div></td></tr>')
        prev = n
    table = ('<div class=panel style="overflow-x:auto"><table><thead><tr><th>Этап</th><th>Игроков</th>'
      '<th>% от рег</th><th title="к предыдущему этапу">Конверсия шага</th><th>Воронка</th></tr></thead><tbody>' + rows + '</tbody></table></div>')
    content = ('<div class=topbar><div><div class=h1>Воронка депозитов <em class=bd>· где теряем</em></div>'
      '<div class=lead>путь игрока: регистрация → играл → 1-й депозит → #2 → … → #10 · где отваливается больше всего видно по колонке «конверсия шага»</div></div></div>'
      + table)
    return layout('funnel', content)

# ============================ ОТЧЁТ ОТДЕЛА (офферы) ============================
@app.route('/report')
def report():
    # --- сводка очереди (что в работе) из движка ---
    qn, qv, qhead = q("SELECT count(), round(sum(value_try)), round(sum(ltv_headroom)) FROM player_actions WHERE action!='наблюдать'")[1][0]
    dist = q("SELECT action, count(), round(sum(value_try)), round(avg(priority)) FROM player_actions WHERE action!='наблюдать' GROUP BY action ORDER BY sum(value_try) DESC")[1]
    topp = q("SELECT pa.casino_player_id, pa.lifecycle, pa.action, round(pa.value_try), pa.p_churn, pa.bonus, "
             "pa.dep_count, pa.early_tier, pa.pred_ltv_d90, toFloat64(ifNull(pf.net,0)) "
             "FROM player_actions pa LEFT JOIN player_features pf USING (casino_player_id) "
             "WHERE pa.action!='наблюдать' ORDER BY pa.priority DESC, pa.value_try DESC LIMIT 12")[1]
    # распределение по РЕАЛЬНЫМ акциям каталога (в работе = кроме «наблюдать»)
    _bd = _bonus_distribution()
    bdist = sorted(((_bd['names'].get(bid, bid), n, _bd['values'].get(bid, 0))
                    for bid, n in _bd['counts'].items() if _bd['values'].get(bid, 0) > 0),
                   key=lambda x: -x[1])
    # --- активность по офферам ---
    sc = q("SELECT s, count() FROM (SELECT casino_player_id, argMax(status,ts) s FROM player_offers GROUP BY casino_player_id) GROUP BY s")[1]
    by = {s: n for s, n in sc}; total = sum(by.values())
    log = q("SELECT casino_player_id, argMax(status,ts), argMax(offer_text,ts), argMax(operator,ts), toString(max(ts)) FROM player_offers GROUP BY casino_player_id ORDER BY max(ts) DESC LIMIT 20")[1]

    cards = ('<div class=cards>'
      + scard('alert', '📋', 'В работе (очередь)', f(qn), 'из 39 010 игроков (остальные — «наблюдать»)')
      + scard('orange', '💰', 'Ценность под риском', mn(qv or 0), 'суммарный LTV/деп в очереди')
      + scard('cream', '📈', 'Потенциал (headroom)', mn(qhead or 0), 'ожидаемые будущие депозиты')
      + scard('', '✍️', 'Офферов оформлено', f(total), f'отправлено: {f(by.get("sent",0))} · отклонено: {f(by.get("rejected",0))}')
      + '</div>')
    drows = ''.join(f'<tr><td>{act_badge(a)}</td><td class=num>{f(n)}</td><td class=num>{mn(v or 0)}</td><td class=num>{f(pr)}</td></tr>' for a, n, v, pr in dist)
    dpanel = ('<div class=eyebrow>Что в работе по задачам <span class=muted>из движка офферов</span></div>'
      '<div class=panel style="overflow-x:auto"><table><thead><tr><th>Задача</th><th>Игроков</th>'
      '<th title="суммарный прогноз LTV/депозитов в этой задаче">Ценность</th><th title="ценность × вероятность ухода — чем выше, тем срочнее">Ср. приоритет</th></tr></thead><tbody>' + drows + '</tbody></table></div>')
    trows = ''
    for pid, lf, a, val, pch, bonus, dc, tier, ltv, pnet in topp:
        rsk = '—' if pch is None else f'{round(pch*100)}%'
        oc = offer_cell({'lifecycle': lf, 'dep_count': dc, 'early_tier': tier,
                         'pred_ltv_d90': ltv, 'p_churn': pch, 'net': pnet})
        trows += (f'<tr onclick="location.href=\'/player/{pid}\'"><td class=id>{pid}</td><td>{life_badge(lf)}</td>'
                  f'<td>{act_badge(a)}</td><td class="num pos">{f(val)} ₺</td><td class=num>{rsk}</td><td>{oc}</td></tr>')
    tpanel = ('<div class=eyebrow style="margin-top:16px">🔝 Топ-приоритеты сейчас <span class=muted>кого трогать первым · клик — карточка</span></div>'
      '<div class=panel style="overflow-x:auto"><table><thead><tr><th>ID</th><th>Стадия</th><th>Задача</th>'
      '<th>Ценность</th><th>Риск</th><th>Бонус</th></tr></thead><tbody>' + trows + '</tbody></table></div>')
    brows = ''.join(f'<tr><td>{escape(str(b))}</td><td class=num>{f(n)}</td><td class=num>{mn(v or 0)}</td></tr>' for b, n, v in bdist)
    bpanel = ('<div class=eyebrow style="margin-top:16px">Рекомендованные бонусы <span class=muted>что система советует дать</span></div>'
      '<div class=panel style="overflow-x:auto"><table><thead><tr><th>Бонус</th><th>Игроков</th><th>Ценность</th></tr></thead><tbody>' + brows + '</tbody></table></div>')
    if log:
        lrows = ''.join(f'<tr onclick="location.href=\'/player/{pid}\'"><td class=id>{pid}</td><td>{escape(str(st))}</td>'
                        f'<td>{escape(str(txt)[:50])}</td><td class=muted>{escape(str(op))}</td><td class=muted>{escape(str(ts)[:16])}</td></tr>'
                        for pid, st, txt, op, ts in log)
        lpanel = ('<div class=eyebrow style="margin-top:16px">Журнал офферов <span class=muted>что оформил отдел</span></div>'
          '<div class=panel style="overflow-x:auto"><table><thead><tr><th>Игрок</th><th>Статус</th><th>Оффер</th>'
          '<th>Оператор</th><th>Когда</th></tr></thead><tbody>' + lrows + '</tbody></table></div>')
    else:
        lpanel = ('<div class=eyebrow style="margin-top:16px">Журнал офферов</div>'
          '<div class=banner style="margin-top:4px">Здесь появятся офферы, как только отдел начнёт работать: '
          'в карточке игрока система пишет оффер → оператор <b>утверждает / правит / отправляет</b> → запись падает сюда. '
          'Пока оформлен 1 оффер — список наполнится по мере работы.</div>')
    content = ('<div class=topbar><div><div class=h1>Отчёт отдела <em class=bd>· работа и приоритеты</em></div>'
      '<div class=lead>что отдел должен делать (из движка) и что уже сделал (офферы)</div></div></div>'
      + cards + dpanel + tpanel + bpanel + lpanel)
    return layout('report', content)

# ============================ RFM-СЕГМЕНТЫ ============================
@app.route('/rfm')
def rfm():
    rows = q("""
      WITH scored AS (
        SELECT turnover, recency_days, active_days,
          6 - ntile(5) OVER (ORDER BY recency_days) AS R,
          ntile(5) OVER (ORDER BY active_days)      AS F,
          ntile(5) OVER (ORDER BY turnover)         AS M
        FROM player_features WHERE account_type='normal' AND turnover > 0
      )
      SELECT multiIf(
          R>=4 AND F>=4 AND M>=4,        'Champions',
          R>=3 AND F>=3,                 'Loyal',
          R>=4 AND F<=2,                 'New / Promising',
          R<=2 AND F>=4 AND M>=4,        'Cant-Lose-Them',
          R<=2 AND F>=3,                 'At-Risk',
          R<=2,                          'Hibernating / Lost',
                                         'Need-Attention') AS seg,
        count() AS n, round(avg(turnover)) AS avg_turn,
        round(avg(recency_days)) AS avg_rec, round(avg(active_days),1) AS avg_act
      FROM scored GROUP BY seg ORDER BY n DESC""")[1]
    played = sum(r[1] for r in rows)
    base = q("SELECT count() FROM player_features WHERE account_type='normal'")[1][0][0]
    never = base - played
    total = base or 1
    META = {
      'Champions':          ('#dcfce7', '#166534', 'недавно + часто + много', 'беречь, VIP-программа'),
      'Loyal':              ('#dbeafe', '#1e40af', 'стабильное ядро',         'апсейл, удержание'),
      'New / Promising':    ('#fef9c3', '#854d0e', 'недавно, мало активности','онбординг'),
      'Cant-Lose-Them':     ('#fee2e2', '#991b1b', 'ценные, но пропали',      '🔴 срочно вернуть'),
      'At-Risk':            ('#ffedd5', '#9a3412', 'были активны, уходят',    'удержание сейчас'),
      'Hibernating / Lost': ('#f1f5f9', '#475569', 'давно не играли',         'win-back или отпустить'),
      'Need-Attention':     ('#f3e8ff', '#6b21a8', 'средние',                 'реактивация'),
    }
    cards = ('<div class=cards>'
      + scard('alert', '📊', 'Охват RFM', f(played), f'из {f(base)} normal · {f(never)} не играли (нет ставок)')
      + scard('', '📅', 'R — Recency (давность)', '1–5', 'как давно играл · меньше = выше балл')
      + scard('', '🔁', 'F — Frequency (частота)', '1–5', 'активных дней')
      + scard('cream', '💰', 'M — Monetary (деньги)', '1–5', 'оборот ставок')
      + '</div>')
    trs = ''
    for seg, n, avg_turn, avg_rec, avg_act in rows:
        bg, fg, mean, act = META.get(seg, ('#ededed', '#666', '', ''))
        trs += (f'<tr><td><span class=badge style="background:{bg};color:{fg}">{escape(seg)}</span></td>'
          f'<td class=num>{f(n)}</td><td class=num>{round(100*n/total,1)}%</td>'
          f'<td class=num>{f(avg_turn)} ₺</td><td class=num>{f(avg_rec)}д</td><td class=num>{avg_act}</td>'
          f'<td class=muted>{escape(mean)}</td><td>{escape(act)}</td></tr>')
    trs += (f'<tr><td><span class=badge style="background:#ededed;color:#94a3b8">⚪ Не играли (нет RFM)</span></td>'
      f'<td class=num>{f(never)}</td><td class=num>{round(100*never/total,1)}%</td>'
      f'<td class=num>0 ₺</td><td class=num>—</td><td class=num>—</td>'
      f'<td class=muted>зарегистрированы, но без ставок</td><td>конверсия в игру / 1-й депозит</td></tr>')
    table = ('<div class=eyebrow>Сегменты RFM <span class=muted>вся база normal = '
      + f(base) + ' · RFM считается по игравшим (оборот&gt;0)</span></div>'
      '<div class=panel style="overflow-x:auto"><table><thead><tr>'
      '<th>Сегмент</th><th>Игроков</th><th>% базы</th><th>Ср. оборот</th>'
      '<th title="дней с последней ставки">Ср. recency</th><th title="активных дней">Ср. дней</th>'
      '<th>Что значит</th><th>Действие</th></tr></thead><tbody>' + trs + '</tbody></table></div>')
    content = ('<div class=topbar><div><div class=h1>RFM-сегменты <em class=bd>· Recency · Frequency · Monetary</em></div>'
      '<div class=lead>классическая сегментация по 3 осям ценности · квинтили 1–5 '
      '(у Recency балл инвертирован: недавно = 5) → именованные сегменты · правило по прошлому, не ML.<br>'
      '⚠️ RFM требует ось Monetary (оборот), поэтому считается только по <b>игравшим</b>; '
      'кто не сделал ни ставки — отдельной строкой внизу (сходится к ' + f(base) + ').</div></div></div>'
      + cards + table
      + '<div class=lead style="margin-top:14px">💡 RFM — для общей картины и кампаний. Для точной приоритизации «кому что дать» — '
      'движок офферов на <a href="/desk" style="color:var(--steel)">Пульте</a> (там churn/LTV-модели).</div>')
    return layout('rfm', content)

# ============================ ОБОЗНАЧЕНИЯ (словарь) ============================
@app.route('/glossary')
def glossary():
    def tbl(title, rows):
        body = ''.join(f'<tr><td><b>{escape(t)}</b></td><td class=muted style="white-space:nowrap">{escape(full)}</td><td>{escape(plain)}</td></tr>' for t, full, plain in rows)
        return (f'<div class=eyebrow style="margin-top:18px">{escape(title)}</div>'
                '<div class=panel style="overflow-x:auto"><table><thead><tr><th>Термин</th><th>Расшифровка</th><th>Простыми словами</th></tr></thead><tbody>' + body + '</tbody></table></div>')
    eco = tbl('💰 Экономика / деньги', [
      ('Ставка (bet)', 'оборот / turnover', 'сколько игрок поставил В ИГРЕ (за спин/кон). Сумма всех ставок = оборот'),
      ('Выигрыш (win)', '', 'сколько игра ВЕРНУЛА игроку на игровой баланс (можно снова ставить)'),
      ('GGR', 'Gross Gaming Revenue', 'доход казино от игры = все ставки − все выигрыши'),
      ('RTP', 'Return To Player', 'какой % ставок вернулся игрокам выигрышами'),
      ('Hold', 'удержание', 'доля оборота, осевшая у казино (100% − RTP)'),
      ('Депозит', '', 'игрок занёс деньги НА СЧЁТ (вход денег — другая таблица, не ставка!)'),
      ('Вывод', '', 'игрок снял деньги СО СЧЁТА (выход денег)'),
      ('Кэш-нетто', '', 'реальные деньги: депозиты − выводы'),
      ('FTD', 'First Time Deposit', 'самый первый депозит игрока'),
      ('Депозитор', '', 'игрок, сделавший хотя бы один депозит'),
    ]) + ('<div class=banner style="margin-top:8px">⚠️ <b>Не путать!</b> <b>Ставка / выигрыш</b> — это про ИГРУ (сколько поставил и сколько игра вернула). '
      '<b>Депозит / вывод</b> — про ДЕНЬГИ НА СЧЁТЕ (занёс / снял). Один депозит можно проставить много раз → '
      '<b>оборот в разы больше депозитов</b> (у нас ставки 343 млн против депозитов 30 млн — деньги крутятся по кругу).</div>')
    val = tbl('🎯 Игрок и ценность', [
      ('LTV', 'Lifetime Value', 'прогноз: сколько игрок принесёт депозитами (у нас — за 90 дней)'),
      ('Net', 'чистый результат', 'выигрыши − ставки игрока (+ в плюсе / − слил казино)'),
      ('Recency', 'давность', 'сколько дней прошло с последней ставки'),
      ('Headroom / «ещё ожидаем»', '', 'сколько игрок ещё внесёт сверх уже внесённого'),
      ('Churn', 'отток', 'уход игрока — перестал играть'),
      ('Lifecycle', 'жизненный цикл', 'стадия: активен · остывает · под риском · спящий · отток'),
      ('VIP', '', 'самые ценные / крупные игроки'),
      ('Тир A/B/C/D', 'tier', 'группа по депозиту 1-й недели: A <1k · B 1–3k · C 3–10k · D 10k+ (кит)'),
    ])
    seg = tbl('🧩 Сегменты (RFM)', [
      ('RFM', 'Recency · Frequency · Monetary', 'сегментация по 3 осям: давность · частота · деньги'),
      ('R / F / M', '', 'баллы 1–5 по каждой оси (квинтили). У Recency: недавно = 5'),
      ('Champions', '', 'недавно + часто + много → беречь, VIP'),
      ('Loyal', '', 'стабильное ядро'),
      ('Cant-Lose-Them', '', 'ценные, но пропали → срочно вернуть'),
      ('At-Risk / Hibernating', '', 'уходят / давно не играли'),
    ])
    pred = tbl('📈 Прогнозы и горизонты', [
      ('D1 / D7 / D30 / D90 / D120', '', 'день 1 / 7 / 30 / 90 / 120 от первого депозита'),
      ('P(2-й деп, 30д)', 'probability', 'вероятность, что игрок сделает 2-й депозит за 30 дней'),
      ('P(след. деп)', '', 'вероятность дойти до следующего депозита'),
      ('Риск ухода (30д)', 'p_churn', 'вероятность, что игрок уйдёт в ближайшие 30 дней'),
      ('P10 / P50 / P90', 'перцентили', 'P50 = медиана (типичный). P90 = только 10% выше этого'),
      ('Дециль', '', 'база делится на 10 равных групп; D1 = топ-10%'),
    ])
    ml = tbl('🤖 Модели и качество', [
      ('ML', 'Machine Learning', 'модель учится на данных и предсказывает'),
      ('********', '', 'алгоритм ML, который мы используем (для таблиц лучший)'),
      ('AUC', 'площадь под ROC', 'качество «да/нет»: 0.5 угадайка · 0.7–0.8 хорошо · 0.9+ супер'),
      ('Spearman', 'ранговая корреляция', 'насколько верно модель СОРТИРУЕТ (0 случайно, 1 идеал)'),
      ('Калибровка', '', 'насколько «70%» реально означает 70%'),
      ('Point-in-time', 'срез на дату', 'фичи «как было на дату T» — чтобы не подсмотреть будущее (без утечки)'),
    ])
    stat = tbl('🧪 Статистика (эффект бонуса)', [
      ('Uplift', 'добавка', 'сколько действие (бонус) реально ДОБАВИЛО сверх «и так бы было»'),
      ('ATT', 'средний эффект на получивших', 'честная добавка после поправки на отбор'),
      ('CI', 'доверительный интервал', 'диапазон, где истинное значение с вероятностью 95%'),
      ('Propensity-matching', 'подбор похожих', 'сравниваем похожих игроков с бонусом и без — для честного эффекта'),
      ('п.п.', 'процентных пункта', 'разница в процентах (с 60% до 63% = +3 п.п.)'),
    ])
    content = ('<div class=topbar><div><div class=h1>Обозначения <em class=bd>· словарь терминов</em></div>'
      '<div class=lead>что значит каждое сокращение на дашборде — простыми словами, чтобы понял любой</div></div></div>'
      + eco + val + seg + pred + ml + stat)
    return layout('glossary', content)

# ============================ ФОРМУЛЫ РАСЧЁТОВ ============================
@app.route('/formulas')
def formulas():
    m = lambda s: f'<code style="font-family:\'JetBrains Mono\',monospace;font-size:12px;background:#f6f5f1;padding:1px 5px;border-radius:4px;white-space:nowrap">{escape(s)}</code>'
    def tbl(title, cols, rows):
        head = ''.join(f'<th>{escape(c)}</th>' for c in cols)
        body = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
        return (f'<div class=eyebrow style="margin-top:18px">{escape(title)}</div>'
                f'<div class=panel style="overflow-x:auto"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')

    agg = tbl('1. Базовые агрегаты игрока (player_features)', ['Метрика', 'Формула', 'Смысл'], [
      ['turnover (оборот)', m('Σ bet_amount'), 'сколько поставил'],
      ['net', m('wins_sum − turnover'), '+ в плюсе / − слил (со стороны игрока)'],
      ['recency_days', m("dateDiff('day', last_bet, today())"), 'дней с последней ставки'],
      ['freespin_ratio', m('freespins_bets / bets'), 'доля фриспин-ставок'],
      ['night_share', m('night_bets / bets'), 'доля ночной игры (час<6)'],
      ['bets_per_active_day', m('bets / active_days'), 'интенсивность'],
      ['lifecycle', m('recency: ≤7 active · ≤30 cooling · ≤60 at_risk · ≤90 dormant · >90 churned'), 'стадия'],
      ['is_depositor (борд)', m('dep_count > 0'), 'реальный депозитор'],
    ])
    eco = tbl('2. Экономика / KPI (/overview)', ['Метрика', 'Формула'], [
      ['GGR (доход казино)', m('Σ bet − Σ win')],
      ['RTP', m('Σ win / Σ bet × 100%')],
      ['Hold', m('GGR / Σ bet × 100%')],
      ['Кэш-нетто', m('депозиты(авто) − выводы(авто)')],
    ])
    ltv = tbl('3. LTV (ценность игрока)', ['Что', 'Формула'], [
      ['Кривая (реализ.)', m('avg(Σ dep в [0,H] дн от FTD)') + ' по дозревшим (age ≥ H)'],
      ['LTV ML (таргет)', m('Σ dep в [0,90] от FTD') + '; обучение на log1p, фичи только 1-й недели'],
      ['Квантили', m('******** Quantile(α=0.1/0.5/0.9)') + ' → P10/P50/P90'],
      ['Headroom', m('max(pred_ltv_d90 − dep_to_date, 0)')],
    ])
    dep = tbl('4. Депозиты и churn', ['Что', 'Формула'], [
      ['Конверсия #N→#N+1', m('count(n≥N+1) / count(n≥N)')],
      ['P(2-й деп, 30д) ML', m('таргет: ≥2 деп в 30 дн от FTD') + '; фичи только FTD-дня (без утечки)'],
      ['P(следующий деп)', m('таргет: депозит #k+1 в 30 дн') + '; фичи на момент депозита #k'],
      ['Churn (риск ухода)', m('срез T → нет ставки в (T, T+30]') + '; фичи строго created_at < T'],
      ['Личный ритм', m('expected_gap = span/(active_days−1)') + ', просрочка = recency/expected_gap'],
    ])
    eng = tbl('5. Движок офферов (player_actions)', ['Что', 'Формула'], [
      ['value_try (ценность)', m('депозитор ? max(pred_ltv_d90, dep_sum) : 0')],
      ['save_weight (вес стадии)', m('active .30 · cooling .70 · at_risk 1.0 · dormant .55 · churned .35')],
      ['priority (приоритет)', m('round( value_try × coalesce(p_churn, save_weight) )')],
      ['action', m('CONVERT · NUDGE · SAVE · WINBACK · NURTURE') + ' по lifecycle/депозитам'],
      ['bonus', m('freespin>0.4→фриспины · тир C/D или avg_bet≥200→VIP · ≤1 деп→релоад')],
    ])
    ses = tbl('6. Сессии (реконструкция)', ['Метрика', 'Формула'], [
      ['Длительность', m("round( dateDiff('second', min, max) / 60 )") + ' мин'],
      ['Net сессии', m('Σ win − Σ bet') + ' → 🟢/🔴'],
      ['Моментум', m('recent_net = Σ net за окно (7/14/30/90/всё)')],
      ['Live-алерт', m('pred_ltv_d90 ≥ 10000 AND net_сессии < 0')],
    ])
    dist = tbl('7. Распределения / бонусы / RFM', ['Что', 'Формула'], [
      ['Дециль LTV', m('11 − ntile(10) OVER (ORDER BY pred_ltv_d90)') + ' (D1 = топ-10%)'],
      ['Доля ценности', m('Σ LTV(дециль) / Σ LTV(все) × 100%')],
      ['Перцентиль деп.', m('quantile(p)(dep_sum)')],
      ['Бонус: отклик', m('% событий с депозитом в (бонус, +14д]')],
      ['Uplift ATT', m('mean(retained_treated − retained_control)') + ' по propensity-парам, CI бутстрэп'],
      ['RFM', m('R = 6−ntile(5)(recency) · F = ntile(5)(active_days) · M = ntile(5)(turnover)')],
    ])
    content = ('<div class=topbar><div><div class=h1>Формулы расчётов <em class=bd>· как считается</em></div>'
      '<div class=lead>все вычисления системы по слоям · '
      'условные: bet=ставка, dep=завершённый депозит, FTD=первый депозит, всё по account_type=normal</div></div></div>'
      + agg + eco + ltv + dep + eng + ses + dist
      + '<div class=lead style="margin-top:14px">⚠️ модели калиброваны на <b>ранжирование</b>, не на абсолютную вероятность — для приоритизации. '
      'Поля от today() (recency/lifecycle) замораживаются на дату сборки витрины.</div>')
    return layout('formulas', content)

# ============================ БОНУСЫ: ЭФФЕКТ ============================
@app.route('/bonus')
def bonus():
    up = {m: v for m, v in q("SELECT metric, value FROM bonus_uplift")[1]}
    eff = q("SELECT bonus_type, players, dep_resp_14d_pct, retained_30d_pct, bonus_events FROM bonus_effectiveness_t ORDER BY bonus_events DESC")[1]
    rec = q("SELECT rec_bonus, count() FROM player_bonus_ml GROUP BY rec_bonus ORDER BY count() DESC")[1]
    att = up.get('att_pp', 0); lo = up.get('ci_lo_pp', 0); hi = up.get('ci_hi_pp', 0)
    rt = up.get('retain_treated', 0) * 100; rc = up.get('retain_control', 0) * 100; raw = rt - rc
    nt = int(up.get('n_treated', 0)); nc = int(up.get('n_control', 0))
    cards = ('<div class=cards>'
      + scard('orange', '🧪', 'Честная добавка бонуса', f'{att:+.1f} п.п.', f'причинный эффект · возможен диапазон [{lo:+.1f}; {hi:+.1f}]')
      + scard('alert', '🎭', 'Сырая разница (обманчиво)', f'+{raw:.0f} п.п.', 'до поправки на «кому давали»')
      + scard('cream', '✅', 'Остались активны', f'{rt:.0f}%', f'с бонусом · без бонуса {rc:.0f}%')
      + scard('', '👥', 'С бонусом / без (сравнение)', f'{f(nt)} / {f(nc)}', 'группа «без» мала → оценка грубая')
      + '</div>')
    banner = ('<div class=banner style="margin:2px 0 16px">🧠 <b>Главный вывод:</b> сырой разрыв ретеншна '
      f'(+{raw:.0f} п.п.) почти весь — это <b>отбор</b> (бонусы дают и так активным игрокам). '
      f'После propensity-matching честная добавка бонуса = <b>{att:+.1f} п.п.</b>, '
      f'CI [{lo:+.1f}; {hi:+.1f}] пересекает ноль → значимого причинного эффекта на ретеншн не видно. '
      'Вероятно, часть бонус-бюджета уходит тем, кто остался бы и без бонуса.</div>')
    erows = ''
    for bt, pl, dr, ret, ev in eff:
        erows += (f'<tr><td>{escape(str(bt))}</td><td class=num>{f(pl)}</td><td class=num>{f(ev)}</td>'
                  f'<td class=num>{dr}%</td><td class=num>{ret}%</td></tr>')
    eff_panel = ('<div class=eyebrow>Эффективность по типу бонуса <span class=muted>наблюдательно · игроки пересекаются (один мог получить разные типы)</span></div>'
      '<div class=panel style="overflow-x:auto"><table><thead><tr>'
      '<th>Тип бонуса</th><th title="сколько разных игроков получали этот тип (один игрок может быть в нескольких типах)">Игроков*</th>'
      '<th title="сколько раз бонус выдавался всего">Сколько раз выдан</th>'
      '<th title="доля выдач, после которых игрок внёс депозит в течение 14 дней">Внёс депозит<br><span class=muted style="font-weight:400">в 14 дней после</span></th>'
      '<th title="доля выдач, после которых игрок сыграл хоть одну ставку в течение 30 дней — т.е. остался активен">Остался играть<br><span class=muted style="font-weight:400">в 30 дней после</span></th></tr></thead><tbody>' + erows + '</tbody></table></div>'
      '<div class=lead style="margin:6px 0 16px">* «Игроков» по типам пересекается — это НЕ разбиение базы. «Внёс депозит» и «Остался играть» — что было ПОСЛЕ бонуса (наблюдательно, не доказательство пользы — см. uplift выше). ⚠️ deposit-match / cashback по природе требуют депозита → их высокий отклик частично механический.</div>')
    nrec = sum(r[1] for r in rec)
    rrows = ''.join(f'<tr><td>{escape(str(b))}</td><td class=num>{f(n)}</td><td class=num>{round(100*n/(nrec or 1))}%</td></tr>' for b, n in rec)
    rec_panel = (f'<div class=eyebrow>Какой бонус советует модель <span class=muted>пробная · по {f(nrec)} игравшим из 39 010</span></div>'
      '<div class=panel style="overflow-x:auto"><table><thead><tr><th>Рекоменд. бонус</th><th>Игроков</th><th>% от оценённых</th></tr></thead><tbody>' + rrows + '</tbody></table></div>')
    content = ('<div class=topbar><div><div class=h1>Бонусы: эффект <em class=bd>· что работает и насколько</em></div>'
      '<div class=lead>что происходит с игроком после разных бонусов · и сколько бонус реально ДОБАВЛЯЕТ (отдельно от того, что его дают и так активным)</div></div></div>'
      + cards + banner + eff_panel + rec_panel)
    return layout('bonus', content)

# ============================ LTV-ПРОГНОЗ ============================
TIER_LBL = {'A': 'A · &lt;1k/нед', 'B': 'B · 1–3k', 'C': 'C · 3–10k', 'D': 'D · 10k+ 🐋'}
TIER_BG  = {'A': ('#f1f5f9', '#475569'), 'B': ('#dbeafe', '#1e40af'),
            'C': ('#fef9c3', '#854d0e'), 'D': ('#dcfce7', '#166534')}

def tier_badge(t):
    bg, fg = TIER_BG.get(t, ('#ededed', '#8a8a8a'))
    return f'<span class=badge style="background:{bg};color:{fg}">{TIER_LBL.get(t, t)}</span>'

@app.route('/ltv')
def ltv():
    curve = q("SELECT day, cohort_n, avg_cum_deposit, median_cum_deposit FROM ltv_curve ORDER BY day")[1]
    tiers = q("SELECT early_tier_D7, cohort_n, exp_d30, exp_d90, exp_d120 FROM ltv_tier_model ORDER BY early_tier_D7")[1]
    whales, whales_head = q("SELECT countIf(early_tier='D'), round(sumIf(ltv_headroom, early_tier='D')) FROM player_ltv")[1][0]
    young = q("SELECT count() FROM player_ltv WHERE early_tier IN ('C','D') AND days_since_ftd<=30")[1][0][0]
    tot_head = q("SELECT round(sum(ltv_headroom)) FROM player_ltv")[1][0][0]
    yw = q("SELECT casino_player_id, days_since_ftd, tier_provisional, early_tier, dep_d7, dep_to_date, pred_ltv_d90, ltv_headroom "
           "FROM player_ltv WHERE early_tier IN ('C','D') AND days_since_ftd<=30 "
           "ORDER BY pred_ltv_d90 DESC, dep_d7 DESC LIMIT 20")[1]

    d1 = (curve[0][2] if curve else 1) or 1   # guard от деления на 0
    cards = ('<div class=cards>'
      + scard('orange', '💎', 'Ожидаемый headroom', mn(tot_head), 'будущие депозиты сверх внесённого', spark([c[2] for c in curve]))
      + scard('cream', '🐋', 'Китов (тир D)', f(whales), f'headroom {mn(whales_head)}')
      + scard('', '🎯', 'Молодые киты', f(young), 'тир C/D, ≤30 дн — действовать сейчас')
      + scard('', '📈', 'LTV D120 / D1', f'×{round(curve[-1][2]/d1,1)}' if curve else '—', 'во столько растёт за 120 дн')
      + '</div>')

    crows = ''
    for day, n, avg, med in curve:
        crows += (f'<tr><td class=id>D{day}</td><td class=num>{f(n)}</td>'
                  f'<td class=num>{f(avg)} ₺</td><td class=num>{f(med)} ₺</td>'
                  f'<td class=num>×{round(avg/d1,2)}</td></tr>')
    curve_panel = ('<div class=eyebrow>Реальная LTV-кривая · накопленный депозит (TRY)</div>'
      '<div class=panel style="overflow-x:auto"><table><thead><tr>'
      '<th>День</th><th>Когорта</th><th>Средний LTV</th><th title="устойчива к китам">Медиана</th><th>×D1</th>'
      '</tr></thead><tbody>' + crows + '</tbody></table></div>'
      '<div class=lead style="margin:6px 0 18px">📖 <b>Как читать:</b> строка «D30» = в среднем игрок к 30-му дню от первого депозита внёс столько-то. '
      '«Когорта» = на скольких посчитано (только дозревшие до этого дня, чтобы не занижать). «×D1» = во сколько раз больше, чем в 1-й день. '
      '<b>Медиана</b> устойчивее среднего: среднее ≫ медианы → LTV тащат киты.</div>')

    trows = ''
    for t, n, e30, e90, e120 in tiers:
        trows += (f'<tr><td>{tier_badge(t)}</td><td class=num>{f(n)}</td>'
                  f'<td class=num>{f(e30)} ₺</td><td class=num>{f(e90)} ₺</td><td class=num>{f(e120)} ₺</td></tr>')
    tier_panel = ('<div class=eyebrow>Модель v0 · ранний тир (депозит 1-й недели) → ожидаемый LTV</div>'
      '<div class=panel style="overflow-x:auto"><table><thead><tr>'
      '<th>Тир</th><th>Когорта (обучение)</th><th>Ожид. D30</th><th>Ожид. D90</th><th>Ожид. D120</th>'
      '</tr></thead><tbody>' + trows + '</tbody></table></div>'
      '<div class=lead style="margin:6px 0 18px">v0 — лукап по тиру. Следующий шаг: ********-регрессор '
      '(непрерывный depₐ7 + ритм) уберёт потолок среднего.</div>')

    wrows = ''
    for pid, age, prov, t, d7, dtot, p90, head in yw:
        provb = ' <span class=badge style="background:#fef9c3;color:#854d0e">провизорно &lt;7д</span>' if prov else ''
        wrows += (f'<tr onclick="location.href=\'/player/{pid}\'"><td class=id>{pid}{provb}</td>'
                  f'<td class=num>{f(age)}д</td><td>{tier_badge(t)}</td>'
                  f'<td class=num>{f(d7)} ₺</td><td class=num>{f(dtot)} ₺</td>'
                  f'<td class="num pos">{f(p90)} ₺</td><td class=num>{f(head)} ₺</td></tr>')
    young_panel = ('<div class=eyebrow id=act>🎯 Молодые киты — действовать сейчас</div>'
      '<div class=lead style="margin:-2px 0 8px">Новички (≤30 дн с FTD), предсказанные в тир C/D. Клик — карточка.</div>'
      '<div class=panel style="overflow-x:auto"><table><thead><tr>'
      '<th>ID</th><th>Возраст</th><th>Тир</th><th>Депозит 7д</th><th>Внесено всего</th>'
      '<th>Предсказ. D90</th><th>Headroom</th>'
      '</tr></thead><tbody>' + wrows + '</tbody></table></div>')

    content = ('<div class=topbar><div><div class=h1>LTV-прогноз <em class=bd>· v0</em></div>'
      '<div class=lead>сколько игрок принесёт депозитами за 90 дней: реальная кривая по базе + per-player ML-прогноз + список «молодых китов, действовать сейчас»</div></div></div>'
      + cards + curve_panel + tier_panel + young_panel)
    return layout('ltv', content)

_COHORTS_CACHE = {}   # кэш тяжёлой страницы когорт; ключ = дата данных (data_asof)

@app.route('/cohorts')
def cohorts():
    N = "casino_player_id IN (SELECT casino_player_id FROM users WHERE account_type='normal')"
    RB = "transaction_type IN ('bet','freespins_bet')"; RW = "transaction_type IN ('win','freespins_win')"
    SPEC = [
     ('A · Время','A1','Регистрации по месяцам','time',"SELECT toStartOfMonth(toTimezone(reg_date,'Europe/Istanbul')) m, count() FROM users WHERE account_type='normal' AND reg_date IS NOT NULL GROUP BY m ORDER BY m"),
     ('A · Время','A2','Когорта первой ставки','time',f"WITH act AS (SELECT casino_player_id, min(toMonday(toTimezone(created_at,'Europe/Istanbul'))) fw FROM game_transactions WHERE {RB} AND {N} GROUP BY casino_player_id) SELECT fw, count() FROM act GROUP BY fw ORDER BY fw"),
     ('A · Время','A3','Депозиторы по месяцу FTD','time',"SELECT toStartOfMonth(toTimezone(ftd_date,'Europe/Istanbul')) m, count() FROM users WHERE account_type='normal' AND ftd_date IS NOT NULL GROUP BY m ORDER BY m"),
     ('A · Время','A3a','Возраст аккаунта','bar',"SELECT multiIf(d<=7,'≤7д',d<=30,'8-30д',d<=90,'31-90д',d<=180,'91-180д','180д+') t, count() FROM (SELECT dateDiff('day',toDate(reg_date),today()) d FROM users WHERE account_type='normal' AND reg_date IS NOT NULL) GROUP BY t ORDER BY min(d)"),
     ('A · Время','A3b','Скорость активации','bar',f"WITH fb AS (SELECT casino_player_id, min(toDate(created_at)) f FROM game_transactions WHERE {RB} GROUP BY casino_player_id) SELECT multiIf(lag=0,'в день рег',lag<=1,'1 день',lag<=7,'2-7 дней','8+ дней') s, count() FROM (SELECT dateDiff('day',toDate(u.reg_date),fb.f) lag FROM users u JOIN fb USING(casino_player_id) WHERE u.account_type='normal' AND u.reg_date IS NOT NULL) GROUP BY s ORDER BY min(lag)"),
     ('B · Канал','B4','Тип аффилиата','donut',"SELECT if(affiliate_account_type='','(нет)',affiliate_account_type) t, count() FROM users WHERE account_type='normal' GROUP BY t ORDER BY count() DESC"),
     ('B · Канал','B5','Топ аффилиатов','table',"SELECT affiliate_code, count() FROM users WHERE account_type='normal' AND affiliate_code!='' GROUP BY affiliate_code ORDER BY count() DESC LIMIT 12"),
     ('B · Канал','B6','Топ источников','table',"SELECT substring(registration_source,1,42), count() FROM users WHERE account_type='normal' GROUP BY registration_source ORDER BY count() DESC LIMIT 10"),
     ('B · Канал','B7','Бонус-кампании','table',f"SELECT replaceOne(payment_method,'campaign:',''), uniqExact(casino_player_id) FROM money_transactions WHERE payment_method LIKE 'campaign:%' AND payment_method!='campaign:undefined' AND {N} GROUP BY payment_method ORDER BY 2 DESC LIMIT 10"),
     ('C · Деньги','C8','Депозитор vs нет','donut',"SELECT if(dep_count>0,'депозитор','не депозитор') s, count() FROM player_features WHERE account_type='normal' GROUP BY s ORDER BY 2 DESC"),
     ('C · Деньги','C9','Тир FTD','bar',"SELECT multiIf(ftd_date IS NULL,'нет',ftd_amount<=50,'≤50₺',ftd_amount<=200,'50-200₺',ftd_amount<=1000,'200-1000₺','1000₺+') t, count() FROM users WHERE account_type='normal' GROUP BY t ORDER BY min(coalesce(ftd_amount,0))"),
     ('C · Деньги','C10','Кол-во депозитов','bar',f"WITH m AS (SELECT casino_player_id, countIf(type IN ('deposit','manual_deposit') AND status='completed') c FROM money_transactions GROUP BY casino_player_id) SELECT multiIf(c=0,'0',c=1,'1',c<=3,'2-3',c<=10,'4-10','10+') s, count() FROM (SELECT u.casino_player_id, ifNull(m.c,0) c FROM users u LEFT JOIN m USING(casino_player_id) WHERE u.account_type='normal') GROUP BY s ORDER BY s"),
     ('C · Деньги','C11','Способ оплаты','table',f"SELECT payment_method, uniqExact(casino_player_id) FROM money_transactions WHERE type IN ('deposit','manual_deposit') AND payment_method NOT LIKE 'campaign:%' AND payment_method!='' AND {N} GROUP BY payment_method ORDER BY 2 DESC LIMIT 10"),
     ('C · Деньги','C12','Платёжное трение','bar',f"WITH m AS (SELECT casino_player_id, countIf(type IN ('deposit','manual_deposit')) r, countIf(type IN ('deposit','manual_deposit') AND status IN ('rejected','failed')) fl FROM money_transactions GROUP BY casino_player_id) SELECT multiIf(r=0,'не пытался',fl=0,'без отказов',fl*2>=r,'много отказов','были отказы') s, count() FROM (SELECT u.casino_player_id, ifNull(m.r,0) r, ifNull(m.fl,0) fl FROM users u LEFT JOIN m USING(casino_player_id) WHERE u.account_type='normal') GROUP BY s ORDER BY 2 DESC"),
     ('C · Деньги','C13','Winner / Loser','bar',f"WITH pp AS (SELECT casino_player_id, sumIf(win_amount,{RW})-sumIf(bet_amount,{RB}) net FROM game_transactions GROUP BY casino_player_id) SELECT multiIf(net>1000,'плюс >1k',net>0,'плюс 0-1k',net>-1000,'минус 0-1k','минус >1k') s, count() FROM pp WHERE {N} GROUP BY s ORDER BY min(net)"),
     ('C · Деньги','C14a','Поведение выводов','bar',f"WITH m AS (SELECT casino_player_id, sumIf(amount,type IN ('withdrawal','manual_withdrawal') AND status='completed') w, sumIf(amount,type IN ('deposit','manual_deposit') AND status='completed') d FROM money_transactions GROUP BY casino_player_id) SELECT multiIf(w=0,'не выводил',d=0,'вывод бонусов',w>d,'вывел > внёс','вывел < внёс') s, count() FROM (SELECT u.casino_player_id, ifNull(m.w,0) w, ifNull(m.d,0) d FROM users u LEFT JOIN m USING(casino_player_id) WHERE u.account_type='normal') GROUP BY s ORDER BY 2 DESC"),
     ('C · Деньги','C14b','Состояние баланса','donut',"SELECT multiIf(balance>0 AND bonus_balance>0,'кэш+бонус',balance>0,'только кэш',bonus_balance>0,'только бонус','пусто') s, count() FROM users WHERE account_type='normal' GROUP BY s ORDER BY 2 DESC"),
     ('D · Вовлечённость','D15','Активных дней','bar',f"WITH pp AS (SELECT casino_player_id, uniqExact(toDate(toTimezone(created_at,'Europe/Istanbul'))) d FROM game_transactions WHERE {RB} GROUP BY casino_player_id) SELECT multiIf(d=1,'1 день',d<=3,'2-3 дня',d<=7,'4-7 дн',d<=30,'8-30 дн','30+ дн') s, count() FROM pp WHERE {N} GROUP BY s ORDER BY min(d)"),
     ('D · Вовлечённость','D16','Кол-во ставок','bar',f"WITH pp AS (SELECT casino_player_id, countIf({RB}) b FROM game_transactions GROUP BY casino_player_id HAVING b>0) SELECT multiIf(b<=50,'≤50',b<=200,'51-200',b<=1000,'201-1k',b<=5000,'1k-5k','5k+') s, count() FROM pp WHERE {N} GROUP BY s ORDER BY min(b)"),
     ('D · Вовлечённость','D17','Средняя ставка','bar',f"WITH pp AS (SELECT casino_player_id, avgIf(bet_amount,{RB}) a FROM game_transactions GROUP BY casino_player_id HAVING a>0) SELECT multiIf(a<=5,'≤5₺',a<=50,'5-50₺',a<=200,'50-200₺',a<=1000,'200-1k₺','1k₺+ VIP') s, count() FROM pp WHERE {N} GROUP BY s ORDER BY min(a)"),
     ('D · Вовлечённость','D18','На свои или бонусы','donut',f"WITH pp AS (SELECT casino_player_id, countIf(transaction_type='freespins_bet') fs, countIf(transaction_type='bet') rb FROM game_transactions GROUP BY casino_player_id HAVING (fs+rb)>0) SELECT multiIf(rb=0,'только бонусы',fs=0,'только реал',fs>rb,'в осн. бонусы','в осн. реал') s, count() FROM pp WHERE {N} GROUP BY s ORDER BY 2 DESC"),
     ('D · Вовлечённость','D19a','Интенсивность','bar',f"WITH pp AS (SELECT casino_player_id, countIf({RB})/uniqExact(toDate(created_at)) b FROM game_transactions GROUP BY casino_player_id HAVING b>0) SELECT multiIf(b<=20,'≤20',b<=100,'21-100',b<=500,'101-500',b<=2000,'501-2k','2k+ грайнд') s, count() FROM pp WHERE {N} GROUP BY s ORDER BY min(b)"),
     ('D · Вовлечённость','D19b','Время игры (час)','area',f"SELECT toHour(toTimezone(created_at,'Europe/Istanbul')) h, count() FROM game_transactions WHERE {RB} AND {N} GROUP BY h ORDER BY h"),
     ('E · Игра','E20','Разнообразие игр','bar',f"WITH pp AS (SELECT casino_player_id, uniqExact(game_uuid) g FROM game_transactions WHERE {RB} AND game_uuid!='' GROUP BY casino_player_id) SELECT multiIf(g=1,'1 игра',g<=3,'2-3',g<=10,'4-10',g<=30,'11-30','30+') s, count() FROM pp WHERE {N} GROUP BY s ORDER BY min(g)"),
     ('E · Игра','E21','Хиты vs нишевые','donut',f"WITH hits AS (SELECT game_uuid FROM game_transactions WHERE {RB} AND game_uuid!='' GROUP BY game_uuid ORDER BY uniqExact(casino_player_id) DESC LIMIT 10), pp AS (SELECT casino_player_id, countIf(game_uuid IN hits) h, count() t FROM game_transactions WHERE {RB} AND game_uuid!='' GROUP BY casino_player_id HAVING t>0) SELECT multiIf(h=0,'только нишевые',h=t,'только хиты','смешанно') s, count() FROM pp WHERE {N} GROUP BY s ORDER BY 2 DESC"),
     ('E · Игра','E22','Провайдер','donut',f"SELECT aggregator, uniqExact(casino_player_id) FROM game_transactions WHERE {RB} AND {N} GROUP BY aggregator ORDER BY 2 DESC"),
     ('E · Игра','E23','Топ-12 игр','table',f"SELECT {GN()}, uniqExact(casino_player_id) FROM game_transactions WHERE {RB} AND game_uuid!='' AND {N} GROUP BY game_uuid ORDER BY 2 DESC LIMIT 12"),
     ('F · Цикл','F24','Recency-стадия','bar',f"WITH pp AS (SELECT casino_player_id, dateDiff('day',toDate(max(created_at)),today()) r FROM game_transactions GROUP BY casino_player_id) SELECT multiIf(r<=7,'активен',r<=30,'остывает',r<=60,'под риском',r<=90,'спящий','отток') s, count() FROM pp WHERE {N} GROUP BY s ORDER BY min(r)"),
     ('F · Цикл','F25','activity_status','bar',"SELECT activity_status, count() FROM users WHERE account_type='normal' GROUP BY activity_status ORDER BY count() DESC"),
     ('F · Цикл','F26','Стадия активации','donut',f"WITH played AS (SELECT DISTINCT casino_player_id FROM game_transactions WHERE {RB}) SELECT if(casino_player_id IN played,'играл','не активирован') s, count() FROM users WHERE account_type='normal' GROUP BY s ORDER BY 2 DESC"),
     ('F · Цикл','F26a','Реактивация','bar',f"WITH days AS (SELECT casino_player_id, toDate(created_at) d FROM game_transactions WHERE {RB} GROUP BY casino_player_id, d), gaps AS (SELECT casino_player_id, max(if(prev=toDate('1970-01-01'),0,dateDiff('day',prev,d))) g FROM (SELECT casino_player_id, d, lagInFrame(d) OVER (PARTITION BY casino_player_id ORDER BY d) prev FROM days) GROUP BY casino_player_id) SELECT multiIf(g>=30,'верн. 30д+',g>=14,'верн. 14-30д','без пауз') s, count() FROM gaps WHERE {N} GROUP BY s ORDER BY 2 DESC"),
     ('G · Композит','G27','RFM-сегменты','bar',"WITH s AS (SELECT 6-ntile(5) OVER (ORDER BY recency_days) R, ntile(5) OVER (ORDER BY active_days) F, ntile(5) OVER (ORDER BY turnover) M FROM player_features WHERE account_type='normal' AND turnover>0) SELECT multiIf(R>=4 AND F>=4 AND M>=4,'Champions',R>=3 AND F>=3,'Loyal',R>=4 AND F<=2,'New',R<=2 AND F>=4 AND M>=4,'Cant-Lose',R<=2 AND F>=3,'At-Risk',R<=2,'Hibernating','Need-Att') seg, count() FROM s GROUP BY seg ORDER BY 2 DESC"),
     ('G · Композит','G28','Value × Lifecycle','table',f"WITH pp AS (SELECT casino_player_id, sumIf(bet_amount,{RB}) t, dateDiff('day',toDate(max(created_at)),today()) r FROM game_transactions GROUP BY casino_player_id), s AS (SELECT if(t>=quantile(0.9)(t) OVER(),'High','Rest') v, multiIf(r<=30,'активен',r<=90,'под риском','отток') l FROM pp WHERE {N}) SELECT concat(v,' · ',l), count() FROM s GROUP BY 1 ORDER BY 2 DESC"),
     ('G · Композит','G29a','Канал × удержание','table',f"WITH pp AS (SELECT casino_player_id, dateDiff('day',toDate(max(created_at)),today()) r FROM game_transactions GROUP BY casino_player_id) SELECT concat(if(u.affiliate_account_type='','нет',u.affiliate_account_type),' — ',toString(round(100*countIf(pp.r<=30)/count(),1)),'%'), count() FROM users u LEFT JOIN pp USING(casino_player_id) WHERE u.account_type='normal' GROUP BY u.affiliate_account_type ORDER BY 2 DESC"),
    ]
    asof = str(data_asof())
    if asof in _COHORTS_CACHE:
        G, body = _COHORTS_CACHE[asof]          # данные не менялись — отдаём из кэша (мгновенно)
    else:
        groups = {}
        for grp, cid, title, typ, sql in SPEC:
            rws = q(sql)[1]
            if typ == 'table':
                item = {'id': cid, 'title': title, 'type': typ, 'rows': [[str(r[0]), r[1]] for r in rws]}
            else:
                item = {'id': cid, 'title': title, 'type': typ,
                        'data': [{'label': (str(r[0])[:10] if typ in ('time','area') else str(r[0])), 'value': r[1]} for r in rws]}
            groups.setdefault(grp, []).append(item)
        G = [{'name': g, 'items': items} for g, items in groups.items()]
        body = ''
        for g in G:
            body += f'<div class=eyebrow>{g["name"]}</div><div class=cohgrid>'
            for it in g['items']:
                if it['type'] == 'table':
                    mx = max(([r[1] for r in it['rows']] or [1])) or 1
                    rh = ''.join(f'<div class=trow><i style="width:{round(r[1]/mx*100)}%"></i><span class=tl>{escape(str(r[0]))}</span><span class=tv>{f(r[1])}</span></div>' for r in it['rows'])
                    body += f'<div class=cohcard><div class=cid>{it["id"]}</div><h4>{escape(it["title"])}</h4><div class=tbl>{rh}</div></div>'
                else:
                    body += f'<div class=cohcard><div class=cid>{it["id"]}</div><h4>{escape(it["title"])}</h4><div class=cohchart id="ch_{it["id"]}"></div></div>'
            body += '</div>'
        _COHORTS_CACHE.clear()                  # держим только последнюю дату данных
        _COHORTS_CACHE[asof] = (G, body)
    DATA = jsdump({'groups': G})
    he = ("<script src='https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js'></script>"
      "<style>.cohgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}"
      ".cohcard{background:var(--canvas);border:1px solid var(--hair);border-radius:12px;padding:14px 16px}"
      ".cohcard .cid{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:10px;color:var(--muted)}"
      ".cohcard h4{font-size:14px;font-weight:600;margin:2px 0 8px}"
      ".cohchart{width:100%;height:180px}"
      ".tbl{display:flex;flex-direction:column;gap:3px}"
      ".trow{position:relative;display:flex;justify-content:space-between;padding:5px 9px;font-size:12px;border-radius:6px;overflow:hidden}"
      ".trow i{position:absolute;left:0;top:0;bottom:0;background:rgba(37,99,235,.10)}"
      ".trow .tl{position:relative;z-index:1;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:70%}"
      ".trow .tv{position:relative;z-index:1;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;color:var(--primary)}</style>")
    top = ("<div class=topbar><div><div class=h1>Все когорты <em>· 36 срезов</em></div>"
      "<div class=lead>каталог всех способов нарезать базу на группы — для кампаний и анализа · клик по сегменту ведёт в список его игроков<br>"
      "⚠️ у разных срезов разный знаменатель: общие — по 39 010, денежные (депозиты/выводы) — только по игрокам с транзакциями (~31 837), игровые — по игравшим (~27 967). Сравнивать высоту баров между карточками напрямую нельзя.</div></div>"
      "<div class=pills><span class='pill live'>live</span></div></div>")
    js = "<script>const CD=" + DATA + ";" + COHORTS_JS + "</script>"
    return layout('cohorts', top + body, head_extra=he).replace('</body>', js + '</body>')

# ============================ ARCHETYPES (похожие игроки по поведению) ============================
PERSONA_SQL = ("multiIf(NOT ever_played,'💤 Не играл',"
  "active_days=1,'💨 Разовый',"
  "avg_bet>=1000,'🐋 Хайроллер',"
  "freespin_ratio>=0.5,'🎁 Бонусник',"
  "bets_per_active_day>=300 AND active_days>=4,'⚙️ Грайндер',"
  "night_share>=0.5,'🦉 Ночной',"
  "distinct_games>=10,'🧭 Исследователь',"
  "distinct_games<=2 AND active_days>=2,'📌 Моногам',"
  "'🎰 Казуал')")
PERSONA_DESC = {
 '🐋 Хайроллер': 'крупные ставки (≥1000 ₺), почти все депозиторы',
 '⚙️ Грайндер': 'молотят объём — 300+ ставок в день, главная ценность',
 '🧭 Исследователь': 'пробует много разных игр (10+)',
 '📌 Моногам': 'залип на 1–2 играх, возвращается',
 '🎁 Бонусник': 'играет в основном на фриспины/бонусы',
 '🦉 Ночной': 'больше половины ставок — ночью',
 '🎰 Казуал': 'нерегулярно, низкая интенсивность',
 '💨 Разовый': 'один активный день — пришёл и ушёл',
 '💤 Не играл': 'зарегистрировался, но не сделал ни ставки'}

@app.route('/archetypes')
def archetypes():
    rows = q(f"""SELECT persona, count() c, round(avg(avg_bet)) ab, round(avg(active_days),1) ad,
        round(avg(distinct_games),1) ag, round(100*countIf(is_depositor)/count()) dp, round(sum(turnover)/1e6,1) tm
      FROM (SELECT {PERSONA_SQL} persona, avg_bet, active_days, distinct_games, is_depositor, turnover
        FROM player_features WHERE account_type='normal') GROUP BY persona""")[1]
    total = sum(r[1] for r in rows) or 1
    rows = sorted(rows, key=lambda r: r[1], reverse=True)
    maxc = max((r[1] for r in rows), default=1)
    cards = ''
    for persona, c, ab, ad, ag, dp, tm in rows:
        emoji, name = (persona.split(' ', 1) + [''])[:2]
        desc = PERSONA_DESC.get(persona, '')
        pct = round(100*c/total, 1)
        cards += (f'<div class=arcard><div class=arhead><span class=arem>{emoji}</span>'
          f'<div class=arttl><div class=arname>{name}</div><div class=ardesc>{desc}</div></div>'
          f'<div class=arn><b>{f(c)}</b><span>{pct}%</span></div></div>'
          f'<div class=arbar><i style="width:{round(c/maxc*100)}%"></i></div>'
          f'<div class=arstats><div><span>ср.ставка</span><b>{f(ab)} ₺</b></div>'
          f'<div><span>акт. дней</span><b>{ad}</b></div><div><span>игр</span><b>{ag}</b></div>'
          f'<div><span>депозиторов</span><b>{f(dp)}%</b></div><div><span>оборот</span><b>{tm} Mn</b></div></div></div>')
    he = ("<style>.argrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:14px;margin-top:18px}"
      ".arcard{background:var(--canvas);border:1px solid var(--hair);border-radius:14px;padding:16px 18px}"
      ".arhead{display:flex;align-items:center;gap:12px}.arem{font-size:30px;line-height:1}"
      ".arttl{flex:1;min-width:0}.arname{font-weight:700;font-size:16px}.ardesc{color:var(--steel);font-size:12.5px;margin-top:2px}"
      ".arn{text-align:right}.arn b{font-size:20px;font-weight:800;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace}.arn span{display:block;font-size:11px;color:var(--steel)}"
      ".arbar{height:6px;background:var(--cream-d);border-radius:3px;overflow:hidden;margin:12px 0}"
      ".arbar i{display:block;height:100%;background:linear-gradient(90deg,#2563eb,#60a5fa)}"
      ".arstats{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.arstats>div{text-align:center}"
      ".arstats span{display:block;font-size:10px;color:var(--steel);text-transform:uppercase;letter-spacing:.3px}"
      ".arstats b{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:13px}</style>")
    top = ("<div class=topbar><div><div class=h1>Архетипы игроков <em>· похожие по поведению</em></div>"
      f"<div class=lead>{f(total)} реальных игроков сгруппированы в типажи по тому, как и во что играют</div></div>"
      "<div class=pills><span class='pill live'>live</span></div></div>")
    return layout('archetypes', top + '<div class=argrid>' + cards + '</div>', head_extra=he)

# ============================ BONUS CAMPAIGNS (сегменты для бонус-рассылок) ============================
# key, icon, name, кому, оффер, SQL-условие (поверх account_type='normal')
SEGMENTS = [
 ('s1','🎯','2-й депозит','один депозит, ещё активен (≤30 дн)','бонус на 2-й депозит / релоад-матч',
   "is_depositor AND dep_count=1 AND recency_days<=30"),
 ('s2','🚨','VIP остывает','депозитор, ср.ставка ≥200₺, тишина 14–60 дн','персональный VIP-бонус удержания',
   "is_depositor AND avg_bet>=200 AND recency_days BETWEEN 14 AND 60"),
 ('s3','💤','Спящий депозитор','платил, неактивен 30–90 дн','win-back: фриспины / кэшбэк',
   "is_depositor AND recency_days BETWEEN 30 AND 90"),
 ('s4','🎁','Фриспин-любитель','играет на фриспины, активен (≤14 дн)','фриспины на любимом провайдере',
   "freespin_ratio>=0.5 AND recency_days<=14"),
 ('s5','🐋','Хайроллер активный','ставки ≥1000₺, активен (≤30 дн)','эксклюзивный хайроллер-бонус',
   "avg_bet>=1000 AND recency_days<=30"),
 ('s6','🌱','Растущий лояльный','2+ депозита, активен (≤14 дн)','лояльность-бонус / VIP-апгрейд',
   "dep_count>=2 AND recency_days<=14"),
 ('s7','💸','Играет, но не платит','играл, без депозита, активен (≤14 дн)','депозит-бонус для конверсии',
   "NOT is_depositor AND ever_played AND recency_days<=14 AND active_days>=2"),
 ('s8','❄️','Почти ушёл','играл 2+ дней, тишина 7–21 дн','реактивация — бонус «вернись»',
   "ever_played AND recency_days BETWEEN 7 AND 21 AND active_days>=2"),
]
SEG_MAP = {s[0]: s for s in SEGMENTS}

@app.route('/campaigns')
def campaigns():
    counts = q("SELECT " + ', '.join(f"countIf({s[5]})" for s in SEGMENTS) +
               " FROM player_features WHERE account_type='normal'")[1][0]
    cards = ''
    for (key, ic, name, who, offer, _), cnt in zip(SEGMENTS, counts):
        cards += (f'<div class=cmcard><div class=cmhead><span class=cmem>{ic}</span>'
          f'<div class=cmttl><div class=cmname>{name}</div><div class=cmwho>{who}</div></div>'
          f'<div class=cmn><b>{f(cnt)}</b><span>игроков</span></div></div>'
          f'<div class=cmoffer><span class=cmlbl>💡 оффер</span>{offer}</div>'
          f'<a class=cmbtn href="/?seg={key}">Список игроков →</a></div>')
    he = ("<style>.cmgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:14px;margin-top:18px}"
      ".cmcard{background:var(--canvas);border:1px solid var(--hair);border-radius:14px;padding:16px 18px;display:flex;flex-direction:column}"
      ".cmhead{display:flex;align-items:center;gap:12px}.cmem{font-size:28px;line-height:1}"
      ".cmttl{flex:1;min-width:0}.cmname{font-weight:700;font-size:16px}.cmwho{color:var(--steel);font-size:12.5px;margin-top:2px}"
      ".cmn{text-align:right}.cmn b{font-size:22px;font-weight:800;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;color:var(--primary)}.cmn span{display:block;font-size:11px;color:var(--steel)}"
      ".cmoffer{background:var(--cream);border:1px solid var(--beige);border-radius:9px;padding:9px 12px;margin:13px 0;font-size:13px;line-height:1.4}"
      ".cmlbl{display:block;font-size:10.5px;color:var(--steel);text-transform:uppercase;letter-spacing:.4px;margin-bottom:2px}"
      ".cmbtn{margin-top:auto;display:inline-block;text-align:center;background:var(--primary);color:#fff;border-radius:9px;padding:10px;font-size:13.5px;font-weight:600;text-decoration:none}"
      ".cmbtn:hover{filter:brightness(1.08)}</style>")
    top = ("<div class=topbar><div><div class=h1>Бонус-кампании <em>· сегменты для рассылок</em></div>"
      "<div class=lead>группы похожих игроков под конкретный оффер · клик «Список игроков» — кому слать</div></div>"
      "<div class=pills><span class='pill live'>live</span></div></div>")
    return layout('campaigns', top + '<div class=cmgrid>' + cards + '</div>', head_extra=he)

# ============================ GAMES (когорты по играм) ============================
@app.route('/games')
def games():
    NRM = "casino_player_id IN (SELECT casino_player_id FROM users WHERE account_type='normal')"
    rows = q(f"""SELECT {GN()} g, uniqExact(casino_player_id) players, any(provider) prov,
        round(sum(turnover)) turn, round(avg(days_played),1) days
      FROM player_games WHERE {NRM} GROUP BY game_uuid ORDER BY players DESC LIMIT 18""")[1]
    cards = ''
    for g, players, prov, turn, days in rows:
        cards += (f'<div class=cmcard><div class=cmhead><span class=cmem>🎮</span>'
          f'<div class=cmttl><div class=cmname>{escape(str(g))}</div>'
          f'<div class=cmwho>{escape(str(prov or "—"))} · оборот {float(turn or 0)/1e6:.1f} Mn · ср. {days} дн</div></div>'
          f'<div class=cmn><b>{f(players)}</b><span>игроков</span></div></div>'
          f'<div class=cmoffer><span class=cmlbl>💡 оффер</span>фриспины на эту игру</div>'
          f'<a class=cmbtn href="/?game={escape(str(g))}">Список игроков →</a></div>')
    he = ("<style>.cmgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px;margin-top:18px}"
      ".cmcard{background:var(--canvas);border:1px solid var(--hair);border-radius:14px;padding:16px 18px;display:flex;flex-direction:column}"
      ".cmhead{display:flex;align-items:center;gap:12px}.cmem{font-size:26px;line-height:1}"
      ".cmttl{flex:1;min-width:0}.cmname{font-weight:700;font-size:14px;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
      ".cmwho{color:var(--steel);font-size:12px;margin-top:2px}"
      ".cmn{text-align:right}.cmn b{font-size:22px;font-weight:800;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;color:var(--primary)}.cmn span{display:block;font-size:11px;color:var(--steel)}"
      ".cmoffer{background:var(--cream);border:1px solid var(--beige);border-radius:9px;padding:9px 12px;margin:13px 0;font-size:13px}"
      ".cmlbl{display:block;font-size:10.5px;color:var(--steel);text-transform:uppercase;letter-spacing:.4px;margin-bottom:2px}"
      ".cmbtn{margin-top:auto;display:inline-block;text-align:center;background:var(--primary);color:#fff;border-radius:9px;padding:10px;font-size:13.5px;font-weight:600;text-decoration:none}"
      ".cmbtn:hover{filter:brightness(1.08)}</style>")
    top = ("<div class=topbar><div><div class=h1>Игры <em>· сегменты для рассылок</em></div>"
      "<div class=lead>топ игр · клик «Список игроков» — кому слать фриспины на эту игру · имена внутренние (uuid)</div></div>"
      "<div class=pills><span class='pill live'>live</span></div></div>")
    return layout('games', top + '<div class=cmgrid>' + cards + '</div>', head_extra=he)

# ============================ AFFILIATES (аффилиаты: обзор + детальная карточка) ============================
AFF_OV_SORTS = {'players','ftd','ftd_sum','dep','wd','net_profit','turn','ggr','ggr_real','ngr','hold'}
AFF_SORTS = {'casino_player_id','reg_date','ftd_amount','dep_count','dep_sum','wd_count','wd_sum','net_dep','turnover','net','recency_days'}

def _aff_clean(code):
    return ''.join(c for c in (code or '') if c.isalnum() or c == '_')[:24]

@app.route('/affiliates')
def affiliates():
    sort = request.args.get('sort','players'); sort = sort if sort in AFF_OV_SORTS else 'players'
    asc = request.args.get('dir') == 'asc'
    # 1) витрина: игроки, FTD, оборот
    _, pf = q("""SELECT affiliate_code, count() players, countIf(ftd_amount>0) ftd,
        round(sumIf(ftd_amount, ftd_amount>0)) ftd_sum, round(sum(turnover)) turn
      FROM player_features WHERE account_type='normal' AND affiliate_code!='' GROUP BY affiliate_code""")
    # 2) деньги по спеке казино: Deposits (deposit), Withdrawals ABS (withdrawal), Bonus cost
    _, mny = q(f"""SELECT u.affiliate_code,
        round(sumIf(m.amount, m.{DEP_OK}),2) dep,
        round(sumIf(abs(m.amount), m.{WD_OK}),2) wd,
        round(sumIf(abs(m.amount), m.{BONUS_OK}),2) bonus
      FROM money_transactions m
      INNER JOIN (SELECT casino_player_id, affiliate_code FROM users
                  WHERE account_type='normal' AND affiliate_code!='') u USING(casino_player_id)
      GROUP BY u.affiliate_code""")
    M = {r[0]: r for r in mny}
    G = aff_ggr_split()
    data = []
    for code, players, ftd, ftd_sum, turn in pf:
        mr = M.get(code)
        dep = float(mr[1] or 0) if mr else 0.0
        wd = float(mr[2] or 0) if mr else 0.0
        bonus = float(mr[3] or 0) if mr else 0.0
        rb, rw, fb, fw = G.get(code, (0.0, 0.0, 0.0, 0.0))
        ggr = (rb + fb) - (rw + fw); ggr_real = rb - rw
        ngr = calc_ngr(ggr, bonus, 0.0, aff_commission_row(dep - wd, code))
        turn_f = float(turn or 0)
        data.append({'code': code, 'players': players, 'ftd': ftd, 'ftd_sum': float(ftd_sum or 0),
                     'dep': dep, 'wd': wd, 'net_profit': dep - wd, 'turn': turn_f, 'ggr': ggr,
                     'ggr_real': ggr_real, 'ngr': ngr,
                     'hold': round(100 * ggr / turn_f, 1) if turn_f else 0.0,
                     'players_win': ggr_real < 0, 'cash_drain': (dep - wd) < 0})
    data.sort(key=lambda d: (d[sort] is None, d[sort]), reverse=not asc)  # None-safe (напр. reg_date=NULL)
    risk_only = request.args.get('risk') == '1'
    n_pwin = sum(1 for d in data if d['players_win'])
    n_cash = sum(1 for d in data if d['cash_drain'])
    n_risk = sum(1 for d in data if d['players_win'] or d['cash_drain'])
    tot_aff = len(data)
    tot_players = sum(d['players'] for d in data); tot_ftd = sum(d['ftd'] for d in data)
    view = [d for d in data if d['players_win'] or d['cash_drain']] if risk_only else data
    cards = (scard('', '🤝', 'Аффилиатов', f(tot_aff), f'проблемных: {f(n_risk)}')
      + scard('cream', '👥', 'Игроков', f(tot_players), f'из них FTD (первый деп): {f(tot_ftd)}')
      + scard('alert', '🔴', 'Игроки бьют игры', f(n_pwin), 'GGR реал&lt;0 — обыграли игры (риск, если выведут)')
      + scard('orange', '💸', 'Касса в минусе', f(n_cash), 'реально вывели больше, чем внесли (Net Profit&lt;0)'))
    def sh(c, label, title):
        nd = 'asc' if (sort == c and not asc) else 'desc'
        arrow = ' ▾' if (sort == c and not asc) else (' ▴' if sort == c else '')
        return f'<th title="{title}"><a href="?sort={c}&dir={nd}">{label}{arrow}</a></th>'
    head = ('<th>Аффилиат</th>'
      + sh('players','Игроков','всего привязанных игроков')
      + sh('ftd','FTD','игроков, сделавших первый депозит')
      + sh('ftd_sum','FTD ₺','сумма ПЕРВЫХ депозитов — входит в «Деп ₺», не плюсуется')
      + sh('dep','Деп ₺','ВСЕ депозиты (deposit, completed, без manual)')
      + sh('wd','Выв ₺','ВСЕ выводы (withdrawal, completed, без manual)')
      + sh('net_profit','Net Profit','КАССА: Деп − Выв (как в партнёрке)')
      + sh('turn','Оборот','сумма всех ставок (вкл. фриспины)')
      + sh('ggr','GGR','игровая маржа: ставки − выплаты (вкл. фриспины)')
      + sh('ggr_real','GGR реал','то же, но только реальные ставки (без фриспинов)')
      + sh('ngr','NGR номин.','GGR − бонусы ПО НОМИНАЛУ. Пессимистично: бонусы — промо-кредит, не кэш, минус тут НЕ значит реальный убыток. Реальная прибыль — по Net Profit и GGR')
      + sh('hold','Hold%','GGR / оборот'))
    trs = ''
    for d in view:
        npc = 'neg' if d['net_profit'] < 0 else 'pos'; ngc = 'neg' if d['ngr'] < 0 else 'pos'
        pw, cd = d['players_win'], d['cash_drain']
        rcls = ' class=risk' if (pw and cd) else (' class=warn' if (pw or cd) else '')
        if pw and cd:
            badge = ' <span class=rmark title="УБЫТОЧНЫЙ: и игра в минусе (игроки обыграли), и касса в минусе (вывели больше)">🔴</span>'
        elif pw:
            badge = ' <span class=rmark title="РИСКОВЫЙ: игроки обыгрывают игры (GGR реал ниже 0), но кэш пока в плюсе — не вывели выигрыш">⚠️</span>'
        elif cd:
            badge = ' <span class=rmark title="КАССА В МИНУСЕ: вывели больше, чем внесли; по игре в плюсе (вероятно тайминг)">💸</span>'
        else:
            badge = ' <span class=rmark title="ПРИБЫЛЬНЫЙ: касса и игра в плюсе">✅</span>'
        trs += (f'<tr{rcls} onclick="location.href=\'/affiliate/{escape(str(d["code"]))}\'">'
          f'<td class=id>{escape(str(d["code"]))}{badge}</td>'
          f'<td class=num>{f(d["players"])}</td><td class=num>{f(d["ftd"])}</td><td class=num>{money2(d["ftd_sum"])}</td>'
          f'<td class=num>{money2(d["dep"])}</td><td class=num>{money2(d["wd"])}</td>'
          f'<td class="num {npc}">{money2(d["net_profit"])}</td>'
          f'<td class=num>{money2(d["turn"])}</td><td class=num>{money2(d["ggr"])}</td>'
          f'<td class=num>{money2(d["ggr_real"])}</td><td class="num {ngc}">{money2(d["ngr"])}</td>'
          f'<td class=num>{d["hold"]}%</td></tr>')
    he = ("<style>.affsearch{display:flex;gap:8px;align-items:center;margin:14px 0 4px}"
      ".affsearch input{width:220px}"
      ".aflegend{background:var(--cream);border:1px solid var(--beige);border-radius:10px;padding:11px 14px;margin:12px 0 2px;font-size:12.5px;line-height:1.7;color:var(--steel)}"
      ".aflegend b{color:var(--ink)}"
      "tr.risk{background:#fef2f2}tr.risk:hover{background:#fee2e2}"
      "tr.risk td:first-child{border-left:3px solid #dc2626}"
      "tr.warn{background:#fffbeb}tr.warn:hover{background:#fef3c7}"
      "tr.warn td:first-child{border-left:3px solid #d97706}"
      ".rmark{font-size:11px}</style>")
    legend = ('<div class=aflegend><b>Как читать:</b> '
      '<b>FTD ₺</b> — сумма первых депозитов, <u>входит</u> в «Деп ₺» (не плюсовать). · '
      '<b>Net Profit</b> = Деп − Выв — это <b>касса</b> (деньги вход − выход), может быть минусом. · '
      '<b>GGR</b> = ставки − выплаты — <b>игровая маржа</b> (вкл. фриспины), <b>GGR реал</b> — без фриспинов. · '
      '<b>NGR</b> = GGR − бонусы. · <b>Hold</b> = GGR / оборот. '
      'Деньги — auto-операции (deposit/withdrawal, completed), как в партнёрке. '
      '<b>«Выв ₺» = только реальные выплаты</b> (банк/havale); ручные бонус-списания (manual_withdrawal: просроченные FS, аннулир. отыгрыш) и отклонённые заявки <b>не считаются</b>.'
      '<br><b>Статус:</b> 🔴 <b>убыточный</b> — и игра, и касса в минусе · '
      '⚠️ <b>рисковый</b> — игроки обыгрывают игры (GGR реал&lt;0), но кэш пока в плюсе (выигрыш ещё не вывели) · '
      '💸 <b>касса в минусе</b> — вывели больше, чем внесли (по игре в плюсе, вероятно тайминг) · '
      '✅ <b>прибыльный</b>. '
      '<b>Бонусы — промо-кредит, не кэш</b>, поэтому «NGR номин.» — лишь пессимистичная оценка; реальный итог — по <b>кассе</b> и <b>GGR реал</b>.'
      f'<br>📅 <b>Данные по {dmy(data_asof())} включительно</b> (5 июня и позже в выгрузе нет). '
      f'При сверке с партнёркой ставь <b>End Date = {dmy(data_asof())}</b> — иначе разойдётся на «хвост» (~1 сутки).</div>')
    riskbar = (f'<div class=bar style="margin:8px 0 0">'
      f'<a class="chip {"on" if risk_only else ""}" href="{"?risk=1" if not risk_only else "?"}">⚠️ только проблемные ({f(n_risk)})</a>'
      f'<span class=muted>🔴 игроки выигрывают (GGR&lt;0) · 💸 касса в минусе (Net Profit&lt;0)</span></div>')
    top = ("<div class=topbar><div><div class=h1>Аффилиаты <em>· " + f(tot_aff) + "</em></div>"
      "<div class=lead>статистика по каждому источнику · деньги по определениям партнёрки (auto, completed) · клик по строке — полная карточка</div></div>"
      "<div class=pills>" + asof_pill() + "<span class='pill live'>live</span></div></div>")
    search = ("<form class=affsearch onsubmit=\"location.href='/affiliate/'+encodeURIComponent(document.getElementById('affq').value.trim());return false\">"
      "<input id=affq list=afflist placeholder='код аффилиата, напр. AF120'>"
      "<datalist id=afflist>" + ''.join(f'<option value="{escape(str(d["code"]))}">' for d in data) + "</datalist>"
      "<button class=btn type=submit>Открыть</button></form>")
    body = (f'<div class=cards style="margin-top:18px">{cards}</div>{legend}{search}{riskbar}'
      f'<div class=panel style="overflow-x:auto;margin-top:6px"><table><thead><tr>{head}</tr></thead><tbody>{trs}</tbody></table></div>')
    return layout('affiliates', top + body, head_extra=he)

AFF_JS = """
const A=window.AFFD;
const HA='#e5e7eb',ST='#64748b',INK='#1e293b',OR='#2563eb',GR='#16a34a',RD='#dc2626';
const tip={backgroundColor:'#fff',borderColor:HA,textStyle:{color:INK},confine:true};
const ax=e=>Object.assign({axisLine:{lineStyle:{color:HA}},axisTick:{show:false},splitLine:{lineStyle:{color:HA}},axisLabel:{color:ST}},e||{});
function affbar(id,data,color){var el=document.getElementById(id);if(!el||!data.length)return;echarts.init(el).setOption({grid:{left:6,right:12,top:14,bottom:6,containLabel:true},tooltip:Object.assign({trigger:'axis'},tip),xAxis:ax({type:'category',data:data.map(d=>d[0])}),yAxis:ax({type:'value'}),series:[{type:'bar',data:data.map(d=>d[1]),barWidth:'55%',itemStyle:{color:color,borderRadius:[4,4,0,0]}}]});}
affbar('aff_regs',A.regs,OR);
affbar('aff_prov',A.prov,'#60a5fa');
(function(){var el=document.getElementById('aff_money');if(el&&A.money.length)echarts.init(el).setOption({grid:{left:6,right:12,top:28,bottom:6,containLabel:true},tooltip:Object.assign({trigger:'axis'},tip),legend:{data:['Депозиты','Выводы'],textStyle:{color:ST},top:0},xAxis:ax({type:'category',data:A.money.map(d=>d[0])}),yAxis:ax({type:'value'}),series:[{name:'Депозиты',type:'bar',data:A.money.map(d=>d[1]),itemStyle:{color:GR,borderRadius:[3,3,0,0]}},{name:'Выводы',type:'bar',data:A.money.map(d=>d[2]),itemStyle:{color:RD,borderRadius:[3,3,0,0]}}]});})();
(function(){var el=document.getElementById('aff_life');if(el&&A.life.length)echarts.init(el).setOption({tooltip:Object.assign({trigger:'item'},tip),series:[{type:'pie',radius:['45%','72%'],data:A.life.map(d=>({name:d[0],value:d[1]})),label:{color:ST,fontSize:11},itemStyle:{borderColor:'#fff',borderWidth:2}}]});})();
"""

@app.route('/affiliate/<code>')
def affiliate(code):
    code = _aff_clean(code)
    P = {'code': code}
    st = request.args.get('st', 'normal'); st = st if st in ('normal', 'all') else 'normal'
    AW = "affiliate_code={code:String}" + ('' if st == 'all' else " AND account_type='normal'")
    _bk = q("SELECT countIf(account_type='normal'), countIf(account_type='blocked'), count() FROM users WHERE affiliate_code={code:String}", P)[1][0]
    bk_norm, bk_block, bk_all = int(_bk[0]), int(_bk[1]), int(_bk[2])
    bk_test = bk_all - bk_norm - bk_block
    # ── фильтр по датам (как в панели: каждая метрика по своей дате события) ──
    _aof = data_asof()
    DMIN, DMAX = '2025-12-01', (_aof.strftime('%Y-%m-%d') if _aof else '2026-06-04')
    def _vd(s, d):
        s = (s or '').strip()
        ok = (len(s) == 10 and s[4] == '-' and s[7] == '-'
              and s[:4].isdigit() and s[5:7].isdigit() and s[8:10].isdigit())
        return s if ok else d
    frm = _vd(request.args.get('from'), DMIN)
    to = _vd(request.args.get('to'), DMAX)
    if frm > to: frm, to = DMIN, DMAX
    filtered = (frm != DMIN) or (to != DMAX)
    TZ = "'Europe/Istanbul'"
    DREG = f"toDate(toTimeZone(reg_date,{TZ})) BETWEEN '{frm}' AND '{to}'"
    DFTD = f"toDate(toTimeZone(ftd_date,{TZ})) BETWEEN '{frm}' AND '{to}'"
    DMT = f"toDate(toTimeZone(created_at,{TZ})) BETWEEN '{frm}' AND '{to}'"
    PSET = f"casino_player_id IN (SELECT casino_player_id FROM player_features WHERE {AW})"
    tot_all = q(f"SELECT count() FROM users WHERE {AW}", P)[1][0][0]
    if not tot_all:
        top = (f"<div class=topbar><div><div class=h1>Аффилиат <em>· {escape(code)}</em></div>"
          "<div class=lead>нет игроков с таким кодом аффилиата</div></div></div>"
          "<a class=back href='/affiliates'>← ко всем аффилиатам</a>")
        return layout('affiliates', top)
    atype = q(f"SELECT any(affiliate_type) FROM player_features WHERE {AW}", P)[1][0][0]
    # регистрации и FTD В ОКНЕ (по своей дате события)
    players = q(f"SELECT count() FROM users WHERE {AW} AND {DREG}", P)[1][0][0]
    fr = q(f"""SELECT countIf(ftd_amount>0), round(sumIf(ftd_amount,ftd_amount>0)),
        max(ftd_date), round(avgIf(ftd_amount,ftd_amount>0))
      FROM users WHERE {AW} AND {DFTD}""", P)[1][0]
    ftd = fr[0]; ftd_sum = float(fr[1] or 0); last_ftd = fr[2]; avg_ftd = float(fr[3] or 0)
    # деньги В ОКНЕ — определения партнёрки (auto, completed)
    m = q(f"""SELECT
        round(sumIf(amount, {DEP_OK}),2),
        countIf({DEP_OK}),
        round(sumIf(amount, type='manual_deposit' AND {SUCCESS}),2),
        round(sumIf(abs(amount), {WD_OK}),2),
        countIf({WD_OK}),
        round(sumIf(amount, type='manual_withdrawal' AND {SUCCESS}),2),
        countIf(type='withdrawal' AND status IN ('rejected','failed')),
        round(sumIf(abs(amount), {BONUS_OK}),2)
      FROM money_transactions WHERE {PSET} AND {DMT}""", P)[1][0]
    (dep_appr, dep_cnt, dep_man, wd_appr, wd_cnt, wd_man, wd_rej, bonus_cost) = [float(x or 0) for x in m]
    dep_cnt, wd_cnt, wd_rej = int(dep_cnt), int(wd_cnt), int(wd_rej)
    # игра В ОКНЕ (только completed — pending/rejected не в итоги)
    gg = q(f"""SELECT round(sumIf(bet_amount, transaction_type='bet' AND {GSUCCESS}),2),
        round(sumIf(win_amount, transaction_type='win' AND {GSUCCESS}),2),
        round(sumIf(bet_amount, transaction_type='freespins_bet' AND {GSUCCESS}),2),
        round(sumIf(win_amount, transaction_type='freespins_win' AND {GSUCCESS}),2)
      FROM game_transactions WHERE {PSET} AND {DMT}""", P)[1][0]
    (real_bets, real_wins, fs_bets, fs_wins) = [float(x or 0) for x in gg]
    ggr_real = real_bets - real_wins; ggr_fs = fs_bets - fs_wins; ggr_game = ggr_real + ggr_fs
    turn = real_bets + fs_bets
    active = q(f"SELECT uniqExact(casino_player_id) FROM game_transactions WHERE {PSET} AND {DMT} AND {BET_T} AND {GSUCCESS}", P)[1][0][0]
    # производные (спека казино)
    conv = round(100 * ftd / players, 1) if players else 0
    dep_ratio = round(100 * bonus_cost / dep_appr, 1) if dep_appr else 0
    net_profit = dep_appr - wd_appr                          # Affiliate net = Deposits − Withdrawals
    commission = round(aff_commission_row(net_profit, code), 2)  # ЭТОТ аффилиат: max(net,0)×его ставку (не глобально!)
    hold = round(100 * ggr_game / turn, 1) if turn else 0
    hold_real = round(100 * ggr_real / real_bets, 1) if real_bets else 0
    ngr = calc_ngr(ggr_game, bonus_cost, provider_cost_total(PSET), commission)  # GGR − Bonus − Provider − Commission
    # ── блок 1: сверка с партнёркой (те же пункты, тот же порядок, те же определения) ──
    cards = (scard('cream', '🧾', 'Total Registrations', f(players), f'Conversion {conv}%')
      + scard('cream', '🥇', 'Total FTD', f(ftd), f'FTD Rate {conv}% · ср. {f(avg_ftd)} ₺ · посл. {dmy(last_ftd)}')
      + scard('', '💰', 'Approved Deposits', money2(dep_appr), f'{f(dep_cnt)} транзакций')
      + scard('', '🏧', 'Approved Withdrawals', money2(wd_appr), f'{f(wd_cnt)} раз · {f(wd_rej)} отклонено')
      + scard('', '🎁', 'Bonus Cost', money2(bonus_cost), f'bonus/manual_bonus/freespin · Ratio {dep_ratio}%')
      + scard(('pos' if net_profit >= 0 else 'alert'), '📈', 'Net Profit', money2(net_profit), 'Affiliate net · Deposits − Withdrawals')
      + scard('orange', '🪙', 'Commission', money2(commission), f'max(net,0) × {aff_rate(code):g}% (ставка аффилиата)')
      + scard('', '🟢', 'Active Players', f(active), 'играли ≥1 ставки в окне'))
    # ── блок 2: наша игровая аналитика (сверх партнёрки) ──
    cards_extra = (scard('', '🎰', 'Оборот · всего', money2(turn), f'ставки: реальные {money2(real_bets)} · фриспины {money2(fs_bets)}')
      + scard('', '🏦', 'GGR · всего', money2(ggr_game), f'ставки − выплаты · Hold {hold}%')
      + scard('orange', '🎯', 'GGR · реальные', money2(ggr_real), f'без фриспинов · Hold {hold_real}%')
      + scard('', '🎁', 'GGR · фриспины', money2(ggr_fs), 'фриспины: ставки − выплаты')
      + scard('', '💸', 'Бонусы выдано', money2(bonus_cost), 'manual-бонусы (Bonus Cost)')
      + scard('', '💠', 'NGR', money2(ngr), f'GGR − Bonus({money2(bonus_cost)}) − Provider − Commission')
      + scard('', '🧮', 'Бонус-списания (ручн.)', money2(wd_man), f'НЕ кэш · просрочка FS / аннулир. отыгрыш · ручные начисления +{money2(dep_man)}')
      + scard('', '💎', 'FTD-сумма', money2(ftd_sum), f'первые депозиты {f(ftd)} игроков (⊆ депозиты)'))
    recon = ('<div class=banner style="margin-top:16px">'
      '🔎 <b>Сверка с партнёркой.</b> Блок выше посчитан по её определениям: '
      '<b>Approved Deposits/Withdrawals</b> = операции типа deposit/withdrawal со статусом completed (без manual); '
      '<b>Bonus Cost</b> = manual-бонусы; <b>Net Profit</b> = deposits − withdrawals; <b>Commission</b> = Net Profit × 1%. '
      f'Выводы сходятся до копейки. Разница в Registrations/FTD/Deposits — игроки, появившиеся <b>после нашего экспорта</b> '
      f'(данные на {dmy(data_asof())}); для совпадения 1-в-1 нужен свежий выгруз. '
      f'«Active Players» в панели (152) к этому аффилиату не относится — у него физически {f(players)} игроков.</div>')
    glegend = ('<div class=banner style="margin-top:12px">'
      '📊 <b>Три разных «дохода» — не путать:</b> '
      '<b>Net Profit</b> (касса) = депозиты − выводы · '
      '<b>GGR</b> (игровая маржа) = ставки − выплаты · '
      '<b>NGR</b> = GGR − выданные бонусы. '
      'GGR показан раздельно: всего / только реальные ставки / фриспины. '
      '<b>FTD-сумма</b> входит в депозиты (не плюсуется).'
      '<br>🎁 <b>Бонусы — промо-кредит, не кэш:</b> фриспины уже учтены в GGR (как ставки/выплаты), manual-бонусы — отдельно. '
      '<b>«Выводы» = только реальные выплаты</b> (banka/havale, type=withdrawal·completed). '
      'Ручные бонус-списания (manual_withdrawal: просроченные FS, аннулир. отыгрыш) — это НЕ выплаты, в выводах не считаются.</div>')
    # вердикт: прибыльный / убыточный (по реальной кассе и игровой марже)
    pw_d = ggr_real < 0       # игроки обыгрывают РЕАЛЬНЫЕ игры (без фриспинов)
    cd_d = net_profit < 0     # касса в минусе (вывели больше, чем внесли)
    if pw_d and cd_d:
        v_head = '🔴 <b>УБЫТОЧНЫЙ.</b>'
        v_why = (f'И игра, и касса в минусе: игроки обыграли игры (GGR реал <b>{money2(ggr_real)}</b>) '
                 f'И вывели больше, чем внесли (касса <b>{money2(net_profit)}</b>).')
        col, bg, bd = '#dc2626', '#fef2f2', '#fecaca'
    elif pw_d:
        v_head = '⚠️ <b>РИСКОВЫЙ — игроки обыгрывают игры.</b>'
        v_why = (f'GGR реал = <b>{money2(ggr_real)}</b> (минус) — игроки выиграли у игр. '
                 f'Но касса пока в плюсе (<b>{money2(net_profit)}</b>) — выигрыш ещё не вывели. '
                 f'Риск: выведут — уйдём в минус.')
        col, bg, bd = '#d97706', '#fffbeb', '#fde68a'
    elif cd_d:
        v_head = '💸 <b>КАССА В МИНУСЕ.</b>'
        v_why = (f'Net Profit = <b>{money2(net_profit)}</b> — вывели больше, чем внесли. '
                 f'По игре в плюсе (GGR реал {money2(ggr_real)}) — вероятно тайминг выводов.')
        col, bg, bd = '#d97706', '#fffbeb', '#fde68a'
    else:
        v_head = '✅ <b>ПРИБЫЛЬНЫЙ.</b>'
        v_why = f'Касса (Net Profit) = <b>{money2(net_profit)}</b>, игровая маржа GGR реал = <b>{money2(ggr_real)}</b> — оба в плюсе.'
        col, bg, bd = '#16a34a', '#f0fdf4', '#bbf7d0'
    risk_banner = (f'<div class=banner style="margin-top:14px;border-left-color:{col};background:{bg};border-color:{bd}">'
      f'{v_head} {v_why} <span class=muted>Выводы — только реальные выплаты (банк), без бонус-списаний; бонусы — промо-кредит, не кэш.</span></div>')
    manual_note = ''
    if wd_man > 0 or dep_man > 0:
        manual_note = ('<div class=banner style="margin-top:12px;border-left-color:#7c3aed">'
          'ℹ️ <b>Важно про «выводы».</b> Считаем <b>только реальные выплаты</b> (банк/havale, <code>type=withdrawal · completed</code>). '
          f'Ручные операции <b>manual_withdrawal {money2(wd_man)}</b> — это <b>списания бонусов</b> '
          '(просроченные фриспины, аннулированный отыгрыш, «лишний выигрыш» — <i>fazla kazanç / süresi geçmiş fs / çevrim geçersiz</i>), '
          'а НЕ деньги игроку. В выводы и Net Profit они <b>не входят</b> — так же, как в партнёрке. '
          'Отклонённые/failed-заявки тоже не считаются.</div>')
    # charts data
    regs = [[str(r[0])[:7], r[1]] for r in q(f"SELECT toStartOfMonth(toTimeZone(reg_date,'Europe/Istanbul')) m, count() FROM player_features WHERE {AW} AND reg_date IS NOT NULL AND {DREG} GROUP BY m ORDER BY m", P)[1]]
    money = [[str(r[0])[:7], float(r[1] or 0), float(r[2] or 0)] for r in q(
        f"""SELECT toStartOfMonth(toTimeZone(created_at,'Europe/Istanbul')) m,
            sumIf(amount, type='deposit' AND status='completed') dep,
            sumIf(amount, type='withdrawal' AND status='completed') wd
          FROM money_transactions WHERE {PSET} AND {DMT}
          GROUP BY m ORDER BY m""", P)[1]]
    life = [[str(r[0]), r[1]] for r in q(f"SELECT lifecycle, count() FROM player_features WHERE {AW} GROUP BY lifecycle ORDER BY 2 DESC", P)[1]]
    prov = [[str(r[0]), r[1]] for r in q(f"SELECT primary_provider, count() FROM player_features WHERE {AW} AND primary_provider!='' GROUP BY 1 ORDER BY 2 DESC LIMIT 8", P)[1]]
    # top games В ОКНЕ (из сырых транзакций по дате)
    tg = q(f"""SELECT any(aggregator) prov, {GN()} g, uniqExact(casino_player_id) ppl,
        countIf(transaction_type IN ('bet','freespins_bet')) bets,
        round(sumIf(bet_amount, transaction_type IN ('bet','freespins_bet'))) turn,
        round(sumIf(win_amount, transaction_type IN ('win','freespins_win')) - sumIf(bet_amount, transaction_type IN ('bet','freespins_bet'))) net
      FROM game_transactions WHERE {PSET} AND {DMT} AND game_uuid!='' GROUP BY game_uuid ORDER BY turn DESC LIMIT 15""", P)[1]
    games_rows = ''.join(
        f'<tr><td>{escape(str(g))}</td><td>{escape(str(pv or "—"))}</td><td class=num>{f(ppl)}</td>'
        f'<td class=num>{f(bets)}</td><td class=num>{f(tn)}</td><td class="num {"neg" if (nt or 0)<0 else "pos"}">{f(nt)}</td></tr>'
        for (pv, g, ppl, bets, tn, nt) in tg) or '<tr><td colspan=6 style="text-align:center;color:var(--steel)">нет игровых данных</td></tr>'
    # payment methods
    pays = q(f"SELECT primary_payment_method, count() FROM player_features WHERE {AW} AND primary_payment_method!='' GROUP BY 1 ORDER BY 2 DESC LIMIT 8", P)[1]
    pmx = max(([r[1] for r in pays] or [1])) or 1
    pays_html = ''.join(f'<div class=trow><i style="width:{round(r[1]/pmx*100)}%"></i><span class=tl>{escape(str(r[0]))}</span><span class=tv>{f(r[1])}</span></div>' for r in pays) or '<div class=muted>—</div>'
    # players table — РЕАЛЬНАЯ КАССА (auto deposit/withdrawal, completed); витрину не берём (в ней manual бонус-корректировки)
    P_SORTS = {'casino_player_id','reg_date','ftd_amount','dep_cnt','dep','wd_cnt','wd','net_cash','turnover','net','recency_days'}
    sort = request.args.get('sort','dep'); sort = sort if sort in P_SORTS else 'dep'
    asc_p = request.args.get('dir') == 'asc'
    page = max(0, int(request.args.get('p','0') or 0))
    _, prows0 = q(f"""SELECT casino_player_id, lifecycle, country, toDate(reg_date) reg_date, ftd_amount,
        primary_provider, recency_days FROM player_features WHERE {AW}""", P)
    pmoney = {r[0]: r for r in q(f"""SELECT casino_player_id,
        round(sumIf(amount, {DEP_OK}),2),
        countIf({DEP_OK}),
        round(sumIf(abs(amount), {WD_OK}),2),
        countIf({WD_OK})
      FROM money_transactions WHERE {PSET} AND {DMT}
      GROUP BY casino_player_id""", P)[1]}
    pgame = {r[0]: (float(r[1] or 0), float(r[2] or 0)) for r in q(f"""SELECT casino_player_id,
        round(sumIf(bet_amount, {BET_T} AND {GSUCCESS}),2),
        round(sumIf(win_amount, {WIN_T} AND {GSUCCESS}) - sumIf(bet_amount, {BET_T} AND {GSUCCESS}),2)
      FROM game_transactions WHERE {PSET} AND {DMT} GROUP BY casino_player_id""", P)[1]}
    plist = []
    for (pid, lf, ctry, reg, ftd, prov_p, rec) in prows0:
        mr = pmoney.get(pid); gr = pgame.get(pid)
        dep = float(mr[1] or 0) if mr else 0.0; dep_cnt = int(mr[2]) if mr else 0
        wd = float(mr[3] or 0) if mr else 0.0; wd_cnt = int(mr[4]) if mr else 0
        turn_p = gr[0] if gr else 0.0; net_p = gr[1] if gr else 0.0
        plist.append({'casino_player_id': pid, 'lf': lf, 'ctry': ctry, 'reg_date': reg, 'ftd_amount': float(ftd or 0),
                      'dep': dep, 'dep_cnt': dep_cnt, 'wd': wd, 'wd_cnt': wd_cnt, 'net_cash': dep - wd,
                      'turnover': turn_p, 'net': net_p, 'prov': prov_p,
                      'recency_days': rec if rec is not None else 10**9})
    plist.sort(key=lambda d: (d[sort] is None, d[sort]), reverse=not asc_p)  # None-safe (reg_date=NULL → 500)
    total_p = len(plist); pview = plist[page*100:(page+1)*100]
    dq_date = f'&from={frm}&to={to}'
    dq = f'{dq_date}&st={st}'
    base = f'&sort={sort}&dir={"asc" if asc_p else "desc"}{dq}'
    def psh(c, label, title=''):
        nd = 'asc' if (sort == c and not asc_p) else 'desc'
        arrow = ' ▾' if (sort == c and not asc_p) else (' ▴' if sort == c else '')
        tt = f' title="{title}"' if title else ''
        return f'<th{tt}><a href="?sort={c}&dir={nd}&p=0{dq}">{label}{arrow}</a></th>'
    phead = ('<th>ID</th><th>Стадия</th><th>Страна</th>' + psh('reg_date','Рег') + psh('ftd_amount','FTD ₺')
      + psh('dep_cnt','#Деп') + psh('dep','Деп ₺') + psh('wd_cnt','#Выв')
      + psh('wd','Выв ₺','реальные выплаты (банк), без бонус-списаний')
      + psh('net_cash','Касса','Деп − Выв (реальные деньги)')
      + psh('turnover','Оборот') + psh('net','Net игрока') + '<th>Провайдер</th>' + psh('recency_days','Recency'))
    ptrs = ''
    for d in pview:
        ndc = 'neg' if d['net_cash'] < 0 else 'pos'; netc = 'neg' if d['net'] < 0 else 'pos'
        rec = d['recency_days']; rec_txt = '—' if rec >= 10**9 else f(rec) + 'д'
        ptrs += (f'<tr onclick="location.href=\'/player/{d["casino_player_id"]}\'"><td class=id>{d["casino_player_id"]}</td>'
          f'<td>{life_badge(d["lf"])}</td><td>{escape(str(d["ctry"] or "—"))}</td>'
          f'<td class=num>{str(d["reg_date"])[:10] if d["reg_date"] else "—"}</td>'
          f'<td class=num>{f(d["ftd_amount"])}</td><td class=num>{f(d["dep_cnt"])}</td><td class=num>{money2(d["dep"])}</td>'
          f'<td class=num>{f(d["wd_cnt"])}</td><td class=num>{money2(d["wd"])}</td><td class="num {ndc}">{money2(d["net_cash"])}</td>'
          f'<td class=num>{f(d["turnover"])}</td><td class="num {netc}">{f(d["net"])}</td>'
          f'<td>{escape(str(d["prov"] or "—"))}</td><td class=num>{rec_txt}</td></tr>')
    pg = ''
    if page > 0: pg += f'<a href="?p={page-1}{base}">← назад</a>'
    pg += f'<span class=bd>{page*100+1}–{min((page+1)*100, total_p)} из {f(total_p)}</span>'
    if (page+1)*100 < total_p: pg += f'<a href="?p={page+1}{base}">вперёд →</a>'
    he = ("<script src='https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js'></script>"
      "<style>.cohchart{width:100%;height:230px}"
      ".tbl{display:flex;flex-direction:column;gap:3px}"
      ".trow{position:relative;display:flex;justify-content:space-between;padding:6px 10px;font-size:12.5px;border-radius:6px;overflow:hidden}"
      ".trow i{position:absolute;left:0;top:0;bottom:0;background:rgba(37,99,235,.10)}"
      ".trow .tl{position:relative;z-index:1;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:70%}"
      ".trow .tv{position:relative;z-index:1;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;color:var(--primary)}"
      ".chbox{background:var(--canvas);border:1px solid var(--hair);border-radius:12px;padding:14px 16px}"
      ".chbox h4{font-size:14px;font-weight:600;margin:0 0 8px}"
      ".afffilter{display:flex;align-items:center;gap:8px;flex-wrap:wrap;background:var(--cream);border:1px solid var(--beige);border-radius:10px;padding:10px 14px;margin-top:8px}"
      ".afffilter .fl{font-size:13px;color:var(--steel);font-weight:600}"
      ".afffilter input[type=date]{height:38px}"
      ".afffilter .fwin{font-size:12.5px;color:var(--primary);font-weight:600;margin-left:6px}</style>")
    dsel = f'asc' if asc_p else 'desc'
    filterbar = (f'<form class=afffilter method=get>'
      f'<span class=fl>📅 Период (по дате события):</span>'
      f'<input type=date name=from value="{frm}" min="{DMIN}" max="{DMAX}">'
      f'<span class=fl>→</span>'
      f'<input type=date name=to value="{to}" min="{DMIN}" max="{DMAX}">'
      f'<input type=hidden name=sort value="{sort}"><input type=hidden name=dir value="{dsel}">'
      f'<input type=hidden name=st value="{st}">'
      f'<button class=btn type=submit>Применить</button>'
      f'<a class=chip href="?">Сброс</a>'
      + (f'<span class=fwin>окно: {frm} → {to}</span>' if filtered
         else f'<span class=muted>все данные ({DMIN} → {DMAX})</span>') + '</form>')
    statusbar = (f'<div class=afffilter style="margin-top:6px">'
      f'<span class=fl>👤 Статус игроков (как «Player Status» в панели):</span>'
      f'<a class="chip {"on" if st=="normal" else ""}" href="?st=normal{dq_date}">Только реальные</a>'
      f'<a class="chip {"on" if st=="all" else ""}" href="?st=all{dq_date}">Все игроки</a>'
      f'<span class=muted>разбивка AF: ✅ реальные <b>{f(bk_norm)}</b> · 🧪 тест/служебные <b>{f(bk_test)}</b> · ⛔ blocked <b>{f(bk_block)}</b> · всего <b>{f(bk_all)}</b></span>'
      + (f'<span class=fwin>сейчас: {"ВСЕ типы" if st=="all" else "только реальные"}</span>') + '</div>')
    top = (f"<div class=topbar><div><a class=back href='/affiliates'>← ко всем аффилиатам</a>"
      f"<div class=h1 style='margin-top:6px'>Аффилиат <em>· {escape(code)}</em></div>"
      f"<div class=lead>полная статистика источника {escape(code)} · всего {f(total_p)} игроков · во что играли, сколько вносили и выводили</div></div>"
      "<div class=pills>" + asof_pill() + (f"<span class=pill style='background:var(--primary);color:#fff'>окно {frm}→{to}</span>" if filtered else "") + "<span class='pill live'>live</span></div></div>")
    _ec = f"aff={escape(code)}&at=normal"
    exportbar = (f'<div class=bar style="margin:8px 0 0;align-items:center">'
      f'<span class=muted>выгрузить игроков аффилиата:</span>'
      f'<a class=chip href="/players.csv?{_ec}">⬇ все · CSV</a>'
      f'<a class=chip href="/players.xlsx?{_ec}">⬇ все · Excel</a>'
      f'<a class=chip href="/players.csv?{_ec}&life=churning" title="под риском + спящие + отток — для возврата">⬇ уходящие · CSV</a>'
      f'<a class=chip href="/players.xlsx?{_ec}&life=churning" title="под риском + спящие + отток — для возврата">⬇ уходящие · Excel</a></div>')
    body = (f'{filterbar}{statusbar}{risk_banner}{exportbar}'
      f'<div class=eyebrow style="margin-top:8px">Сверка с партнёркой · те же метрики, что в панели</div>'
      f'<div class=cards>{cards}</div>'
      f'{recon}'
      f'<div class=eyebrow>Игровая аналитика · сверх партнёрки</div>'
      f'<div class=cards>{cards_extra}</div>'
      f'{glegend}'
      f'{manual_note}'
      '<div class=eyebrow>Деньги и регистрации по месяцам</div>'
      '<div class=chgrid>'
      '<div class=chbox><h4>Регистрации по месяцам</h4><div class=cohchart id=aff_regs></div></div>'
      '<div class=chbox><h4>Депозиты vs выводы (₺/мес)</h4><div class=cohchart id=aff_money></div></div></div>'
      '<div class=eyebrow>Во что играли</div>'
      '<div class=chgrid>'
      '<div class=chbox><h4>Топ провайдеров (по игрокам)</h4><div class=cohchart id=aff_prov></div></div>'
      f'<div class=chbox><h4>Топ игр</h4><div style="overflow-x:auto"><table><thead><tr><th>Игра</th><th>Провайдер</th><th>Игроков</th><th>Ставок</th><th>Оборот ₺</th><th>Net игроков</th></tr></thead><tbody>{games_rows}</tbody></table></div></div></div>'
      '<div class=eyebrow>Стадии жизни и способы оплаты</div>'
      '<div class=chgrid>'
      '<div class=chbox><h4>Стадии жизненного цикла</h4><div class=cohchart id=aff_life></div></div>'
      f'<div class=chbox><h4>Способы оплаты (по игрокам)</h4><div class=tbl style="margin-top:4px">{pays_html}</div></div></div>'
      f'<div class=eyebrow>Игроки · {f(total_p)} <span style="color:var(--steel);font-weight:400;text-transform:none;letter-spacing:0">(деньги/оборот — за выбранное окно)</span></div>'
      f'<div class=panel style="overflow-x:auto"><table><thead><tr>{phead}</tr></thead><tbody>{ptrs}</tbody></table></div>'
      f'<div class=pager>{pg}</div>')
    DATA = jsdump({'regs': regs, 'money': money, 'life': life, 'prov': prov})
    js = "<script>window.AFFD=" + DATA + ";" + AFF_JS + "</script>"
    return layout('affiliates', top + body, head_extra=he).replace('</body>', js + '</body>')

@app.route('/schema')
def schema():
    tabs = [('users','справочник игроков · 1 строка = игрок'),
            ('money_transactions','депозиты, выводы, бонусы'),
            ('game_sessions','игровые сессии'),
            ('game_transactions','каждая ставка и выигрыш')]
    pk = {('users','casino_player_id'),('game_sessions','session_id')}
    fk = {('game_sessions','casino_player_id'),('money_transactions','casino_player_id'),
          ('game_transactions','casino_player_id'),('game_transactions','session_id')}
    cards = ''
    for t, role in tabs:
        rows = q(f"SELECT sum(rows) FROM system.parts WHERE database='retention' AND table='{t}' AND active")[1][0][0] or 0
        cols = [r[0] for r in q(f"SELECT name FROM system.columns WHERE database='retention' AND table='{t}' ORDER BY position")[1]]
        ch = ''
        for c in cols:
            cls = 'col pk' if (t,c) in pk else ('col fk' if (t,c) in fk else 'col')
            ch += f'<span class="{cls}">{escape(c)}</span>'
        cards += (f'<div class=schcard><div class=schh><b>{t}</b><span class=cnt>{f(rows)} строк</span></div>'
          f'<div class=role>{role} · {len(cols)} колонок</div><div class=cols>{ch}</div></div>')
    rels = ("<div class=banner>Все таблицы связаны через <code>casino_player_id</code> "
      "(<code>users</code> → события, связь 1:N · синим PK, индиго FK). "
      "Дополнительно <code>session_id</code> сшивает <code>game_transactions</code> с <code>game_sessions</code>.</div>")
    he = ("<style>.schgrid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:18px}"
      ".schcard{background:var(--canvas);border:1px solid var(--hair);border-radius:12px;padding:16px 18px}"
      ".schh{display:flex;justify-content:space-between;align-items:baseline;font-weight:700;font-size:18px}"
      ".schh .cnt{font-family:Inter;font-size:12px;color:var(--steel);font-weight:500}"
      ".role{color:var(--steel);font-size:12px;margin:4px 0 12px}"
      ".cols{display:flex;flex-wrap:wrap;gap:5px}"
      ".col{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:11px;background:var(--surface);border:1px solid var(--hair);border-radius:5px;padding:3px 7px;color:var(--slate)}"
      ".col.pk{background:#dbeafe;border-color:#bfdbfe;color:#1e40af;font-weight:600}"
      ".col.fk{background:#e0e7ff;border-color:#c7d2fe;color:#4338ca;font-weight:600}"
      "code{background:var(--cream-d);border-radius:4px;padding:1px 5px;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:12px;color:var(--primary)}</style>")
    top = ("<div class=topbar><div><div class=h1>Схема данных <em>· 4 таблицы</em></div>"
      "<div class=lead>структура и связи · всё live из ClickHouse</div></div></div>")
    return layout('schema', top + rels + '<div class=schgrid>' + cards + '</div>', head_extra=he)

CAT = ("multiIf("
 "positionCaseInsensitive(notes,'test')>0,'🧪 тест-операции',"
 "positionCaseInsensitive(notes,'fazla kazanç')>0 OR positionCaseInsensitive(notes,'üzeri kazan')>0,'лишний выигрыш (сверх лимита)',"
 "positionCaseInsensitive(notes,'süresi')>0 OR positionCaseInsensitive(notes,'dolmuş')>0 OR positionCaseInsensitive(notes,'geçmiş')>0 OR positionCaseInsensitive(notes,'dolan')>0,'истёкший бонус',"
 "positionCaseInsensitive(notes,'haksız')>0,'нечестный выигрыш',"
 "positionCaseInsensitive(notes,'ihlal')>0 OR positionCaseInsensitive(notes,'promok')>0 OR positionCaseInsensitive(notes,'promos')>0 OR positionCaseInsensitive(notes,'kural')>0 OR positionCaseInsensitive(notes,'birden fazla')>0,'нарушение правил/промо',"
 "positionCaseInsensitive(notes,'deneme')>0,'бонус без депозита',"
 "notes='','(без пометки)','прочее')")

AUDIT_JS = """
const OR='#2563eb',ST='#64748b',HA='#e5e7eb',INK='#1e293b';
const _t={trigger:'axis',backgroundColor:'#fff',borderColor:HA,textStyle:{color:INK}};
const _E=id=>document.getElementById(id);
if(_E('c_mon'))echarts.init(_E('c_mon')).setOption({grid:{left:6,right:14,top:16,bottom:6,containLabel:true},tooltip:_t,
 xAxis:{type:'category',data:AU.mon.map(x=>x[0]),axisLine:{lineStyle:{color:HA}},axisTick:{show:false},axisLabel:{color:ST}},
 yAxis:{type:'value',axisLine:{show:false},axisTick:{show:false},splitLine:{lineStyle:{color:HA}},axisLabel:{color:ST,formatter:v=>(v/1e6)+'M'}},
 series:[{type:'bar',data:AU.mon.map(x=>x[1]),barWidth:'56%',itemStyle:{color:OR,borderRadius:[4,4,0,0]}}]});
if(_E('c_cat')&&AU.cat)echarts.init(_E('c_cat')).setOption({grid:{left:6,right:66,top:4,bottom:4,containLabel:true},
 tooltip:{trigger:'item',backgroundColor:'#fff',borderColor:HA,textStyle:{color:INK},formatter:p=>p.name+': '+(p.value/1e6).toFixed(2)+'M ₺'},
 xAxis:{type:'value',axisLabel:{show:false},axisLine:{show:false},axisTick:{show:false},splitLine:{show:false}},
 yAxis:{type:'category',data:AU.cat.map(x=>x[0]).reverse(),axisLine:{show:false},axisTick:{show:false},axisLabel:{color:ST,fontSize:12}},
 series:[{type:'bar',data:AU.cat.map(x=>x[1]).reverse(),barWidth:'64%',itemStyle:{color:OR,borderRadius:[0,5,5,0]},label:{show:true,position:'right',color:ST,formatter:p=>(p.value/1e6).toFixed(1)+'M'}}]});
"""

def rev_link(rb, stop=False):
    if not rb: return '—'
    sp = ' onclick="event.stopPropagation()"' if stop else ''
    return f'<a href="/audit/reviewer/{escape(rb)}"{sp} style="color:var(--primary);font-weight:500">{escape(rb)}</a>'

@app.route('/audit')
def audit():
    admins = {r[0] for r in q("SELECT toString(casino_player_id) FROM users WHERE role IN ('admin','support') OR account_type='service'")[1]}
    tot, cnt, napp, biggest = q("SELECT round(sum(amount)), count(), uniqExact(reviewed_by), round(max(amount)) FROM money_transactions WHERE type='manual_withdrawal' AND status='completed'")[1][0]
    apprs = q(f"SELECT reviewed_by, count(), round(sum(amount)), round(100*sumIf(amount, {CAT} IN ('🧪 тест-операции','прочее','(без пометки)'))/sum(amount)) FROM money_transactions WHERE type='manual_withdrawal' AND status='completed' GROUP BY reviewed_by ORDER BY 3 DESC LIMIT 15")[1]
    cats = q(f"SELECT {CAT} cat, round(sum(amount)) FROM money_transactions WHERE type='manual_withdrawal' AND status='completed' GROUP BY cat ORDER BY 2 DESC")[1]
    tops = q("""WITH dep AS (SELECT casino_player_id, sumIf(amount,type IN ('deposit','manual_deposit') AND status='completed') d FROM money_transactions GROUP BY casino_player_id)
      SELECT m.casino_player_id, u.account_type, round(m.amount), toDate(toTimezone(m.created_at,'Europe/Istanbul')), m.reviewed_by, round(dep.d)
      FROM money_transactions m LEFT JOIN users u USING(casino_player_id) LEFT JOIN dep ON dep.casino_player_id=m.casino_player_id
      WHERE m.type='manual_withdrawal' AND m.status='completed' ORDER BY m.amount DESC LIMIT 25""")[1]
    mon = q("SELECT toStartOfMonth(created_at) m, round(sum(amount)) FROM money_transactions WHERE type='manual_withdrawal' AND status='completed' GROUP BY m ORDER BY m")[1]
    kpis = (scard('alert orange','🧾','Ручных выводов', mn(tot), f'{f(cnt)} операций')
      + scard('','👤','Кто одобрял', f(napp), 'разных reviewed_by')
      + scard('alert orange','💥','Крупнейший', mn(biggest), 'одной операцией')
      + scard('','🛡','Админ-аккаунтов', f(len(admins)), 'role=admin / service'))
    arows = ''
    for rb, c, s, unclear in apprs:
        adm = ('<span class=badge style="background:#dcfce7;color:#166534">админ</span>' if rb in admins
               else '<span class=badge style="background:#fee2e2;color:#991b1b">⚠️ не админ</span>')
        uc = f'<span class="neg" style="font-weight:600">{f(unclear)}%</span>' if (unclear or 0) >= 40 else f'{f(unclear)}%'
        arows += f'<tr><td class=id>{rev_link(rb)}</td><td>{adm}</td><td class=num>{f(c)}</td><td class=num>{mn(s)}</td><td class=num>{uc}</td></tr>'
    trows = ''
    for pid, atp, amt, dt, rb, depd in tops:
        flag = ('<span class=badge style="background:#fee2e2;color:#991b1b">🚩 без депозита</span>'
                if float(depd or 0) < float(amt)*0.1 else '')
        trows += (f'<tr onclick="location.href=\'/player/{pid}\'"><td class=id>{pid}{at_badge(atp)}</td>'
          f'<td class=num>{mn(amt)}</td><td class=num>{f(depd)} ₺</td><td class=num>{dt}</td>'
          f'<td class=id>{rev_link(rb, True)}</td><td>{flag}</td></tr>')
    zd = q("""WITH mw AS (SELECT casino_player_id, sum(amount) wd, count() n FROM money_transactions WHERE type='manual_withdrawal' AND status='completed' GROUP BY casino_player_id),
      dp AS (SELECT casino_player_id, sumIf(amount,type IN ('deposit','manual_deposit') AND status='completed') dep FROM money_transactions GROUP BY casino_player_id)
      SELECT mw.casino_player_id, u.account_type, round(mw.wd), round(coalesce(dp.dep,0)), mw.n
      FROM mw LEFT JOIN dp ON dp.casino_player_id=mw.casino_player_id LEFT JOIN users u ON u.casino_player_id=mw.casino_player_id
      WHERE mw.wd > 50000 AND toFloat64(coalesce(dp.dep,0)) < toFloat64(mw.wd)*0.1 ORDER BY mw.wd DESC LIMIT 80""")[1]
    zd_total = sum(float(r[2] or 0) for r in zd)
    zdrows = ''
    for zpid, zat, zwd, zdep, zn in zd:
        zdrows += (f'<tr onclick="location.href=\'/player/{zpid}\'"><td class=id>{zpid}{at_badge(zat)}</td>'
          f'<td class=num>{mn(zwd)}</td><td class=num>{f(zdep)} ₺</td><td class=num>{f(zn)}</td></tr>')
    tst = q("""SELECT m.casino_player_id, u.account_type, round(sum(m.amount)), count()
      FROM money_transactions m LEFT JOIN users u USING(casino_player_id)
      WHERE m.type='manual_withdrawal' AND m.status='completed' AND positionCaseInsensitive(m.notes,'test')>0
      GROUP BY m.casino_player_id, u.account_type ORDER BY 3 DESC LIMIT 40""")[1]
    tst_total = sum(float(r[2] or 0) for r in tst)
    tstrows = ''.join(f'<tr onclick="location.href=\'/player/{tp}\'"><td class=id>{tp}{at_badge(ta)}</td><td class=num>{mn(ts)}</td><td class=num>{f(tn)}</td></tr>' for tp, ta, ts, tn in tst)
    AU = jsdump({'mon': [[str(m)[:7], float(v or 0)] for m, v in mon],
                     'cat': [[str(c), float(s or 0)] for c, s in cats]})
    top = ("<div class=topbar><div><div class=h1>Аудит ручных списаний <em>· manual_withdrawal</em></div>"
      "<div class=lead>это <b>не выплаты игрокам</b>, а списания казино: отмена бонус-выигрышей, истёкших бонусов, нарушений правил и тест-операции</div></div>"
      "<div class=pills><span class='pill live'>live</span></div></div>")
    body = (f'<div class=cards>{kpis}</div>'
      '<div class=eyebrow>За что списывали (по полю notes)</div>'
      '<div class=chartbox><div class=cap>почти всё — отмена бонус-выигрышей и нарушений, а не выплаты кэша</div><div class=chart id=c_cat style="height:270px"></div></div>'
      '<div class=eyebrow>Динамика по месяцам</div>'
      '<div class=chartbox><div class=cap>февральский всплеск</div><div class=chart id=c_mon style="height:230px"></div></div>'
      '<div class=eyebrow>Кто проводил списания (reviewed_by) <span class=muted style="text-transform:none;letter-spacing:0">· «Неясных %» = доля test / без пометки</span></div>'
      f'<div class=panel style="overflow-x:auto"><table><thead><tr><th>Оператор ID</th><th>Статус</th><th>Операций</th><th>Сумма</th><th>Неясных %</th></tr></thead><tbody>{arows}</tbody></table></div>'
      '<div class=eyebrow>Топ-25 ручных выводов</div>'
      f'<div class=panel style="overflow-x:auto"><table><thead><tr><th>Игрок</th><th>Вывел</th><th>Внёс всего</th><th>Дата</th><th>Одобрил</th><th>Флаг</th></tr></thead><tbody>{trows}</tbody></table></div>'
      f'<div class=eyebrow>Крупные списания у игроков без депозита</div>'
      f'<div class=lead style="margin:-4px 0 12px">{len(zd)} аккаунтов: списано &gt;50k ₺ при депозите &lt;10% · суммарно <b style="color:var(--primary)">{mn(zd_total)}</b> — это снятые <b>бонус-выигрыши</b> (нет депозита = играл на бонусы/фриспины)</div>'
      f'<div class=panel style="overflow-x:auto"><table><thead><tr><th>Игрок</th><th>Списано</th><th>Внёс всего</th><th>Операций</th></tr></thead><tbody>{zdrows}</tbody></table></div>'
      f'<div class=eyebrow>🧪 Тест-операции — исключить из метрик</div>'
      f'<div class=lead style="margin:-4px 0 12px">{len(tst)} аккаунтов с notes=«test» · суммарно <b style="color:var(--primary)">{mn(tst_total)}</b> (в осн. админы 1254/49 и тест-аккаунт 1426)</div>'
      f'<div class=panel style="overflow-x:auto"><table><thead><tr><th>Аккаунт</th><th>Сумма</th><th>Операций</th></tr></thead><tbody>{tstrows}</tbody></table></div>')
    js = "<script>const AU=" + AU + ";" + AUDIT_JS + "</script>"
    return layout('risk', top + body, head_extra=ECHARTS).replace('</body>', js + '</body>')

@app.route('/audit/reviewer/<rid>')
def reviewer(rid):
    isadm = q("SELECT count() FROM users WHERE toString(casino_player_id)={rid:String} AND (role IN ('admin','support') OR account_type='service')", {'rid': rid})[1][0][0]
    base = "m.type='manual_withdrawal' AND m.status='completed' AND m.reviewed_by={rid:String}"
    k = q(f"SELECT count(), round(sum(m.amount)), round(max(m.amount)), uniqExact(m.casino_player_id), min(toDate(m.created_at)), max(toDate(m.created_at)) FROM money_transactions m WHERE {base}", {'rid': rid})[1][0]
    if not k[0]: abort(404)
    mon = q(f"SELECT toStartOfMonth(m.created_at) mth, round(sum(m.amount)) FROM money_transactions m WHERE {base} GROUP BY mth ORDER BY mth", {'rid': rid})[1]
    zdc = q(f"""WITH dep AS (SELECT casino_player_id, sumIf(amount,type IN ('deposit','manual_deposit') AND status='completed') d FROM money_transactions GROUP BY casino_player_id)
      SELECT countIf(toFloat64(coalesce(dep.d,0)) < toFloat64(m.amount)*0.1), round(sumIf(m.amount, toFloat64(coalesce(dep.d,0)) < toFloat64(m.amount)*0.1))
      FROM money_transactions m LEFT JOIN dep ON dep.casino_player_id=m.casino_player_id WHERE {base}""", {'rid': rid})[1][0]
    tops = q(f"""WITH dep AS (SELECT casino_player_id, sumIf(amount,type IN ('deposit','manual_deposit') AND status='completed') d FROM money_transactions GROUP BY casino_player_id)
      SELECT m.casino_player_id, u.account_type, round(m.amount), toDate(toTimezone(m.created_at,'Europe/Istanbul')), round(dep.d)
      FROM money_transactions m LEFT JOIN users u USING(casino_player_id) LEFT JOIN dep ON dep.casino_player_id=m.casino_player_id
      WHERE {base} ORDER BY m.amount DESC LIMIT 40""", {'rid': rid})[1]
    badge = ('<span class=badge style="background:#dcfce7;color:#166534">админ / служебный</span>' if isadm
             else '<span class=badge style="background:#fee2e2;color:#991b1b">⚠️ обычный аккаунт, не помечен админом</span>')
    kc = lambda l, v: f'<div class=scard><div class=l>{l}</div><div class=v style="font-size:22px">{v}</div></div>'
    kpis = (kc('Одобрил операций', f(k[0])) + kc('На сумму', mn(k[1])) + kc('Крупнейшая', mn(k[2]))
      + kc('Разных игроков', f(k[3])) + kc('🚩 без депозита', f'{f(zdc[0])} · {mn(zdc[1])}'))
    trows = ''
    for pid, atp, amt, dt, depd in tops:
        flag = ('<span class=badge style="background:#fee2e2;color:#991b1b">🚩 без депозита</span>'
                if float(depd or 0) < float(amt)*0.1 else '')
        trows += (f'<tr onclick="location.href=\'/player/{pid}\'"><td class=id>{pid}{at_badge(atp)}</td>'
          f'<td class=num>{mn(amt)}</td><td class=num>{f(depd)} ₺</td><td class=num>{dt}</td><td>{flag}</td></tr>')
    cats = q(f"SELECT {CAT} cat, round(sum(m.amount)) FROM money_transactions m WHERE {base} GROUP BY cat ORDER BY 2 DESC", {'rid': rid})[1]
    AU = jsdump({'mon': [[str(m)[:7], float(v or 0)] for m, v in mon],
                     'cat': [[str(c), float(s or 0)] for c, s in cats]})
    top = (f'<a class=back href="/audit">← к аудиту</a>'
      f'<div class=topbar style="margin-top:10px"><div><div class=h1>Оператор списаний <em class=bd>{escape(rid)}</em></div>'
      f'<div class=lead>{badge} &nbsp; оператор ручных выводов · период {k[4]} → {k[5]}</div></div></div>')
    body = (f'<div class=cards>{kpis}</div>'
      '<div class=eyebrow>За что списывал (по notes)</div>'
      '<div class=chartbox><div class=chart id=c_cat style="height:220px"></div></div>'
      '<div class=eyebrow>Что списывал по месяцам</div>'
      '<div class=chartbox><div class=chart id=c_mon style="height:240px"></div></div>'
      '<div class=eyebrow>Топ выводов, которые он одобрил</div>'
      f'<div class=panel style="overflow-x:auto"><table><thead><tr><th>Игрок</th><th>Вывел</th><th>Внёс всего</th><th>Дата</th><th>Флаг</th></tr></thead><tbody>{trows}</tbody></table></div>')
    js = "<script>const AU=" + AU + ";" + AUDIT_JS + "</script>"
    return layout('risk', top + body, head_extra=ECHARTS).replace('</body>', js + '</body>')

# ============================ КЛЮЧИ ИНТЕГРАЦИИ (просмотр / регенерация) ============================
TOKENS_FILE = os.environ.get('TOKENS_FILE', '/secrets/tokens.json')
IPS_FILE = os.environ.get('IPS_FILE', '/secrets/allowed_ips.json')
TOKEN_LABELS = {'ingest_prod': 'HTTP ingest — PROD', 'ingest_test': 'HTTP ingest — TEST'}

def _load_tokens():
    try:
        with open(TOKENS_FILE) as fh:
            return json.load(fh)
    except Exception:
        return {}

def _save_tokens(d):
    with open(TOKENS_FILE, 'w') as fh:
        json.dump(d, fh, indent=2)

def _load_ips():
    try:
        with open(IPS_FILE) as fh:
            return [str(x).strip() for x in json.load(fh) if str(x).strip()]
    except Exception:
        return []

def _save_ips(lst):
    with open(IPS_FILE, 'w') as fh:
        json.dump(lst, fh, indent=2)

@app.route('/keys')
def keys():
    toks = _load_tokens()
    rows = ''
    for k, label in TOKEN_LABELS.items():
        val = toks.get(k, '')
        rows += (f'<tr><td>{escape(label)}</td>'
          f'<td class=id style="user-select:all;word-break:break-all">{escape(val) if val else "—"}</td>'
          f'<td><form method=post action="/keys/regenerate" style="margin:0" '
          f'onsubmit="return confirm(\'Пересоздать «{label}»? Старый токен сразу перестанет работать — не забудьте выдать новый казино.\')">'
          f'<input type=hidden name=which value="{k}">'
          f'<button type=submit style="cursor:pointer;background:var(--primary);color:#fff;border:0;border-radius:7px;padding:7px 12px;font-size:12px;font-weight:600">↻ пересоздать</button>'
          f'</form></td></tr>')
    table = ('<div class=panel style="overflow-x:auto"><table><thead><tr>'
      '<th>Ключ</th><th>Значение</th><th>Действие</th></tr></thead><tbody>' + rows + '</tbody></table></div>')
    curl_ex = ('<div class=eyebrow style="margin-top:16px">Как казино использует токен</div>'
      '<div class=panel><pre style="margin:0;white-space:pre-wrap;font-size:12px">'
      'curl -X POST https://cas.21do.xyz/ingest/events \\\n'
      '  -H "Authorization: Bearer &lt;токен&gt;" -H "Content-Type: application/json" \\\n'
      '  -d \'{"event_id":"...","event_type":"bet","casino_player_id":40,"ts":"...","bet_amount":5,"currency":"TRY"}\''
      '</pre></div>')
    # --- секция IP-allowlist ---
    ips = _load_ips()
    iprows = ''
    for ip in ips:
        iprows += (f'<tr><td class=id style="user-select:all">{escape(ip)}</td>'
          f'<td><form method=post action="/keys/ip/remove" style="margin:0" '
          f'onsubmit="return confirm(\'Удалить {escape(ip)} из белого списка?\')">'
          f'<input type=hidden name=ip value="{escape(ip)}">'
          f'<button type=submit style="cursor:pointer;background:#fee2e2;color:#b91c1c;border:0;border-radius:7px;padding:6px 11px;font-size:12px;font-weight:600">удалить</button>'
          f'</form></td></tr>')
    if not iprows:
        iprows = '<tr><td colspan=2 class=muted>список пуст — сейчас приём открыт для всех IP</td></tr>'
    ip_table = ('<div class=eyebrow style="margin-top:22px">IP-allowlist для <code>/ingest/events</code></div>'
      '<div class=lead style="margin:-2px 0 8px">только эти адреса могут слать события · пусто = разрешено всем · поддерживаются IP и CIDR</div>'
      '<div class=panel style="overflow-x:auto"><table><thead><tr><th>IP / CIDR</th><th>Действие</th></tr></thead><tbody>'
      + iprows + '</tbody></table></div>'
      '<form method=post action="/keys/ip/add" style="margin-top:10px;display:flex;gap:8px">'
      '<input name=ip placeholder="напр. 57.129.125.90 или 10.0.0.0/24" required '
      'style="flex:1;max-width:340px;padding:8px 11px;border:1px solid var(--hair);border-radius:7px;font-size:13px">'
      '<button type=submit style="cursor:pointer;background:var(--primary);color:#fff;border:0;border-radius:7px;padding:8px 14px;font-size:13px;font-weight:600">+ добавить IP</button>'
      '</form>')

    content = ('<div class=topbar><div><div class=h1>Интеграция <em class=bd>· ключи и доступ</em></div>'
      '<div class=lead>токены и IP-allowlist для приёма событий казино на <code>/ingest/events</code> · '
      'изменения применяются мгновенно · страница под basic-auth</div></div></div>'
      + '<div class=eyebrow>HTTP-токены</div>' + table + ip_table + curl_ex
      + '<div class=lead style="margin-top:14px">⚠️ Kafka-креды (SASL) меняются скриптом '
      '<code>create_producer.sh</code> на сервере — не из UI.</div>')
    return layout('keys', content)

@app.route('/keys/regenerate', methods=['POST'])
def keys_regenerate():
    which = request.form.get('which', '')
    if which not in TOKEN_LABELS:
        abort(400)
    toks = _load_tokens()
    toks[which] = _secrets.token_urlsafe(24)
    _save_tokens(toks)
    return Response(status=303, headers={'Location': '/keys'})

@app.route('/keys/ip/add', methods=['POST'])
def keys_ip_add():
    ip = (request.form.get('ip', '') or '').strip()
    try:
        ipaddress.ip_network(ip, strict=False)   # валидируем IP/CIDR
    except Exception:
        abort(400)
    ips = _load_ips()
    if ip not in ips:
        ips.append(ip)
        _save_ips(ips)
    return Response(status=303, headers={'Location': '/keys'})

@app.route('/keys/ip/remove', methods=['POST'])
def keys_ip_remove():
    ip = (request.form.get('ip', '') or '').strip()
    ips = [x for x in _load_ips() if x != ip]
    _save_ips(ips)
    return Response(status=303, headers={'Location': '/keys'})

# ============================ СИГНАЛЫ МОДЕЛИ (выход модели + realtime) ============================
_SIGNALS_CACHE = {}
_SIG_SQL = """
SELECT casino_player_id, toInt64(round(pred_ltv_d90)) AS ltv, p_churn, p_2nd_deposit,
       early_tier, action, bonus, toInt64(round(priority)) AS prio
FROM player_actions
WHERE pred_ltv_d90 > 0 OR p_churn IS NOT NULL
ORDER BY priority DESC
LIMIT 200
"""

def _signals_table():
    """Выход модели (то, что уходит казино) — кэш по дате данных (батч-скоринг)."""
    asof = str(data_asof())
    if asof in _SIGNALS_CACHE:
        return _SIGNALS_CACHE[asof]
    rows = q(_SIG_SQL)[1]
    tot, whales, avgp = q("SELECT count(), countIf(early_tier='D'), toInt64(round(avg(priority))) "
        "FROM player_actions WHERE pred_ltv_d90>0 OR p_churn IS NOT NULL")[1][0]
    acts = q("SELECT action, count() c FROM player_actions WHERE (pred_ltv_d90>0 OR p_churn IS NOT NULL) "
        "AND action!='' GROUP BY action ORDER BY c DESC LIMIT 1")[1]
    top_action = acts[0][0] if acts else '—'
    trs = ''
    for pid, ltv, pch, p2, tier, action, bonus, prio in rows:
        rsk = '—' if pch is None else f'{round(pch*100)}%'
        pnd = '—' if p2 is None else f'{round(p2*100)}%'
        trs += (f'<tr data-pid="{pid}" id="sig-{pid}" onclick="location.href=\'/player/{pid}\'">'
          f'<td class=id>{pid} <span class=onl id="onl-{pid}"></span></td>'
          f'<td class=num>{f(ltv)} ₺</td>'
          f'<td class="num {"neg" if (pch is not None and pch>=0.7) else ""}">{rsk}</td>'
          f'<td class=num>{pnd}</td>'
          f'<td>{tier_badge(tier) if tier else "—"}</td>'
          f'<td>{escape(str(action) or "—")}</td>'
          f'<td>{escape(str(bonus) or "—")}</td>'
          f'<td class=num><b>{f(prio)}</b></td></tr>')
    if not trs:
        trs = '<tr><td colspan=8 class=muted>модель ещё не скорена</td></tr>'
    payload = {'tbody': trs, 'total': tot or 0, 'whales': whales or 0, 'avgp': avgp or 0, 'top_action': top_action}
    _SIGNALS_CACHE.clear()
    _SIGNALS_CACHE[asof] = payload
    return payload

@app.route('/signals')
def signals():
    p = _signals_table()
    cards = ('<div class=cards>'
      + scard('', '🧠', 'Игроков со скором', f(p['total']), 'по ним есть сигналы модели')
      + scard('', '🟢', 'Играют сейчас', '<span id=sig-online>0</span>', 'из них активны в потоке (live)')
      + scard('orange', '🐋', 'Китов (тир D)', f(p['whales']), 'высшая ценность')
      + scard('cream', '🎯', 'Частое действие', escape(str(p['top_action'])), 'топ next-best-action')
      + '</div>')
    table = ('<div class=panel style="overflow-x:auto"><table><thead><tr>'
      '<th>Игрок</th><th title="прогноз депозитов за 90 дней">LTV прогноз</th>'
      '<th title="вероятность оттока за 30 дней">Риск</th><th title="вероятность следующего депозита">P(деп)</th>'
      '<th>Тир</th><th>Действие</th><th>Бонус</th><th title="приоритет: больше = важнее">Приоритет</th>'
      '</tr></thead><tbody id=sig-tbody>' + p['tbody'] + '</tbody></table></div>')
    content = ('<div class=topbar><div><div class=h1>Сигналы модели <em class=bd>· выход модели (real-time)</em></div>'
      '<div class=lead>ровно то, что уходит казино на <code>/signals</code>: прогноз LTV, риск оттока, вероятность депозита, '
      'рекомендованные действие и бонус, приоритет · <span id=sig-dot style="transition:opacity .3s">●</span> подсветка «играет сейчас» обновляется вживую по потоку событий</div></div></div>'
      + cards + '<div class=eyebrow style="margin-top:8px">Топ-200 по приоритету · 🟢 = активен в потоке сейчас · клик — карточка</div>' + table)
    js = ("<script>(function(){"
      "var on=document.getElementById('sig-online'),dot=document.getElementById('sig-dot');"
      "var es=new EventSource('/signals/stream');"
      "es.onmessage=function(e){try{var d=JSON.parse(e.data);var ids=d.online||[];"
      "document.querySelectorAll('#sig-tbody tr[data-pid]').forEach(function(tr){"
      "var live=ids.indexOf(parseInt(tr.dataset.pid))>=0;var b=document.getElementById('onl-'+tr.dataset.pid);"
      "if(b)b.textContent=live?'🟢':'';tr.style.background=live?'#f0fdf4':'';});"
      "if(on)on.textContent=ids.length;"
      "if(dot){dot.style.opacity=1;setTimeout(function(){dot.style.opacity=0.25;},300);}}catch(err){}};"
      "})();</script>")
    return layout('signals', content).replace('</body>', js + '</body>')

@app.route('/signals/stream')
def signals_stream():
    """SSE: id игроков, активных в потоке за последние 3 минуты (realtime-оверлей)."""
    def gen():
        while True:
            try:
                ids = [int(r[0]) for r in q("SELECT DISTINCT casino_player_id FROM live_events "
                    "WHERE ts > now64(3) - toIntervalMinute(3) LIMIT 5000")[1]]
                payload = json.dumps({'online': ids})
            except Exception:
                _local.ch = None
                payload = json.dumps({'online': []})
            yield 'data: ' + payload + '\n\n'
            time.sleep(3)
    return Response(gen(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

# ============================ БОНУСЫ: КАТАЛОГ + ПОДБОР ============================
_BONUS_CACHE = {}

# Подписи условий оффера по локали. Значения самих полей берём из каталога через
# bonus_catalog.loc_field (там же фолбэк на русский). Суммы/₺/имена игр не переводим.
OFFER_LBL = {
    'min_deposit':  {'ru': 'мин деп',      'en': 'min deposit', 'tr': 'min yatırma'},
    'min_loss':     {'ru': 'мин проигрыш', 'en': 'min loss',    'tr': 'min kayıp'},
    'max_bonus':    {'ru': 'макс',         'en': 'max',         'tr': 'max'},
    'max_refund':   {'ru': 'возврат до',   'en': 'refund up to', 'tr': 'iade limiti'},
    'game':         {'ru': 'игра',         'en': 'game',        'tr': 'oyun'},
    'wager':        {'ru': 'вейджер:',     'en': 'wager:',      'tr': 'çevrim:'},
}

# Фолбэк-названия, когда акции нет (оффер не подобран / игрок на ревью).
OFFER_NONE_LBL = {
    'review': {'ru': '⚠ без бонуса — игрок в плюсе (ревью)',
               'en': '⚠ no bonus — player is up (review)',
               'tr': '⚠ bonus yok — oyuncu kârda (inceleme)'},
}

def _lbl(key, locale='ru'):
    """Подпись условия оффера на нужном языке (фолбэк — русский)."""
    row = OFFER_LBL.get(key, {})
    return row.get(locale) or row.get('ru') or key


# ── Витринные поля player_actions (marts.sql) — фиксированные русские фразы ──
# `when_to` и `bonus` собирает SQL-витрина (multiIf в retention.player_actions),
# поэтому в API они приезжают по-русски и оператору-турку не читаются. Набор
# значений ЗАКРЫТЫЙ (см. marts.sql), поэтому переводим точным маппингом.
# Незнакомая фраза (изменили витрину) → отдаём как есть, а не пустоту.
WHEN_TO_I18N = {
    'сейчас': {'en': 'now', 'tr': 'şimdi'},
    'сейчас (играет без депозита)': {
        'en': 'now (playing without a deposit)', 'tr': 'şimdi (yatırımsız oynuyor)'},
    'окно 2-го депозита (ближайшие дни)': {
        'en': '2nd deposit window (next few days)', 'tr': '2. yatırım penceresi (yakın günler)'},
    'к следующей сессии': {'en': 'by the next session', 'tr': 'bir sonraki oturuma kadar'},
}

BONUS_I18N = {
    'бонус на первый депозит': {
        'en': 'first deposit bonus', 'tr': 'ilk yatırım bonusu'},
    'релоад-бонус на 2-й депозит': {
        'en': 'reload bonus on the 2nd deposit', 'tr': '2. yatırıma reload bonusu'},
    'VIP-оффер (кэшбэк / деп-матч)': {
        'en': 'VIP offer (cashback / deposit match)', 'tr': 'VIP teklif (cashback / yatırım eşleme)'},
    'релоад / кэшбэк': {'en': 'reload / cashback', 'tr': 'reload / cashback'},
    '⚠ без бонуса — игрок в плюсе (ревью)': {
        'en': '⚠ no bonus — player is up (review)', 'tr': '⚠ bonus yok — oyuncu kârda (inceleme)'},
}

# 'фриспины · PragmaticPlay' — префикс переводим, имя провайдера НЕТ (это данные).
_FS_PREFIX = 'фриспины · '
_FS_I18N = {'en': 'freespins · ', 'tr': 'freespin · '}


def when_to_label(raw, locale='ru'):
    """`when_to` из витрины на языке оператора (фолбэк — исходная фраза)."""
    if not raw or locale == 'ru':
        return raw
    return WHEN_TO_I18N.get(raw, {}).get(locale) or raw


def bonus_label(raw, locale='ru'):
    """`bonus` из витрины на языке оператора. Фриспины с провайдером
    ('фриспины · PragmaticPlay') — переводим только префикс."""
    if not raw or locale == 'ru':
        return raw
    if raw.startswith(_FS_PREFIX):
        return _FS_I18N.get(locale, _FS_PREFIX) + raw[len(_FS_PREFIX):]
    return BONUS_I18N.get(raw, {}).get(locale) or raw

def offer_terms(b, locale='ru'):
    """Краткие условия акции одной строкой (для оператора), на языке интерфейса."""
    if not b:
        return ''
    from bonus_catalog import loc_field
    p = []
    vp = b.get('vip_percent')
    if vp:
        p.append(f"{min(vp.values())}–{max(vp.values())}%")
    elif b.get('percent'):
        p.append(f"{b['percent']}%")
    if b.get('min_deposit'):  p.append(f"{_lbl('min_deposit', locale)} {f(b['min_deposit'])}₺")
    if b.get('min_loss'):     p.append(f"{_lbl('min_loss', locale)} {f(b['min_loss'])}₺")
    if b.get('max_bonus'):    p.append(f"{_lbl('max_bonus', locale)} {f(b['max_bonus'])}₺")
    if b.get('max_refund'):   p.append(f"{_lbl('max_refund', locale)} {f(b['max_refund'])}₺")
    if b.get('game'):         p.append(f"{_lbl('game', locale)} {b['game']}")   # имя игры не переводим
    if b.get('wager'):        p.append(f"{_lbl('wager', locale)} {loc_field(b, 'wager', locale)}")
    return ' · '.join(p)

def offer_for(p, locale='ru'):
    """Реальная акция из каталога под игрока → (название, условия, причина).
    Заменяет придуманные фразы из marts.sql («VIP-оффер (кэшбэк / деп-матч)»).
    locale — язык оператора (ru/en/tr); дефолт 'ru' держит старый борд без правок."""
    from bonus_catalog import match_bonus_detail, render_why, loc_field, REVIEW_CODE
    try:
        b, code, params = match_bonus_detail(p)
        why = render_why(code, params, locale)
    except Exception:
        return ('—', '', '')
    if not b:
        # «в плюсе → ревью» отличаем по КОДУ причины, а не по подстроке: подстрока
        # ломалась бы на любом языке, кроме русского.
        if code == REVIEW_CODE:
            nm = OFFER_NONE_LBL['review'].get(locale) or OFFER_NONE_LBL['review']['ru']
        else:
            nm = render_why('no_match', locale=locale)
        return (nm, '', why)
    return (loc_field(b, 'name', locale), offer_terms(b, locale), why)

def bonus_name_for(bid, locale='ru'):
    """Название акции по id на языке интерфейса (для распределений в отчётах)."""
    from bonus_catalog import bonus_name
    try:
        return bonus_name(bid, locale)
    except Exception:
        return bid

def offer_cell(p):
    """HTML-ячейка оффера для таблиц: название + условия мелким шрифтом."""
    name, terms, why = offer_for(p)
    t = f'<br><span class=muted style="font-size:11px">{escape(terms)}</span>' if terms else ''
    return f'<b>{escape(name)}</b>{t}'

def _bonus_distribution():
    """Для каждой акции — сколько игроков ей подобрано (кэш по дате данных).

    Кэш локаль-НЕзависим: в examples кладём и готовую русскую причину (ex[1] —
    для HTML-борда), и код+параметры (ex[2], ex[3] — чтобы API отрисовал причину
    на языке оператора через bonus_catalog.render_why, не пересчитывая подбор
    по всей базе на каждый язык)."""
    from bonus_catalog import match_bonus_detail, render_why
    asof = str(data_asof())
    if asof in _BONUS_CACHE:
        return _BONUS_CACHE[asof]
    rows = q("""SELECT pf.casino_player_id, pf.lifecycle, pf.dep_count, pf.net,
                       pa.early_tier, pa.pred_ltv_d90, pa.p_churn,
                       ifNull(pa.value_try, 0), ifNull(pa.action, ''), pf.net_cash
                FROM player_features pf
                LEFT JOIN player_actions pa USING (casino_player_id)
                LEFT JOIN player_vip_churn_ml vc ON vc.casino_player_id = pf.casino_player_id
                LEFT JOIN player_early_vip_ml ev ON ev.casino_player_id = pf.casino_player_id
                LEFT JOIN player_non_promising_vip_ml np ON np.casino_player_id = pf.casino_player_id
                WHERE pf.account_type='normal'""")[1]
    counts, examples, names, values = {}, {}, {}, {}
    for pid, life, dc, net, tier, ltv, churn, val, action, net_cash in rows:
        b, code, params = match_bonus_detail({'lifecycle': life, 'dep_count': dc, 'net': net,
                                              'net_cash': net_cash, 'early_tier': tier,
                                              'pred_ltv_d90': ltv, 'p_churn': churn})
        bid = b['id'] if b else '—'
        counts[bid] = counts.get(bid, 0) + 1
        names[bid] = b['name_ru'] if b else 'подходящей акции нет'
        if action != 'наблюдать':                       # ценность «в работе»
            values[bid] = values.get(bid, 0) + float(val or 0)
        if bid not in examples:
            examples[bid] = (int(pid), render_why(code, params), code, params)
    payload = {'counts': counts, 'examples': examples, 'total': len(rows),
               'names': names, 'values': values}
    _BONUS_CACHE.clear(); _BONUS_CACHE[asof] = payload
    return payload

KIND_LBL = {'welcome': ('🎁', 'велком'), 'reload': ('🔄', 'релоад'), 'cashback': ('💸', 'кэшбэк'),
            'freespins': ('🎰', 'фриспины'), 'vip_deposit': ('👑', 'VIP'), 'insurance': ('🛡', 'страховка'),
            'referral': ('🤝', 'реферал')}

@app.route('/bonuses')
def bonuses():
    from bonus_catalog import load_catalog, _available_today
    cat = load_catalog()
    dist = _bonus_distribution()
    counts, examples, total = dist['counts'], dist['examples'], dist['total']
    matched = sum(v for k, v in counts.items() if k != '—')

    cards = ('<div class=cards>'
      + scard('', '🎯', 'Акций в каталоге', f(len(cat['bonuses'])), 'из BillionBahis_бонусы.md')
      + scard('', '✅', 'Доступны сегодня', f(sum(1 for b in cat['bonuses'] if _available_today(b))), 'по дню недели')
      + scard('orange', '👥', 'Игроков с подбором', f(matched), f'из {f(total)} обычных')
      + scard('cream', '🔝', 'Самая частая', escape(max(counts, key=counts.get) if counts else '—'), 'кому подобрана чаще всего')
      + '</div>')

    rows = ''
    for b in sorted(cat['bonuses'], key=lambda x: -counts.get(x['id'], 0)):
        n = counts.get(b['id'], 0)
        ic, kind = KIND_LBL.get(b['kind'], ('•', b['kind']))
        today_ok = _available_today(b)
        vip = b.get('vip_percent')
        pct = (f"{min(vip.values())}–{max(vip.values())}%" if vip else
               (f"{b['percent']}%" if b.get('percent') else '—'))
        limits = []
        if b.get('min_deposit'): limits.append(f"мин деп {f(b['min_deposit'])}₺")
        if b.get('min_loss'): limits.append(f"мин проигрыш {f(b['min_loss'])}₺")
        if b.get('max_bonus'): limits.append(f"макс {f(b['max_bonus'])}₺")
        ex = examples.get(b['id'])
        exs = (f'<span class=muted>напр. игрок <a href="/player/{ex[0]}">{ex[0]}</a> — {escape(ex[1])}</span>'
               if ex else '<span class=muted>никому не подобрана сегодня</span>')
        rows += (f'<tr>'
          f'<td>{ic} <b>{escape(b["name_ru"])}</b><br><span class=muted style="font-size:11px">{escape(b["name_tr"])}</span></td>'
          f'<td>{escape(kind)}<br><span class=muted>{escape(b["area"])}</span></td>'
          f'<td class=num>{pct}</td>'
          f'<td><span class=muted>{escape(" · ".join(limits) or "—")}</span></td>'
          f'<td>{"🟢" if today_ok else "⚪"}<br><span class=muted style="font-size:11px">{escape(",".join(b["days"]))}</span></td>'
          f'<td class=num><b>{f(n)}</b></td>'
          f'<td>{exs}</td></tr>')

    table = ('<div class=panel style="overflow-x:auto"><table><thead><tr>'
      '<th>Акция</th><th>Тип / зона</th><th>%</th><th>Лимиты</th>'
      '<th title="доступна сегодня по дню недели">Сегодня</th>'
      '<th title="сколько игроков подобрано этой акции">Игроков</th><th>Пример подбора</th>'
      '</tr></thead><tbody>' + rows + '</tbody></table></div>')

    content = ('<div class=topbar><div><div class=h1>Бонусы <em class=bd>· каталог и подбор</em></div>'
      '<div class=lead>реальные акции BillionBahis · для каждого игрока правила подбирают конкретную акцию '
      'по его состоянию (депозиты, проигрыш, риск оттока, тир) · источник правды — '
      '<code>BillionBahis_бонусы.md</code> → <code>bonuses.json</code></div></div></div>'
      + cards
      + '<div class=eyebrow style="margin-top:8px">Каталог · отсортирован по охвату игроков</div>' + table
      + '<div class=lead style="margin-top:14px">⚠️ Подбор пока используется <b>внутри дашборда</b>. '
      'Чтобы конкретный <code>promo_id</code> уходил в казино вместе с сигналом, они должны принять новое поле '
      '(сейчас шлём обобщённые enum-коды — см. INTEGRATION.md §8).</div>')
    return layout('bonuses', content)

def _warm_cohorts():
    """Прогрев тяжёлой страницы /cohorts в фоне при старте — чтобы первый
    пользователь после пересборки не ждал ~6с (ждём готовности ClickHouse)."""
    for _ in range(40):
        try:
            cohorts()   # считает запросы и наполняет _COHORTS_CACHE как побочный эффект
            print('[warm] cohorts cache prewarmed', flush=True)
            return
        except Exception as e:
            print(f'[warm] cohorts not ready, retry in 5s: {e}', flush=True)
            time.sleep(5)

# ── JSON-API для SPA (пакет api/*): авто-регистрация всех blueprint'ов (агент A3) ──
from api import register_api
register_api(app)

if __name__=='__main__':
    threading.Thread(target=_warm_cohorts, daemon=True).start()
    app.run(host=BOARD_HOST, port=BOARD_PORT, debug=False, threaded=True)
