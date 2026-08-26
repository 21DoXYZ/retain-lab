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

ЗАКРЫТЫ 2026-08-27 (upstream main bf04451..cbc5c9d): подпись вебхука
курьера (fail-closed), фейковые GoSend-брони за флагом (деф. выкл),
34 теста payments, честные статусы уведомлений + живые Resend/FCM
(FCM ждёт google-auth в requirements), OAuth connect+callback
Shopee/TikTok/Tokopedia с подписанным state.

ОСТАЛОСЬ:
1. warehouse: FIFO заявлен, не реализован; финансовый контур без тестов.
2. Три ленты общения (WaMessage/Interaction/SupportTicket) не слиты.
3. WhatsApp-stub без Twilio тоже ставит SENT (мелочь, той же правкой).

## Решения за владельцем

имя/бренд; модель денег (подписка + % с реордер-выручки против per-order);
добро на форк Runtime-репо.
РЕШЕНО 2026-08-27: Ф1-пилот = сам SimbaGo (внешний мерчант - после
доказанного uplift, цифры SimbaGo как кейс).
