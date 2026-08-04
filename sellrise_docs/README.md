# Sellrise Docs — интеграционная документация

> Интеграционная документация Sellrise Retention CRM для операторов casino & sportsbook:
> приём событий (HTTP / потоковый канал), бэкфилл истории, требования к данным и доставка
> предсказаний (дашборд, callback-сигналы, витрины).

Предиктивный слой (состав моделей, метрики качества, use cases) описывается отдельно
и передаётся оператору по запросу на этапе договорённостей.

## Интеграция

- [B2B Integration Architecture](integration/b2b-integration-architecture.md) — общая схема: от событий до сигналов
- [Authentication & Access](integration/authentication-and-access.md) — токены, доступы потокового канала, роли дашборда
- [Data Requirements](integration/data-requirements.md) — какие данные нужны, критичность, расширенные данные для функций CRM
- [Real-time Event Ingestion](integration/realtime-event-ingestion.md) — контракт события v2, HTTP и потоковый канал
- [Batch Data Ingestion](integration/batch-data-ingestion.md) — бэкфилл истории и батч-каналы
- [Predictions Delivery](integration/predictions-delivery.md) — где забирать предсказания: дашборд, callback, витрины

## Статус

| Блок | Статус |
|---|---|
| Приём событий HTTP / потоковый канал | ✅ работает |
| Batch-бэкфилл истории | ✅ работает |
| Дашборд и выгрузки | ✅ работает |
| Callback-сигналы оператору | 🟡 спецификация готова, включается после согласования формата и обмена токенами |
