# Call Analyzer — Developer Spec (build-ready) v1.1

Единый документ для разработки. Только анализатор звонков. Самодостаточен: содержит дефолты, интерфейсы, готовую рубрику, схемы, промпты, правила подсчёта, приёмку. Без рыночных обоснований — только что и как строить.

**Что строим.** Post-call batch-пайплайн: приём исходящего retention-звонка (оператор↔игрок, турецкий) → ASR → диаризация → PII-редакция → LLM-скоринг по рубрике → хранение → выдача (оценка, коуч-карточка, отчёт, сигнал в retention-модель) → human override.

---

## 1. Стек и дефолты

| Слой | Дефолт (кодим против него) | Swappable на | Примечание |
|---|---|---|---|
| Ingest API | Python + FastAPI | — | webhook, валидация, постановка в очередь |
| Очередь/воркеры | Celery + Redis | Kafka-консьюмеры на масштабе | партиция по `call_id` |
| ASR (TR) | **Gladia Solaria** (диаризация встроена, all-inclusive) | ElevenLabs Scribe / Deepgram | за адаптером §6.1; выбор финализируется тестом на реальном аудио |
| VAD/тишина | Silero VAD | — | отсечь hold/IVR/паузы |
| Диаризация (моно) | pyannote.audio 3.1 | — | только если каналов=1 и conf провайдера < порога |
| PII | Microsoft Presidio + regex | — | турецкие паттерны §11 |
| LLM primary | **Claude Sonnet 5** (JSON mode, кэш рубрики) | — | скоринг |
| LLM fallback | **Gemini 3 Flash** (другой вендор) | — | при invalid JSON от primary |
| Операционка | Postgres | — | §4 |
| Аналитика/транскрипты | ClickHouse на серверах клиента | — | §4.2 |
| Портал | Next.js/TypeScript | — | дашборд/карточка |
| Config | Config service (Postgres-таблица + hot-reload) | — | §12 |

Аудио на входе: wav/mp3/opus; нормализовать в 16 kHz PCM; предпочтительно 2 канала (оператор/игрок раздельно).

---

## 2. Конвейер (шаги)

Асинхронно, идемпотентно по `call_id` (повтор перезаписывает по `prompt_version`+`model_used`).

| # | Шаг | Действие | Дефолт-инструмент |
|---|---|---|---|
| 0 | Ingest | валидировать, создать `calls`, в очередь | FastAPI |
| 1 | Audio QC | нормализация; SNR; VAD (тишина/hold) | librosa + Silero |
| 2 | ASR | турецкий STT + word timestamps | Gladia адаптер |
| 3 | Диаризация | роли AGENT/PLAYER (§6.3) | каналы / pyannote |
| 4 | Redact | удалить PII, сохранить `text_redacted` | Presidio + regex |
| 5 | Score | LLM по рубрике → JSON (§10, §8) | Claude Sonnet 5 |
| 6 | Validate | schema-check; вычислить `overall_score_100`, `pass_fail` (§9) | код |
| 7 | Signal | экстракция оффер-сигнала (§10.5) | LLM |
| 8 | Deliver | коуч-карточка (§10.6); запись в ClickHouse | LLM + CH |

Шаг 2 идёт, только если шаг 1 не увёл звонок в `manual_review` (низкий SNR).

---

## 3. Машина состояний

Поле `calls.status`, enum `call_status`:
`received | audio_checked | manual_review | transcribed | diarized | redacted | scored | needs_review | completed | asr_failed | llm_failed | error`

Переходы:
```
received → audio_checked → transcribed → diarized → redacted → scored → completed
audio_checked → manual_review            (SNR < snr_min)
manual_review → transcribed              (после ручной проверки аудио)
scored → needs_review                    (audit.needs_human=true)
needs_review → completed                 (после override)
* → asr_failed | llm_failed | error      (терминальные после ретраев)
```

---

## 4. Модель данных

### 4.1 Postgres (операционка)

**calls**: `call_id uuid PK`, `casino_id uuid`, `operator_id uuid`, `player_id text`, `source text`, `channels int`, `audio_uri text`, `started_at timestamptz`, `ended_at timestamptz`, `duration_s int`, `snr float`, `status call_status`, `recommended_offer_id text null`, `created_at`, `updated_at`.

**transcripts**: `transcript_id uuid PK`, `call_id uuid FK`, `asr_provider text`, `language text`, `text_redacted text`, `words jsonb`, `diarization_conf float`, `created_at`.
`words` = `[{"w":str,"start":float,"end":float,"role":"AGENT|PLAYER","conf":float}]`.

**call_audits**: `audit_id uuid PK`, `call_id uuid FK`, `prompt_version text`, `model_used text`, `overall_score_100 int`, `pass_fail text`, `dimensions jsonb`, `objections jsonb`, `offer_outcome text`, `coaching_narrative text`, `highlights jsonb`, `improvement_areas jsonb`, `needs_human bool`, `llm_tokens int`, `llm_cost_usd numeric`, `processing_ms int`, `human_reviewed bool`, `human_override_score int null`, `human_reviewer_id uuid null`, `human_notes text null`, `created_at`.
`dimensions` = `[{"name":str,"score":int,"justification":str,"evidence_ts":[str],"needs_human":bool}]`.

**offer_signals**: `signal_id uuid PK`, `call_id uuid FK`, `player_id text`, `recommended_offer_id text`, `offer_presented bool`, `player_response text`, `alt_offer_worked bool null`, `refusal_reason text null`, `callback_scheduled timestamptz null`, `created_at`.

**coaching_cards**: `card_id uuid PK`, `call_id uuid FK`, `operator_id uuid`, `tips jsonb`, `created_at`, `delivered_at null`.

**access_log** (иммутабельно): `id`, `actor_id`, `call_id`, `action text`, `at`. action ∈ `view_audio|view_transcript|override`.

### 4.2 ClickHouse (клиент, аналитика)

`call_audits_flat` — append-only, `ENGINE=MergeTree ORDER BY (operator_id, created_at) PARTITION BY toYYYYMM(created_at)`. Поля: `call_id`, `operator_id`, `casino_id`, `created_at`, `duration_s`, `overall_score_100`, `pass_fail`, `score_open_identify … score_tone` (по каждому критерию), `offer_outcome`, `top_objection`, `audit_json`.

---

## 5. API (`/v1`)

Auth: сервис-токен (ingest), JWT (портал).

**POST /calls/ingest**
```
req {call_id?, casino_id, operator_id, player_id, source:"taksoft",
     channels:1|2, audio_uri, started_at, ended_at, duration_s, recommended_offer_id?}
202 {call_id, status:"received"}   |   400 {error, detail}
```
**GET /calls/{call_id}/audit** → `200 {call_id, status, audit|null}` | `404`.
**POST /calls/{call_id}/override** `req {overall_score_100, notes, reviewer_id}` → `200 {call_id, human_reviewed:true}`.
**GET /operators/{operator_id}/report?from&to** → `{operator_id, period, calls_total, calls_connected, avg_score, rubric_adherence_pct, top_objection, trend[]}`.
**GET /team/report?casino_id&from&to** → агрегаты по операторам.
**GET /calls/{call_id}/transcript?lang=tr|ru|en** — `lang≠tr` триггерит перевод on-demand.
**POST /config/rubric** (admin) → `{rubric_version}`.
Webhook out **audit_completed** → `{call_id, overall_score_100, pass_fail, needs_human}`.

---

## 6. Интерфейсы адаптеров

### 6.1 ASR
```python
class ASRProvider(Protocol):
    def transcribe(self, audio_path: str, language: str = "tr",
                   channels: int = 1) -> ASRResult: ...

# ASRResult:
# { "words": [{"w","start","end","channel"|None,"speaker"|None,"conf"}],
#   "provider": str }
```
Дефолт `GladiaAdapter`. Альт: `ScribeAdapter`, `DeepgramAdapter`. Выбор — по env `ASR_PROVIDER`.

### 6.2 LLM
```python
class LLMProvider(Protocol):
    def complete_json(self, system: str, user: str,
                      temperature: float = 0.1) -> dict: ...
    # returns parsed JSON; raises on non-JSON
```
Дефолт primary `ClaudeSonnet5Adapter`, fallback `GeminiFlashAdapter`. Кэшировать статичный system+rubric (prompt caching).

### 6.3 Диаризация — логика роли
```
if channels == 2:
    role = "AGENT" if channel == operator_channel else "PLAYER"   # канал = роль
else:
    take provider speaker labels
    if provider speaker_conf < diar_conf_min:
        run pyannote → use pyannote segments (vote: pyannote wins on low provider conf)
    map speaker→role: спикер, говорящий первым в первые 30 сек = AGENT
        (исходящий звонок инициирует оператор)
    set transcripts.diarization_conf = min observed conf
```

---

## 7. Обработка ошибок и ретраи

| Сбой | Поведение |
|---|---|
| Битый webhook | 400, звонок не создавать |
| SNR < `snr_min` | `manual_review`, флаг, без ASR |
| ASR fail | ретрай 3x (exp 2→10s) → `asr_failed`, алерт |
| diar conf низкий | продолжить, пометить аудит флагом `low_diar_conf` |
| Redact fail | НЕ хранить транскрипт, алерт (сырое не персистить) |
| LLM invalid JSON | ретрай 3x → fallback-модель + «return valid JSON only» → `llm_failed` |
| tokens > 6000 | компрессия §10.8 перед скорингом |
| диаризация «плывёт» (длинные) | пост-звонковый re-diarization пасс + сверка |

Сбой одного звонка не роняет очередь; звонок помечается и уходит в human-очередь.

---

## 8. JSON-схема вывода скоринга

LLM возвращает строго это (совпадает с `call_audits`; `overall_score_100`/`pass_fail` считает код, не LLM):
```json
{
  "prompt_version": "string",
  "model_used": "string",
  "dimensions": [
    {"name":"open_identify|rapport|discovery|offer_presented|offer_value|objection_handling|alt_offer|next_step|tone",
     "score": 1, "justification":"string", "evidence_ts":["mm:ss-mm:ss"], "needs_human": false}
  ],
  "objections": [{"type":"no_money|no_time|lost_before|distrust|other","handled":true,"reason":"string"}],
  "offer_outcome": "accepted|refused|countered|no_offer|unclear",
  "needs_human": false,
  "coaching_narrative": "string",
  "highlights": ["string"],
  "improvement_areas": ["string"]
}
```
Валидация: strip ```-fences → `json.loads` → assert ровно 9 dimensions с валидными `name` → каждый `score ∈ 1..5` → `offer_outcome`/`objections[].type` в enum. При провале — ретрай/fallback (§7).

---

## 9. Подсчёт `overall_score_100` и `pass_fail`

Веса критериев (сумма 100):
```
open_identify 5, rapport 10, discovery 15, offer_presented 15, offer_value 15,
objection_handling 20, alt_offer 5, next_step 10, tone 5
```

**Правило needs_human (закрывает дыру):**
```
included = [d for d in dimensions if not d.needs_human]
W = сумма весов included
overall_score_100 = round( Σ_included (d.score/5 * weight_d) / W * 100 )
# критерии с needs_human=true исключаются из суммы, веса ренормируются на 100

audit.needs_human = any(d.needs_human) OR llm.needs_human
```
Если included пуст (все needs_human) → `overall_score_100 = null`, `pass_fail = NEEDS_REVIEW`.

**pass_fail:**
```
NEEDS_REVIEW  если audit.needs_human == true
PASS          иначе если overall_score_100 >= 70
NEEDS_REVIEW  иначе если 50 <= overall_score_100 < 70
FAIL          иначе (< 50)
```

---

## 10. Промпты

`temperature=0.1`, JSON-only, вход — турецкий транскрипт, reasoning на `{output_lang}` (ru/en). Статичный system+rubric кэшируются.

### 10.1 System
```
You are an expert QA auditor for an iGaming RETENTION call center.
Input: a diarized Turkish transcript of an OUTBOUND call where an OPERATOR
calls a lapsing PLAYER to bring them back with a recommended bonus offer.
Score the OPERATOR against the rubric. Judge ONLY what the transcript supports.
Do NOT infer intent. Cite exact timestamps as evidence. Be fair and specific.
For a subjective dimension, if your confidence < 0.7, set that dimension's needs_human=true.
Return ONLY valid JSON per the schema. No preamble, no markdown fences.
Write all reasoning fields in {output_lang}.
```

### 10.2 User template
```
## Call
call_id: {call_id} | duration_s: {duration_s} | operator_id: {operator_id}
recommended_offer_id: {recommended_offer_id_or_"NONE"}

## Transcript (diarized, Turkish; lines "[mm:ss] AGENT: ..." / "[mm:ss] PLAYER: ...")
{transcript_lines}

## Rubric
{rubric_block}     // §10.3

## Return JSON per schema (§8). All 9 dimensions required.
```

### 10.3 Rubric v1 (`rubric_version="v1"`, хардкод-дефолт, потом из Config)
```
Score each dimension 1-5 (1=poor, 3=meets standard, 5=exceptional).
- open_identify: greeted, named the brand, friendly opener
- rapport: built contact, addressed the player by name
- discovery: asked >=1 question about inactivity reason / player need
- offer_presented: stated the recommended offer.
    If recommended_offer_id == NONE, score=3 and needs_human=true (cannot verify)
- offer_value: explained the offer's value, not just "there is a bonus"
- objection_handling: addressed the player's objection (no money / no time / lost before)
- alt_offer: if the offer was refused, proposed an alternative
- next_step: fixed a concrete next step / callback date
- tone (subjective): not pushy, did not interrupt. needs_human=true if confidence<0.7
```

### 10.4 Слой надёжности
```
temperature=0.1; response_format=json_object (или строгий JSON-парс)
retry 3x exp(2→10s); on invalid → fallback model + "return valid JSON only"
store prompt_version + model_used with result
```

### 10.5 Экстракция сигнала оффера (шаг 7)
```
From transcript + operator note (if any) output ONLY:
{player_id, recommended_offer_id, offer_presented:bool,
 player_response:"accepted|refused|countered|deferred",
 alt_offer_worked:bool|null,
 refusal_reason:"no_money|no_time|distrust|competitor|other"|null,
 callback_scheduled:"ISO-8601"|null}
Only fields grounded in the transcript. No guessing.
```

### 10.6 Коуч-карточка (шаг 8)
```
Given the audit JSON, write 2-3 specific tips in {output_lang}.
Reference exact timestamps ("skipped the offer at 01:12"). Concrete, not generic.
Encouraging tone. Max 60 words. Return {"tips":[{"ts":"mm:ss","text":"..."}]}.
```

### 10.7 Агрегат возражений (отчёт)
```
From scored calls in period, find the objection type most often preceding
offer_outcome=refused; find the operator with highest handled-rate for it;
extract their talk-track. Return {top_objection, refusal_rate_pct,
best_operator_id, talk_track (in {output_lang})}.
```

### 10.8 Компрессия длинного транскрипта (если tokens>6000)
```
Keep verbatim: first/last 5 turns + turns flagged (objection/offer moment).
Summarize the middle with the fallback (cheap) model. Else pass through.
```

---

## 11. PII, безопасность

Redact до хранения (Presidio NER `PERSON, LOCATION` + regex):
```
phone: \b(?:0?5\d{9}|\+90\d{10}|0\d{10})\b        → [PHONE]
card:  \b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b  → [CARD]
tc_kimlik: \b\d{11}\b                              → [TC]
email: стандартный                                 → [EMAIL]
```
Хранить только `text_redacted`. Транскрипты/аудиты — в ClickHouse клиента; сырое аудио пайплайн не персистит. `player_id` — связка без контактов. RBAC (§ниже) + `access_log`. TLS 1.3; at-rest шифрование; секреты в vault. ASR-вендор — только zero-retention DPA. Видеозапись звонков запрещена.

RBAC: Operator (свои звонки), Head CC/WA (свои операторы + override), Head Retention (всё казино + override), QA (всё + аудио + override), Super admin (конфиг + всё).

---

## 12. Config service (схема)

Таблица `config` (hot-reload, версионируется):
```
{ rubric_version: "v1",
  rubric_block: "<текст §10.3>",
  weights: {open_identify:5, rapport:10, discovery:15, offer_presented:15,
            offer_value:15, objection_handling:20, alt_offer:5, next_step:10, tone:5},
  snr_min: <float, калибруется>,
  diar_conf_min: <float>,
  primary_model: "claude-sonnet-5",
  fallback_model: "gemini-3-flash",
  asr_provider: "gladia",
  output_lang: "ru",
  pass_threshold: 70, review_low: 50 }
```
Смена `rubric_version` не меняет старые аудиты (в них хранится своя версия).

---

## 13. Eval / калибровка (условие релиза)

1. Golden set: 100–500 турецких звонков, размечены человеком по рубрике v1.
2. Релиз только если: средняя дельта по dimension < 0.3 vs человек И точность `pass_fail` > 92%.
3. Adversarial-набор («звучит хорошо, но плохо» и наоборот).
4. Cross-model: логировать расхождения primary vs fallback > 1 балла → в golden set.
5. Регресс golden set на каждой смене промпта/модели; блокировать релиз при регрессе.
6. Human override rate > 15% = сигнал проблемы рубрики/промпта.

---

## 14. Тесты кода (отдельно от eval)

- **Unit:** валидатор JSON-схемы (§8); подсчёт `overall_score_100` включая needs_human-ренормализацию (§9); PII-regex (§11); маппинг роли (§6.3); переходы state machine (§3, запрещённые переходы падают).
- **Integration:** ingest→очередь→воркеры на замоканных ASR/LLM (детерминированные ответы); идемпотентность (повтор call_id перезаписывает); путь ошибок (ASR fail → `asr_failed`, LLM invalid → fallback → при повторном провале `llm_failed`).
- **Contract:** адаптеры ASR/LLM против фикстур (§6).
- **Load (перед масштабом):** глубина очереди и лаг при целевом RPS.

---

## 15. Наблюдаемость

AI-health (ночью на human-reviewed сэмпле): дрейф среднего балла 7д > 0.2; % битого JSON > 0.5%; diar error > 5%; cross-model расхождение > 20%; override rate > 15%.
Инфра: глубина очереди, лаг воркеров, latency ASR/LLM p95/p99, стоимость/звонок.
Алерты: P1 (пайплайн стоит) → пейджер; P2 (дрейф/аудио) → чат; P3 (сдвиги распределения) → недельный дайджест.

---

## 16. NFR

Латентность p95 < 5 мин (конец звонка → оценка). Пропускная: пилот ~300/день, масштаб до ~8000/день без переписывания. Стоимость ≤ $0.06/звонок. Доступность 99% (пилот). Идемпотентность по call_id. Горизонтальное масштабирование воркеров.

---

## 17. Definition of Done

1. Пайплайн end-to-end: звонок → оценка за p95 < 5 мин, ≤ $0.06.
2. Пройдена калибровка §13 (дельта <0.3, pass_fail >92%) на golden set.
3. PII-редакция подтверждена на 50 звонках (в хранилище нет сырых номеров/имён).
4. Все сбои (§7) уводят звонок в верный статус, очередь не падает.
5. Override работает, событие идёт в eval-данные.
6. Unit/integration-тесты (§14) зелёные в CI.
7. AI-health метрики и алерты (§15) активны.
8. Каждый аудит хранит `prompt_version` + `model_used`.

---

## 18. Порядок разработки

**Спринт 1:** миграции БД (§4); Config service + рубрика v1 (§12); ingest API + очередь; Audio QC (SNR/VAD); заглушка дашборда на sample-данных.
**Спринт 2:** ASR-адаптер (Gladia) + тест на реальном турецком аудио; диаризация (§6.3); PII-редакция; скоринг (§10) + валидация + подсчёт (§9); запись Postgres/ClickHouse.
**Спринт 3:** golden set + калибровка (§13); коуч-карточки; отчёты оператора/команды; override; сигнал оффера в retention-модель.
**Позже:** агрегат возражений; fine-tuned модель на объёме; real-time — отдельный трек.

---

## 19. Внешние зависимости (закрыть в начале Спринта 2)

1. Taksoft: 2 канала? формат/кодек аудио? webhook или файлы в бакет?
2. Реальный скрипт казино → финализировать рубрику v1.
3. Тест ASR на аудио клиента → подтвердить/сменить дефолт (Gladia).
4. LLM: облако vs self-host (Qwen), если редактированный транскрипт не должен покидать периметр.
5. Где и на какой срок хранится аудио (сторона клиента).

---

## 20. Honesty rails

Call Analyzer — LLM-слой, отдельный от classical-ML retention-ядра. Публично без «96–98% точности» → «пилотная цель на данных клиента». Неуверенные оценки — «неточный расчёт», не «галлюцинация». PII редактируется до хранения; транскрипты на ClickHouse клиента. Видеозаписи нет. Compliance (детерминированный) и quality (LLM) не смешивать.
