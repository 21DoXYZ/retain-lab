"""
Загрузка сегментных выгрузок (players_<segment>_<ts>.xlsx) в ClickHouse-таблицу
retention.segment_exports — журнал переданных в кол-центр списков.

Идемпотентно: (export_ts, segment) уже загруженные — пропускаются. История копится
(будущие выгрузки = новые записи). Дата/сегмент берутся из имени файла.

Запуск:  .venv/bin/python load_exports.py
"""
import os
import re
import glob
import clickhouse_connect

CH = dict(host=os.environ.get('CH_HOST', '127.0.0.1'), port=int(os.environ.get('CH_PORT', '8123')),
          username=os.environ.get('CH_USER', 'default'), password=os.environ.get('CH_PASSWORD', ''),
          database=os.environ.get('CH_DB', 'retention'))

DDL = """
CREATE TABLE IF NOT EXISTS retention.segment_exports (
    export_ts        DateTime,
    segment          LowCardinality(String),
    casino_player_id UInt32,
    dep_count_at     UInt32,
    dep_sum_at       Float64,
    bonus_sum_at     Float64,
    rec_action       String,
    rec_bonus        String,
    is_demo          UInt8 DEFAULT 0,
    loaded_at        DateTime DEFAULT now()
) ENGINE = MergeTree ORDER BY (export_ts, segment, casino_player_id)
"""

# имя вида: players_<segment>_YYYY-MM-DD HH_MM_SS[.ffffff][+03_00].xlsx — время локальное (Стамбул)
FN_RE = re.compile(r'players_(.+?)_(\d{4}-\d{2}-\d{2})[ _](\d{2})[_:](\d{2})[_:](\d{2})'
                   r'(?:\.\d+)?(?:\+(\d{2})[_:](\d{2}))?')


def load_file(client, path, *, export_ts=None, segment=None, is_demo=0):
    import pandas as pd
    from datetime import datetime, timezone, timedelta
    base = os.path.basename(path)
    if export_ts is None or segment is None:
        m = FN_RE.search(base)
        if m is None:   # имя файла не по маске players_<seg>_<ts> — пропускаем, не роняем весь батч
            print(f"  ⚠ пропуск (имя не по маске): {base}")
            return
        segment = segment or m.group(1)
        if export_ts is None:
            off = timedelta(hours=int(m.group(6) or 3), minutes=int(m.group(7) or 0))  # из имени; дефолт +03 (Стамбул)
            export_ts = datetime.strptime(f"{m.group(2)} {m.group(3)}:{m.group(4)}:{m.group(5)}",
                                          '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(off))
    if isinstance(export_ts, str):  # демо/ручной вызов: строка = стамбульское время
        export_ts = datetime.strptime(export_ts, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=3)))

    epoch = int(export_ts.timestamp())
    exists = client.query(
        "SELECT count() FROM retention.segment_exports WHERE toUnixTimestamp(export_ts)=%(t)s AND segment=%(s)s",
        parameters={'t': epoch, 's': segment}).result_rows[0][0]
    if exists:
        print(f"  · пропуск {segment} @ {export_ts} (уже загружено: {exists})")
        return

    df = pd.read_excel(path)
    n = len(df)
    out = pd.DataFrame({
        'export_ts': pd.to_datetime([export_ts] * n),
        'segment': [segment] * n,
        'casino_player_id': df['casino_player_id'].astype('uint32'),
        'dep_count_at': df.get('деп_кол-во', 0).fillna(0).astype('uint32'),
        'dep_sum_at': df.get('деп_сумма', 0).fillna(0).astype('float64'),
        'bonus_sum_at': df.get('бонус_сумма', 0).fillna(0).astype('float64'),
        'rec_action': df.get('реком_действие', '').fillna('').astype(str),
        'rec_bonus': df.get('реком_бонус', '').fillna('').astype(str),
        'is_demo': [is_demo] * n,
    })
    client.insert_df('segment_exports', out)
    print(f"  ✓ {segment} @ {export_ts}: {n} игроков" + (" [ДЕМО]" if is_demo else ""))


def main():
    client = clickhouse_connect.get_client(**CH)
    client.command(DDL)
    files = sorted(glob.glob('players_*_2026-*.xlsx'))
    print(f"Файлов выгрузок найдено: {len(files)}")
    for path in files:
        load_file(client, path)

    tot = client.query("SELECT segment, toString(export_ts), count() FROM retention.segment_exports "
                       "GROUP BY segment, export_ts ORDER BY export_ts, segment").result_rows
    print("\nВ журнале segment_exports:")
    for seg, ts, n in tot:
        print(f"  {ts}  {seg:16s} {n}")


if __name__ == '__main__':
    main()
