# Tegsoft REST API — конспект для интеграции звонилки

> Источник: https://apidocs.tegsoft.com (изучено 15.07.2026, сырой дамп: `tegsoft_docs_raw.txt`).
> В ТЗ колл-центра звонилка названа «Techsoft» — это опечатка, правильно **Tegsoft** (турецкий contact-center suite).

## Общий формат API
- База: `https://<server>.tegsoftcloud.com/Tobe/view/<Servlet>?service=...&method=...&param=...`
- JSON REST, в основном GET (есть POST для токена/загрузок). Сессионная авторизация.

## 1. Авторизация (Login Services)
| Endpoint | Что делает |
|---|---|
| `POST Generate token and crypt password` | получить токен / зашифрованный пароль |
| `GET /Tobe/view/Login?service=performLogin&locale=en` | логин по usercode+password **или** по токену |
| `GET /Tobe/view/Login?fileName=login&service=checkLoginStatus` | проверка живости сессии |
| `GET Logging-out an active user` | logout |

→ Наш адаптер держит **сервисную учётку** + сессию, рефрешит по checkLoginStatus.

## 2. Звонки (Contact Center + PBX)
| Endpoint | Что делает |
|---|---|
| `Create a Call` (ContactCenterServices) | звонок из интерфейса агента |
| `GET originateWithProfile` / `originateWithVariables` (PBX) | **click-to-call**: соединить агента и номер |
| `bridgeWithAnnouncement` | мост с проигрыванием объявления |
| Answer / Transfer / Hold / Mute / Hangup (voice+webchat) | управление активным звонком |
| `ServicesGateway?service=ContactCenterServices&method=agentLogout&USERCODE=...` | пример формата вызова |

## 3. Записи звонков — ЕСТЬ ✅ (Recording Services)
| Endpoint | Что делает |
|---|---|
| `GET Get Related Audio File Names` | имена аудиофайлов по звонку/контакту |
| `GET Download Audio File` | скачать запись |
| `GET Stream Audio File` | **стримить запись** (плеер в карточке!) |
| `GET Download Audio File Analysis Image` | картинка анализа аудио |
| `POST Upload Screen Recording` / `GET Download Screen-recording file` | скрин-записи агента |

→ В нашу таблицу `crm.calls` добавляем `recording_ref` (имя/ид файла) — плеер тянет через adapter (Stream).
→ Это же фундамент будущего «Анализатора звонков» (фаза 2 ТЗ): записи доступны по API.

### 3a. Двухканальность записи — ДА, поддерживается (нужно подтвердить формат файла)
В настройках extension (дамп доков) у каждого внутреннего номера **пишутся обе стороны разговора отдельно**:
- `RECORDIN: "Always"` — входящее плечо (голос **клиента** → агенту);
- `RECORDOUT: "Always"` — исходящее плечо (голос **агента** → клиенту).

Раз обе стороны фиксируются раздельно — платформа **двухканальная (dual-channel) по своей природе**. Косвенное подтверждение: есть метод `Recordings?service=downloadSpeechAnalysisImage` (картинка речевого анализа), а разделение «кто говорил» возможно только при раздельных каналах.

**Что уточнить на боевом инстансе (открытый вопрос ниже):** отдаёт ли API готовый **стерео-файл (2 канала: агент/клиент)** или **уже сведённый моно-микс**. Для текущего CRM (просто прослушать звонок в карточке) хватает моно. Для «Анализатора звонков» (фаза 2, распознавание «кто что сказал») нужен **стерео** — попросить клиента выставить профиль записи в двухканальный/стерео.

### Подтверждённый из доков синтаксис (снимает часть «UNVERIFIED»)
- **Originate (click-to-call):** `GET /Tobe/view/ServicesGateway?service=RemotePBX&method=<originate|bridgeWithAnnouncement>&extension=<ext_агента>&destination=<номер_клиента>&profile=<CONTEXTID>&variables=__STARTREC=true`
  - `service=RemotePBX` — подтверждено. `__STARTREC=true` (включить запись) — подтверждено дословно.
  - Сначала звоним агенту (`extension`), после ответа — клиенту (`destination`). Ответ: `errorOccurred=false`, `CALLID/UNIQUEID`.
  - «Originate Call» берёт `extension+destination`; `bridgeWithAnnouncement` — то же + `profile+variables` (объявления опциональны). Точное строковое имя простого originate в публичном дампе показано частично → держим в env `TEGSOFT_ORIGINATE_METHOD`.
- **Запись:** `Recordings?service=streamAudioFile&CALLID={CALLID}` (стрим, подтверждено), `getRelatedAudioFileNames` (список файлов), `downloadSpeechAnalysisImage` (анализ).
- **Авторизация:** `Login?service=performLogin` (usercode+password) **или** Bearer-токен; живость — `checkLoginStatus`.

## Как это ложится на наш код (что уже сделано)
- `tegsoft/adapter.py` — `TegsoftProvider` (боевой) + `MockProvider` (dev/CI); переключение по env `CALL_PROVIDER`, секреты только на сервере.
- `api/calls.py` — `POST /calls/originate` (IDOR-гейт), `POST /webhooks/tegsoft` (shared-secret), `GET /calls/<id>/recording` (стрим, роли risk/главы/director).
- `tegsoft/store.py` — запись/апдейт в `crm.calls` по `provider_ref`; **корреляция webhook↔игрок через `audit_log` (store.lookup_originate)** — Tegsoft-ECR присылает только CALLID+исход+длительность, а игрока/оператора берём из записи `call_originate`, сделанной при старте звонка.
- `tegsoft/test_adapter.py` — полный цикл на Mock зелёный (originate → запись → webhook → crm.calls).

## Go-Live чеклист (чтобы «осталось вставить ключ»)
**Мы (готово в коде):** адаптер, приёмник webhook, стрим записи, корреляция, маскирование номера, роли, аудит. Осталось заполнить `tegsoft/.env.tegsoft.example` → в `.env`.
**Клиент должен дать/настроить:**
1. URL инстанса (`<server>.tegsoftcloud.com`) + сервисную учётку с правом **Webservice access** (или Bearer-токен).
2. `CONTEXTID` исходящего профиля (для originate с записью).
3. В **ECR Definitions** прописать наш webhook-URL `https://<наш-домен>/api/v1/webhooks/tegsoft` + заголовок `X-Tegsoft-Secret` = наш `TEGSOFT_WEBHOOK_SECRET`; включить события старт/конец звонка.
4. Подтвердить: запись звонков **включена** на их тарифе; **формат** (стерео vs моно) и срок хранения.
5. Карта «оператор → extension» (через `app_metadata.tegsoft_ext` в JWT или `TEGSOFT_EXT_MAP`).
После этого: `CALL_PROVIDER=tegsoft`, один тестовый звонок → сверить `CALLID` в ответе и приход webhook в `crm.calls`; снять оставшиеся метки `UNVERIFIED` (точное имя метода originate, форма ответа списка записей).

## 4. Реалтайм-статусы (Dashboard Services)
`RealTimeActivityData`, статусы agents / campaigns / skills / trunks / webchats, `Extension Status`, `Presence` — можно показывать «оператор на линии» и контролировать дисциплину.

## 5. Доступ к данным (Data and Functional Services)
- `POST Insert Data into a Database Table` + чтение таблиц Tegsoft.
- Таблицы, замеченные в доках: `TBLCRMCONTACTS` (контакты CRM), `TBLCRMCONTACTRESP`, `TBLCCAGENT` (агенты), `TBLCCAGENTLOG` (лог работы агентов), `TBLPBXEXT` (extensions), `TBLLOGINS`, `TBLCCPOPUP`, `TBLUSERDATA`.
- CDR-таблица (детальные записи звонков с длительностью) в дампе не отснята (виртуализация доков) — **добрать при получении доступа**; классически у Tegsoft это TBLCDR-семейство. Длительность/исход также можно собирать из webhook-событий.

## 6. Webhooks (ECR — External Contact Router) ✅
- На каждое событие жизненного цикла звонка можно задать **webhook URL** (настройка: ECR Definitions в Contact Center Settings).
- «All the events with enabled webhook URL definitions will generate a webhook request upon event instance» + Table Synchronization Event (живая таблица ожидающих).
- → Наш приёмник вебхуков фиксирует: старт/конец звонка, длительность, кто говорил → пишем в `crm.calls` автоматически (а не только руками оператора).

## Как это ложится на нашу схему `crm.calls`
| Наше поле | Источник в Tegsoft |
|---|---|
| `started_at`, `duration_sec` | webhook-события / CDR / RealTimeActivityData |
| `outcome` (дозвон/недозвон/занято/неверный) | событие + подтверждение оператором (2 клика) |
| `provider_ref` | ид звонка Tegsoft |
| `recording_ref` (добавить) | Get Related Audio File Names |
| прослушивание | Stream Audio File через adapter |

## ✅ Подтверждено на боевом инстансе (20.07.2026, доступ от Лолиты)

- **Инстанс — white-label «NGTX AI»**: витрина `https://app.ngtxai.com/1289878771/` (iframe-обёртка),
  боевой узел API — **`https://f81o27.ngtxai.com`** (из `config.php` кластера; failover: 2×20с таймаут).
  Под капотом обычный Tegsoft (`/Tobe/view/`, ZK, `<title>Tegsoft - Contact Center Solutions</title>`).
- **Авторизация API — Bearer-токен, stateless (ПОДТВЕРЖДЕНО живым запросом)**:
  `Authorization: Bearer <токен>` на каждый запрос; `checkLoginStatus` отвечает
  `{"success":true,"user":{...,"rowTBLLOGINS":{"STATUS":"ACTIVE",...}}}`.
  Отказ: `{"success":false,"message":"No user login detected"}`. `performLogin` в
  токен-режиме НЕ нужен и отвергается (Code:898) — параметр `?token=` в URL не работает.
  Токен берётся в ЛК: Настройки → Управление пользователями → юзер → таблица токенов.
- **Учётка `entegreapi`** активна, полноценный доступ в веб-ЛК (RU-локаль), токен рабочий.
- **Записи звонков РАБОТАЮТ**: раздел «Голосовые записи» — дата, звонящий, длительность,
  диспозиция (Ответил/Занятый/Нет ответа), агент, имя файла `20260720-1784549110.1198313`.
- **Формат номеров**: кампания — `905XXXXXXXXX` (межд.), ручной набор агента — `0XXXXXXXXXX`.
  Транки: 908504340542, 908505454313, 908505454323. ID кампании-дайлера в CDR: 859996.
- **Вебхуки**: раздел «Настройки → Управление веб-перехватчиком» (доступен нам), список ПУСТ —
  наш webhook ещё не заведён. Заводить ТОЛЬКО после деплоя прод-приёмника + секрета в .env
  (иначе события будут биться о 401).
- **Агенты (20)**: suat/sude/omer/ozgur/irem/ece/fidan/gürkan call, nairobi1-4, aff1-3,
  admin3, agent28, elif/irem nova + админы. Extensions — в карточке агента (TBLPBXEXTUID).
- **CDR есть**: `Reports?fileName=cc_cdr` + real-time (`Presence`, `RealTimeSkillsData`).

## Осталось (обновлено 20.07)
1. **Стерео/моно записи** — посмотреть RECORDIN/RECORDOUT у extension либо спросить; для
   Анализатора звонков нужен стерео.
2. **Выписать карту оператор→extension** из карточек агентов → `TEGSOFT_EXT_MAP`.
3. **Завести webhook** в «Управлении веб-перехватчиком» — после деплоя прод-приёмника.
4. **Перегенерировать токен** после настройки (текущий засветился в переписке) и положить
   свежий в `.env` (`TEGSOFT_TOKEN`). Пароль-режим не нужен.
