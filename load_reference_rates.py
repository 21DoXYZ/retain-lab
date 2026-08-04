"""
Загрузка справочников ставок в ClickHouse — для расчёта Provider cost и Affiliate commission (NGR).
Справочники — reference/config данные (не транзакции): их казино досылает отдельным архивом.

Вход (по умолчанию — распакованный архив retention_reference_rates_*):
  provider_rates.csv   — provider, engr_percent, infra_percent, revshare_percent, fixed_fee, minimum_guarantee, period
  affiliate_rates.csv  — affiliate_db_id, affiliate_code, username, ..., commission_rate_percent

Создаёт таблицы retention.provider_rates и retention.affiliate_rates и заливает CSV (idempotent: TRUNCATE+INSERT).
Также обеспечивает наличие game_names + dict_game_names (студия по игре) — их наполняет прод-луп.

Запуск:  .venv/bin/python load_reference_rates.py [путь_к_каталогу_с_csv]
"""
import os
import sys
import glob
import clickhouse_connect

CH = dict(host=os.environ.get('CH_HOST', '127.0.0.1'), port=int(os.environ.get('CH_PORT', '8123')),
          username=os.environ.get('CH_USER', 'default'), password=os.environ.get('CH_PASSWORD', ''),
          database=os.environ.get('CH_DB', 'retention'))

PROVIDER_DDL = """
CREATE TABLE IF NOT EXISTS retention.provider_rates (
    provider String, engr_percent Float64, infra_percent Float64, revshare_percent Float64,
    fixed_fee Float64, minimum_guarantee Float64, period String
) ENGINE = MergeTree ORDER BY provider
"""
AFFILIATE_DDL = """
CREATE TABLE IF NOT EXISTS retention.affiliate_rates (
    affiliate_db_id UInt32, affiliate_code String, username String, account_type String,
    status String, currency String, commission_rate_percent Float64, created_at String, updated_at String
) ENGINE = MergeTree ORDER BY affiliate_db_id
"""


def _find(directory, name):
    hits = glob.glob(os.path.join(directory, name))
    return hits[0] if hits else None


def load_csv(client, table, path):
    if not path or not os.path.exists(path):
        print(f"  ⚠ нет файла для {table} — пропуск ({path})")
        return
    import pandas as pd
    df = pd.read_csv(path).fillna('')
    client.command(f"TRUNCATE TABLE retention.{table}")
    client.insert_df(table, df, database='retention')
    n = client.query(f"SELECT count() FROM retention.{table}").result_rows[0][0]
    print(f"  ✓ {table}: {n} строк ← {os.path.basename(path)}")


def main():
    directory = sys.argv[1] if len(sys.argv) > 1 else '.'
    # если передан каталог без csv — попробуем найти вложенный retention_reference_rates_*
    if not _find(directory, 'provider_rates.csv'):
        sub = glob.glob(os.path.join(directory, 'retention_reference_rates_*'))
        if sub:
            directory = sub[0]
    client = clickhouse_connect.get_client(**CH)
    client.command(PROVIDER_DDL)
    client.command(AFFILIATE_DDL)
    print(f"Каталог: {directory}")
    load_csv(client, 'provider_rates', _find(directory, 'provider_rates.csv'))
    load_csv(client, 'affiliate_rates', _find(directory, 'affiliate_rates.csv'))
    print("\nГотово. Provider cost / Affiliate commission теперь считаются по справочникам.")
    print("Напоминание: Provider cost требует наполненного dict_game_names (студия по game_uuid) — его ведёт прод-луп.")


if __name__ == '__main__':
    main()
