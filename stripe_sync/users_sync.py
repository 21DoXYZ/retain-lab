"""Постоянная синхронизация базы юзеров клиента из его источника.

Разовая загрузка CSV закрывает историю, но не будущее. Этот джоб раз в час
забирает список юзеров оттуда, где он живёт (провайдер авторизации или
админский API продукта), и доливает недостающих. Клиенту не нужно ничего
дописывать в код - только один раз дать ключ на чтение.

Идемпотентно: event_id детерминирован по (пространство, юзер), повтор не
плодит дубли. Ошибка источника не валит прогон - пишем причину и уходим.

Запуск: TENANT_ID=<пространство> python users_sync.py
"""

from __future__ import annotations

import os


def main() -> None:
    import clickhouse_connect

    tenant = os.environ.get("TENANT_ID", "").strip()
    if not tenant:
        raise SystemExit("нужен TENANT_ID: джоб работает в пространстве клиента")

    from connectors import fetch_users
    from saas_senders import load_tenant_channels
    from users_import import COLUMNS, to_events

    source = (load_tenant_channels(tenant) or {}).get("users_source") or {}
    if not source.get("kind"):
        print(f"[users_sync] tenant={tenant} источник не подключён - пропуск", flush=True)
        return

    try:
        users = fetch_users(source)
    except Exception as exc:  # noqa: BLE001 - чужой сервис не должен ронять цикл
        print(f"[users_sync] tenant={tenant} источник недоступен: "
              f"{type(exc).__name__}: {exc}", flush=True)
        return

    rows, report = to_events(users, tenant)
    if not rows:
        print(f"[users_sync] tenant={tenant} новых юзеров нет ({report})", flush=True)
        return

    client = clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"),
    )
    client.insert("retention.saas_events", rows, column_names=COLUMNS)
    print(f"[users_sync] tenant={tenant} источник={source['kind']} {report}", flush=True)


if __name__ == "__main__":
    main()
