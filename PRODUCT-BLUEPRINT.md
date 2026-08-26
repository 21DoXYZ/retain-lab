# Retivo Commerce OS - блюпринт склейки (2026-08-27)

Рабочее название комплексного продукта: SimbaGo-стек (Commerce Runtime) +
Revenue Autopilot (Retention Brain), соединённые уже построенным швом
(ra_events outbox + export API + ra.js + connect-links + mp_order).
Полная версия с инвентарём и фазами - артефакт «Retivo Commerce OS»
(claude.ai/code/artifact/ea52da99-1dec-49b5-b5e1-d63e3f8746dc);
рынок и работы - артефакт «Карта работ мерчанта».

## Архитектура

- Кодовые базы НЕ сливаются. Runtime - инстанс на мерчанта (однотенантный,
  как SimbaGo сейчас), Brain - общий мультитенантный SaaS (этот репо).
- Движок потребления carestatus уже перенесён сюда (Replenishment core).
- WhatsApp: мульти-инстанс WAHA готов, инбокс Runtime и Brain со временем
  сливаются; у SimbaGo три параллельные ленты общения (WaMessage /
  crm.Interaction / SupportTicket) - объединять при переносе.

## Фазы

- Ф0: SimbaGo - эталонный мерчант (капча QR в чеке + события + реордер).
- Ф1 (клин, без нашего магазина): QR-вкладыши + единый WhatsApp-инбокс +
  Replenishment Autopilot; ICP - бренды расходников на Shopee/TikTok.
- Ф2: свой канал - лёгкий чекаут (COD+Xendit+пин) + заказ из чата
  (достроить order-tool в chat).
- Ф3: полный Commerce OS - WMS/PIM/AI-карточки/синк площадок managed.

## Критические долги перед внешним мерчантом (из инвентаря кода)

1. deliveries: вебхук курьера БЕЗ подписи (любой запрос меняет статусы).
2. deliveries/gosend.py - заглушка с фейковыми booking_id в проде.
3. payments: ноль тестов на идемпотентность вебхука оплаты.
4. marketplace: OAuth-callback не смонтирован - магазин нечем авторизовать.
5. warehouse: FIFO заявлен, не реализован; финансовый контур без тестов.
6. notifications: FCM/Resend-заглушки ставят SENT (ложная доставка).

## Решения за владельцем

имя/бренд; кандидат Ф1-пилота; модель денег (подписка + % с
реордер-выручки против per-order); добро на форк Runtime-репо.
