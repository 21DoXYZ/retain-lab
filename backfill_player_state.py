"""
Бэкфилл ежедневных состояний игрока (retention.player_state_daily) из raw-фактов.

ЗАЧЕМ. Живой снапшот (player_state_daily.sql, шаг run_loop) начал КОПИТЬ срез
состояния только «с сегодня». Конструктору отчётов нужна историческая
корректность сегментов с ПЕРВОГО дня данных: «кто БЫЛ VIP в феврале». vip_level и
lifecycle — детерминированные функции истории депозитов/ставок, поэтому прошлое
восстановимо задним числом ровно теми же правилами, что и текущий срез
(player_features.sql). Модельные скоры (p_churn / pred_ltv_d90) задним числом
честно НЕДОСТУПНЫ — пишем NULL.

ЧТО СЧИТАЕТСЯ НА ДАТУ T (бизнес-день Стамбула, конец дня → UTC-cutoff):
  - vip_level(T): правило казино (player_features.sql:66-69) над КУМУЛЯТИВНЫМИ
    успешными TRY-депозитами до T + гейт «макс. разовый депозит ≥100 TRY» к T.
  - lifecycle(T): multiIf по dateDiff('day', последняя ставка ≤ T, T) —
    пороги 7/30/60/90; 'never', если ставок ещё не было.
  - dep_sum/dep_count/net/net_cash(T): кумулятивы до T (формулы player_features).
  - early_tier(T): tier по депозитам первой недели от FTD; показывается ТОЛЬКО
    когда к T прошло ≥7 дней от FTD (иначе '' — tier ещё «зреет»).
  - p_churn / pred_ltv_d90: NULL (модели задним числом нет).

ТЕХНИКА КУМУЛЯТИВОВ. 61 млн игровых транзакций сканируем ОДИН раз: строим
per-(игрок, бизнес-день) дельты (депозиты/ставки/выигрыши/последняя ставка),
затем оконными агрегатами sum()/max() OVER (PARTITION BY игрок ORDER BY день)
получаем кумулятив НА КАЖДЫЙ активный день. Итог кладём во временную таблицу
psd_bf_cum_tmp. Далее ЗА КАЖДЫЙ МЕСЯЦ — один INSERT: календарь дней месяца
CROSS JOIN игроки (reg_date ≤ T) ASOF LEFT JOIN кумулятив (последний активный
день ≤ T). ASOF-джойн переносит состояние вперёд на дни без событий, LEFT даёт 0
(не NULL) новичкам без активности — ровно как в остальной аналитике.

ДИАПАЗОН. По умолчанию: от min(первого события money/game, бизнес-день Стамбула)
до (max(snap_date) существующей таблицы − 1 день) — т.е. НЕ трогаем день живого
снапшота W3. Частичный прогон — флагами --from / --to (YYYY-MM-DD).

ИДЕМПОТЕНТНОСТЬ. Таблица — ReplacingMergeTree, PARTITION BY toYYYYMM(snap_date).
Перед вставкой месяца: если КАЛЕНДАРНЫЙ месяц ЦЕЛИКОМ внутри диапазона прогона —
DROP PARTITION (чистая замена). Если месяц частичный (граница --to ИЛИ месяц с
живым снапшотом, напр. 2026-07 с 15-м числом) — партицию НЕ дропаем: повторная
вставка того же (snap_date, id) схлопнется при чтении через FINAL.

Запуск:  .venv/bin/python backfill_player_state.py            # полный бэкфилл
         .venv/bin/python backfill_player_state.py --from 2026-02-01 --to 2026-02-28
"""
import os
import argparse
from datetime import date, timedelta

import clickhouse_connect

CH = dict(host=os.environ.get('CH_HOST', '127.0.0.1'), port=int(os.environ.get('CH_PORT', '8123')),
          username=os.environ.get('CH_USER', 'default'), password=os.environ.get('CH_PASSWORD', ''),
          database=os.environ.get('CH_DB', 'retention'))

TABLE = 'retention.player_state_daily'
CUM_TMP = 'retention.psd_bf_cum_tmp'        # кумулятив состояния на каждый активный день (мой temp)
PLAYER_TMP = 'retention.psd_bf_player_tmp'  # 1 строка на игрока: reg/ftd/account/early_tier (мой temp)

# Правило VIP казино над кумулятивными TRY-депозитами (player_features.sql:66-69).
# Гейт: макс. разовый TRY-депозит ≥100 И суммарные TRY-депозиты ≥100 → иначе 0.
VIP_EXPR = """toUInt8(multiIf(cs.cum_max_dep_try<100 OR cs.cum_cash_dep_try<100, 0,
        cs.cum_cash_dep_try>=1000000, 5, cs.cum_cash_dep_try>=500000, 4,
        cs.cum_cash_dep_try>=150000, 3, cs.cum_cash_dep_try>=50000, 2, 1))"""

# lifecycle по «дней с последней ставки до T» (player_features.sql:92-96).
# last_bet — running-max UTC-таймстампа ставок ≤ T; 0 = ставок ещё не было.
LIFECYCLE_EXPR = """multiIf(cs.cum_last_bet_epoch=0, 'never',
        dateDiff('day', toDate(toDateTime(cs.cum_last_bet_epoch)), base.T)<=7,  'active',
        dateDiff('day', toDate(toDateTime(cs.cum_last_bet_epoch)), base.T)<=30, 'cooling',
        dateDiff('day', toDate(toDateTime(cs.cum_last_bet_epoch)), base.T)<=60, 'at_risk',
        dateDiff('day', toDate(toDateTime(cs.cum_last_bet_epoch)), base.T)<=90, 'dormant', 'churned')"""


def _d(s: str) -> date:
    return date.fromisoformat(s)


def build_cum_tmp(client, upper: date) -> None:
    """
    Один тяжёлый скан. Строит per-(игрок, бизнес-день Стамбула) дельты из money +
    game (61M строк — здесь единственный раз), затем оконными кумулятивами получает
    состояние на каждый активный день. Только события с бизнес-днём ≤ upper.
    """
    client.command(f"DROP TABLE IF EXISTS {CUM_TMP}")
    client.command(f"""
        CREATE TABLE {CUM_TMP}
        (
          casino_player_id    UInt32,
          event_day           Date,
          cum_dep_count       UInt64,
          cum_dep_sum         Float64,
          cum_cash_deposits   Float64,
          cum_withdrawals_abs Float64,
          cum_cash_dep_try    Float64,
          cum_max_dep_try     Float64,
          cum_turnover        Float64,
          cum_wins            Float64,
          cum_last_bet_epoch  UInt32
        )
        ENGINE = MergeTree ORDER BY (casino_player_id, event_day)
    """)
    client.command(f"""
        INSERT INTO {CUM_TMP}
        SELECT
          casino_player_id, bday AS event_day,
          sum(d_dep_count)       OVER w AS cum_dep_count,
          sum(d_dep_sum)         OVER w AS cum_dep_sum,
          sum(d_cash_deposits)   OVER w AS cum_cash_deposits,
          sum(d_withdrawals_abs) OVER w AS cum_withdrawals_abs,
          sum(d_cash_dep_try)    OVER w AS cum_cash_dep_try,
          max(d_max_dep_try)     OVER w AS cum_max_dep_try,
          sum(d_turnover)        OVER w AS cum_turnover,
          sum(d_wins)            OVER w AS cum_wins,
          max(d_last_bet_epoch)  OVER w AS cum_last_bet_epoch
        FROM (
          SELECT casino_player_id, bday,
            sum(d_dep_count)       AS d_dep_count,
            sum(d_dep_sum)         AS d_dep_sum,
            sum(d_cash_deposits)   AS d_cash_deposits,
            sum(d_withdrawals_abs) AS d_withdrawals_abs,
            sum(d_cash_dep_try)    AS d_cash_dep_try,
            max(d_max_dep_try)     AS d_max_dep_try,
            sum(d_turnover)        AS d_turnover,
            sum(d_wins)            AS d_wins,
            max(d_last_bet_epoch)  AS d_last_bet_epoch
          FROM (
            -- money-сторона: депозиты/выводы/TRY-депозиты (кэш по спеке казино)
            SELECT casino_player_id, toDate(toTimezone(created_at,'Europe/Istanbul')) AS bday,
              toUInt64(countIf(type IN ('deposit','manual_deposit') AND status='completed'))                          AS d_dep_count,
              toFloat64(sumIf(amount, type IN ('deposit','manual_deposit') AND status='completed'))                   AS d_dep_sum,
              toFloat64(sumIf(amount, type='deposit' AND status IN ('completed','approved','success')))               AS d_cash_deposits,
              toFloat64(sumIf(abs(amount), type='withdrawal' AND status IN ('completed','approved','success')))       AS d_withdrawals_abs,
              toFloat64(sumIf(amount, type='deposit' AND status IN ('completed','approved','success') AND currency='TRY')) AS d_cash_dep_try,
              toFloat64(maxIf(amount, type='deposit' AND status IN ('completed','approved','success') AND currency='TRY')) AS d_max_dep_try,
              toFloat64(0) AS d_turnover, toFloat64(0) AS d_wins, toUInt32(0) AS d_last_bet_epoch
            FROM retention.money_transactions
            WHERE toDate(toTimezone(created_at,'Europe/Istanbul')) <= toDate('{upper.isoformat()}')
            GROUP BY casino_player_id, bday
            UNION ALL
            -- game-сторона: оборот/выигрыш/последняя ставка (для net и lifecycle)
            SELECT casino_player_id, toDate(toTimezone(created_at,'Europe/Istanbul')) AS bday,
              toUInt64(0), toFloat64(0), toFloat64(0), toFloat64(0), toFloat64(0), toFloat64(0),
              toFloat64(sumIf(bet_amount, transaction_type IN ('bet','freespins_bet')))                              AS d_turnover,
              toFloat64(sumIf(win_amount, transaction_type IN ('win','freespins_win')))                             AS d_wins,
              toUInt32(maxIf(toUnixTimestamp(created_at), transaction_type IN ('bet','freespins_bet')))              AS d_last_bet_epoch
            FROM retention.game_transactions
            WHERE status='completed' AND toDate(toTimezone(created_at,'Europe/Istanbul')) <= toDate('{upper.isoformat()}')
            GROUP BY casino_player_id, bday
          )
          GROUP BY casino_player_id, bday
        )
        WINDOW w AS (PARTITION BY casino_player_id ORDER BY event_day ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
    """)
    rows, players = client.query(
        f"SELECT count(), uniqExact(casino_player_id) FROM {CUM_TMP}").result_rows[0]
    print(f"  · {CUM_TMP}: {rows} строк-состояний по {players} активным игрокам")


def build_player_tmp(client) -> None:
    """
    1 строка на игрока: reg_date, account_type, ftd_date и early_tier (tier по
    депозитам первых 7 дней от FTD — как в вьюхе player_ltv, marts.sql:64;
    только account_type='normal' + есть FTD, иначе tier пустой).
    """
    client.command(f"DROP TABLE IF EXISTS {PLAYER_TMP}")
    client.command(f"""
        CREATE TABLE {PLAYER_TMP} (
          casino_player_id UInt32,
          reg_date_d       Date,
          account_type     LowCardinality(String),
          ftd_date         Nullable(Date),
          early_tier_final String
        ) ENGINE = MergeTree ORDER BY casino_player_id
    """)
    client.command(f"""
        INSERT INTO {PLAYER_TMP}
        SELECT u.casino_player_id, toDate(u.reg_date) AS reg_date_d, u.account_type,
          if(u.ftd_date IS NULL, CAST(NULL AS Nullable(Date)), toDate(u.ftd_date)) AS ftd_date,
          ifNull(t.early_tier_final, '') AS early_tier_final
        FROM retention.users u
        LEFT JOIN (
          SELECT casino_player_id, multiIf(d7<1000,'A', d7<3000,'B', d7<10000,'C','D') AS early_tier_final
          FROM (
            SELECT u.casino_player_id AS casino_player_id,
              sumIf(toFloat64(m.amount),
                    m.type IN ('deposit','manual_deposit') AND m.status='completed'
                    AND dateDiff('day', toDate(u.ftd_date), toDate(m.created_at)) BETWEEN 0 AND 7) AS d7
            FROM retention.users u
            INNER JOIN retention.money_transactions m USING (casino_player_id)
            WHERE u.account_type='normal' AND u.ftd_date IS NOT NULL
            GROUP BY u.casino_player_id
          )
        ) t ON t.casino_player_id = u.casino_player_id
    """)
    n = client.query(f"SELECT count() FROM {PLAYER_TMP}").result_rows[0][0]
    print(f"  · {PLAYER_TMP}: {n} игроков")


def insert_month(client, m_start: date, m_end: date, full_month: bool) -> tuple[int, float]:
    """
    Один INSERT на месяц. Календарь дней [m_start..m_end] CROSS JOIN игроки
    (reg_date ≤ T) ASOF LEFT JOIN кумулятив. Идемпотентность: full_month=True →
    DROP PARTITION перед вставкой; иначе полагаемся на ReplacingMergeTree.
    Возвращает (число_строк, секунды).
    """
    import time
    yyyymm = m_start.year * 100 + m_start.month
    if full_month:
        client.command(f"ALTER TABLE {TABLE} DROP PARTITION {yyyymm}")
    ndays = (m_end - m_start).days + 1
    t0 = time.perf_counter()
    client.command(f"""
        INSERT INTO {TABLE}
          (snap_date, casino_player_id, vip_level, lifecycle, dep_sum, dep_count,
           net, net_cash, early_tier, p_churn, pred_ltv_d90)
        WITH base AS (
          SELECT p.casino_player_id AS pid, p.account_type AS acct,
                 p.ftd_date AS ftd_date, p.early_tier_final AS tier_final, cal.T AS T
          FROM (SELECT toDate('{m_start.isoformat()}') + number AS T FROM numbers({ndays})) cal
          CROSS JOIN {PLAYER_TMP} p
          WHERE p.reg_date_d <= cal.T
        )
        SELECT
          base.T                                            AS snap_date,
          base.pid                                          AS casino_player_id,
          {VIP_EXPR}                                        AS vip_level,
          {LIFECYCLE_EXPR}                                  AS lifecycle,
          round(cs.cum_dep_sum, 2)                          AS dep_sum,
          toUInt32(cs.cum_dep_count)                        AS dep_count,
          round(cs.cum_wins - cs.cum_turnover, 2)           AS net,
          round(cs.cum_cash_deposits - cs.cum_withdrawals_abs, 2) AS net_cash,
          if(base.acct='normal' AND base.ftd_date IS NOT NULL
             AND dateDiff('day', base.ftd_date, base.T) >= 7, base.tier_final, '') AS early_tier,
          CAST(NULL AS Nullable(Float32))                   AS p_churn,
          CAST(NULL AS Nullable(Float64))                   AS pred_ltv_d90
        FROM base
        ASOF LEFT JOIN {CUM_TMP} AS cs
          ON cs.casino_player_id = base.pid AND base.T >= cs.event_day
    """)
    dt = time.perf_counter() - t0
    if not full_month:
        # Частичный месяц (граница --to / месяц с живым снапшотом): партицию не
        # дропали → повторный прогон оставит сырые дубли (snap_date,id). Схлопываем
        # их сразу, чтобы raw-строки не копились между фоновыми мержами (чтение и
        # так через FINAL; живой снапшот с уникальным snap_date не затрагивается).
        client.command(f"OPTIMIZE TABLE {TABLE} PARTITION {yyyymm} FINAL")
    n = client.query(
        "SELECT count() FROM {t} WHERE snap_date BETWEEN %(a)s AND %(b)s".format(t=TABLE),
        parameters={'a': m_start, 'b': m_end}).result_rows[0][0]
    tag = 'DROP+INSERT' if full_month else 'INSERT(replacing+optimize)'
    print(f"  · {m_start:%Y-%m} [{m_start}..{m_end}] {tag}: {n} строк за {dt:.1f}с")
    return n, dt


def iter_months(eff_from: date, eff_to: date):
    """Отдаёт (m_start, m_end, full_month) по календарным месяцам в [eff_from, eff_to]."""
    cur = eff_from.replace(day=1)
    while cur <= eff_to:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)  # 1-е след. месяца
        month_last = nxt - timedelta(days=1)
        m_start = max(cur, eff_from)
        m_end = min(month_last, eff_to)
        full_month = (cur >= eff_from) and (month_last <= eff_to)  # весь календарный месяц внутри
        yield m_start, m_end, full_month
        cur = nxt


def run_sanity(client, eff_to: date) -> None:
    """Проверки корректности (по ТЗ W5-T1, шаг sanity)."""
    print("\n=== SANITY ===")
    # (а) VIP только растёт: vip>=3 на последнюю дату бэкфилла ≤ текущий player_features
    cur_pf = client.query(
        "SELECT countIf(vip_level>=3) FROM retention.player_features").result_rows[0][0]
    bf = client.query(
        f"SELECT countIf(vip_level>=3) FROM {TABLE} FINAL WHERE snap_date=%(d)s",
        parameters={'d': eff_to}).result_rows[0][0]
    flag = 'OK (≤)' if bf <= cur_pf else 'ВНИМАНИЕ (> текущего!)'
    print(f"(а) vip_level>=3: бэкфилл {eff_to} = {bf}  vs  player_features сейчас = {cur_pf}  → {flag}")

    # (б) траектория тест-игрока 808 — vip_level должен монотонно расти до 5
    ctrl = ['2025-12-19', '2026-01-07', '2026-01-17', '2026-03-03', '2026-04-15']
    ctrl = [c for c in ctrl if _d(c) <= eff_to]
    rows = client.query(
        f"SELECT snap_date, vip_level, lifecycle, round(dep_sum) FROM {TABLE} FINAL "
        "WHERE casino_player_id=808 AND snap_date IN %(ds)s ORDER BY snap_date",
        parameters={'ds': ctrl}).result_rows
    print("(б) игрок 808 (Royal) — контрольные даты (vip должен расти до 5):")
    prev = -1
    mono = True
    for d, vip, lc, dep in rows:
        mono = mono and vip >= prev
        prev = vip
        print(f"      {d}  vip={vip}  {lc:8s}  dep_sum≈{dep:.0f}")
    print(f"      монотонность vip: {'OK' if mono else 'НАРУШЕНА'}")

    # (в) число строк по месяцам
    print("(в) строк по месяцам (partition):")
    for ym, n in client.query(
            f"SELECT toYYYYMM(snap_date) ym, count() FROM {TABLE} FINAL "
            "WHERE snap_date<=%(d)s GROUP BY ym ORDER BY ym", parameters={'d': eff_to}).result_rows:
        print(f"      {ym}: {n}")
    tot = client.query(
        f"SELECT count() FROM {TABLE} FINAL WHERE snap_date<=%(d)s",
        parameters={'d': eff_to}).result_rows[0][0]
    print(f"      ИТОГО (бэкфилл, ≤{eff_to}): {tot}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Бэкфилл retention.player_state_daily из raw-фактов")
    ap.add_argument('--from', dest='dfrom', help="начало диапазона YYYY-MM-DD (по умолч. — первый день данных)")
    ap.add_argument('--to', dest='dto', help="конец диапазона YYYY-MM-DD (по умолч. — день перед max(snap_date))")
    ap.add_argument('--keep-tmp', action='store_true', help="не удалять временные таблицы после прогона")
    args = ap.parse_args()

    client = clickhouse_connect.get_client(**CH)

    # Границы диапазона (всё — от дат ДАННЫХ, никаких now()/today()).
    first_event = client.query(
        "SELECT least("
        " (SELECT min(toDate(toTimezone(created_at,'Europe/Istanbul'))) FROM retention.money_transactions),"
        " (SELECT min(toDate(toTimezone(created_at,'Europe/Istanbul'))) FROM retention.game_transactions WHERE status='completed')"
        ")").result_rows[0][0]
    max_snap = client.query(f"SELECT max(snap_date) FROM {TABLE}").result_rows[0][0]

    eff_from = _d(args.dfrom) if args.dfrom else first_event
    if args.dto:
        eff_to = _d(args.dto)
    elif max_snap and max_snap.year > 1970:
        eff_to = max_snap - timedelta(days=1)   # НЕ трогаем день живого снапшота W3
    else:
        eff_to = client.query(
            "SELECT max(toDate(created_at)) FROM retention.game_transactions WHERE status='completed'"
        ).result_rows[0][0] - timedelta(days=1)

    if eff_from > eff_to:
        print(f"Пустой диапазон: from={eff_from} > to={eff_to}. Нечего делать.")
        return

    print(f"Диапазон бэкфилла: {eff_from} .. {eff_to}  (первое событие данных={first_event}, "
          f"max(snap_date)={max_snap})")
    print("Подготовка кумулятивов (единственный скан game_transactions)...")
    build_cum_tmp(client, eff_to)
    build_player_tmp(client)

    print("Помесячная вставка:")
    grand, secs = 0, 0.0
    for m_start, m_end, full_month in iter_months(eff_from, eff_to):
        n, dt = insert_month(client, m_start, m_end, full_month)
        grand += n
        secs += dt
    print(f"Вставлено строк: {grand} за {secs:.1f}с (только INSERT-ы)")

    run_sanity(client, eff_to)

    if not args.keep_tmp:
        client.command(f"DROP TABLE IF EXISTS {CUM_TMP}")
        client.command(f"DROP TABLE IF EXISTS {PLAYER_TMP}")
        print("\nВременные таблицы удалены.")


if __name__ == '__main__':
    main()
