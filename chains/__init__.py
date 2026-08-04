"""chains — исполнитель цепочек автоматизации (chain-runner).

Отдельный poll-сервис (по образцу signals/rt_trigger.py): читает активные
цепочки из Postgres automation.* (миграция 0014), заводит игроков в прогон,
продвигает по узлам definition и пишет факты исполнения в ClickHouse
retention.chain_events / retention.send_log (DDL — marts.sql).

Состав пакета:
  • runner.py  — главный цикл (~5с): вход в цепочки, продвижение узлов;
  • store.py   — лёгкий psycopg-слой к automation.* для runner-а (НЕ Flask);
  • checks.py  — чистые проверки перед отправкой (consent/канал/сессия/fatigue…);
  • senders.py — каналы MVP (casino_webhook / bonus_grant / email / telegram).

fail-closed: пока PREDICTIONS_ENABLED в .env не «1/true», сервис не отправляет и
не продвигает — как rt_trigger (авария = молчание, а не рассылка).
"""
