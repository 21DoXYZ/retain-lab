-- 0007: Call Analyzer — анализ звонков колл-центра (спеки: call_analyzer_dev_spec.md
-- §4 + call_analyzer_interface_spec_FINAL.md §12).
--
-- Схема analyzer НАМЕРЕННО не экспонируется через PostgREST (не добавлять в
-- exposed schemas!): браузер сюда не ходит. Читает Flask (api/call_analysis.py,
-- RBAC по ролям), пишет пайплайн-сервис (call_analyzer/). Транскрипты содержат
-- редактированную речь игроков — поверхность доступа держим минимальной.

CREATE SCHEMA IF NOT EXISTS analyzer;

-- Разовая проверка перевода (§10.11): временная учётка, видит ОДИН экран.
-- Значение enum добавляется вне транзакции миграции быть не может в старых PG,
-- в 15+ ADD VALUE в транзакции разрешён.
ALTER TYPE crm.user_role ADD VALUE IF NOT EXISTS 'translation_reviewer';

-- Машина состояний пайплайна (dev spec §3)
CREATE TYPE analyzer.call_status AS ENUM (
  'received','audio_checked','manual_review','transcribed','diarized',
  'redacted','scored','needs_review','completed','asr_failed','llm_failed','error');

-- ── Звонки анализатора ────────────────────────────────────────────────────────
-- Ссылаемся на crm.calls (журнал звонилки), НЕ дублируем его: отметка оператора
-- (outcome) и recording_ref живут там, флаги «отметка не сходится» сверяют оба.
CREATE TABLE analyzer.calls (
  call_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  crm_call_id       UUID REFERENCES crm.calls(id) ON DELETE SET NULL,
  casino_id         TEXT NOT NULL DEFAULT 'default',
  operator_id       UUID NOT NULL,
  casino_player_id  BIGINT NOT NULL,
  source            TEXT NOT NULL DEFAULT 'tegsoft',
  channels          INT  NOT NULL DEFAULT 1,
  audio_ref         TEXT,                -- ключ записи у провайдера; сырое аудио НЕ храним
  started_at        TIMESTAMPTZ,
  ended_at          TIMESTAMPTZ,
  duration_s        INT,
  snr               REAL,
  player_speech_ms  INT,                 -- для флагов «игрок не говорил»
  status            analyzer.call_status NOT NULL DEFAULT 'received',
  recommended_offer_id TEXT,             -- из нашего оффер-движка (что должен был назвать)
  flags             JSONB NOT NULL DEFAULT '[]',  -- флаги подлинности (§11.4): too_short|no_player_speech|mark_mismatch_*|repeated_pattern|random_review
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_an_calls_status   ON analyzer.calls(status, created_at DESC);
CREATE INDEX idx_an_calls_operator ON analyzer.calls(operator_id, started_at DESC);
CREATE INDEX idx_an_calls_player   ON analyzer.calls(casino_player_id, started_at DESC);
CREATE UNIQUE INDEX uq_an_calls_crm ON analyzer.calls(crm_call_id) WHERE crm_call_id IS NOT NULL;

-- ── Транскрипты ──────────────────────────────────────────────────────────────
-- Только text_redacted (PII вырезан ДО записи — dev spec §11). Переводы
-- кэшируются по требованию (интерфейс §5: перевод подгружается при открытии).
CREATE TABLE analyzer.transcripts (
  transcript_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id          UUID NOT NULL REFERENCES analyzer.calls(call_id) ON DELETE CASCADE,
  asr_provider     TEXT NOT NULL,
  language         TEXT NOT NULL DEFAULT 'tr',
  text_redacted    TEXT NOT NULL,
  words            JSONB NOT NULL DEFAULT '[]',  -- [{w,start,end,role AGENT|PLAYER,conf}]
  diarization_conf REAL,
  translation_ru   TEXT,                -- кэш перевода (on-demand)
  translation_en   TEXT,
  translation_verified BOOL NOT NULL DEFAULT false,  -- §10.11 «перевод проверен»
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_an_transcripts_call ON analyzer.transcripts(call_id);

-- ── Аудиты (оценка LLM) ───────────────────────────────────────────────────────
CREATE TABLE analyzer.call_audits (
  audit_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id           UUID NOT NULL REFERENCES analyzer.calls(call_id) ON DELETE CASCADE,
  prompt_version    TEXT NOT NULL,
  rubric_version    TEXT NOT NULL,
  script_version    INT,                -- версия скрипта казино на момент оценки (может не быть)
  model_used        TEXT NOT NULL,
  overall_score_100 INT,                -- считает КОД (§9), NULL если все критерии needs_human
  pass_fail         TEXT NOT NULL,      -- PASS|NEEDS_REVIEW|FAIL
  dimensions        JSONB NOT NULL,     -- [{name,score,justification,evidence_ts[],needs_human}]
  objections        JSONB NOT NULL DEFAULT '[]',
  compliance        JSONB NOT NULL DEFAULT '[]',  -- обязательные фразы: [{key,present,evidence_ts|null}]
  offer_outcome     TEXT,
  coaching_narrative TEXT,
  highlights        JSONB NOT NULL DEFAULT '[]',
  improvement_areas JSONB NOT NULL DEFAULT '[]',
  needs_human       BOOL NOT NULL DEFAULT false,
  llm_tokens        INT,
  llm_cost_usd      NUMERIC(8,4),
  processing_ms     INT,
  -- последнее человеческое решение (история — в audit_reviews)
  human_reviewed        BOOL NOT NULL DEFAULT false,
  human_override_score  INT,
  human_reviewer_id     UUID,
  human_notes           TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- идемпотентность: повтор по prompt_version+model_used перезаписывает (dev spec §2)
CREATE UNIQUE INDEX uq_an_audits ON analyzer.call_audits(call_id, prompt_version, model_used);
CREATE INDEX idx_an_audits_call ON analyzer.call_audits(call_id, created_at DESC);

-- ── Сверка: подтверждения и правки (интерфейс §7) ─────────────────────────────
-- И подтверждение, и правка — точка данных. Быстрые подтверждения (меньше
-- порога времени) помечаются counted=false: в статистику согласия не идут.
CREATE TABLE analyzer.audit_reviews (
  review_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  audit_id        UUID NOT NULL REFERENCES analyzer.call_audits(audit_id) ON DELETE CASCADE,
  reviewer_id     UUID NOT NULL,
  kind            TEXT NOT NULL CHECK (kind IN ('confirm','override')),
  scores          JSONB,               -- override: {criterion: 1..5}; confirm: NULL
  reason          TEXT,                -- обязателен при override (проверяет API)
  review_time_s   INT NOT NULL,        -- время на разборе — гейт зачёта в сверку
  counted         BOOL NOT NULL,       -- true = идёт в сверку (время >= порога)
  was_random_sample BOOL NOT NULL DEFAULT false,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_an_reviews_audit ON analyzer.audit_reviews(audit_id, created_at DESC);

-- ── Сигнал оффера в ретеншен-модель (dev spec §10.5) ─────────────────────────
CREATE TABLE analyzer.offer_signals (
  signal_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id              UUID NOT NULL REFERENCES analyzer.calls(call_id) ON DELETE CASCADE,
  casino_player_id     BIGINT NOT NULL,
  recommended_offer_id TEXT,
  offer_presented      BOOL NOT NULL,
  player_response      TEXT,            -- accepted|refused|countered|deferred
  alt_offer_worked     BOOL,
  refusal_reason       TEXT,            -- no_money|no_time|distrust|competitor|other
  callback_scheduled   TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_an_signals_call ON analyzer.offer_signals(call_id);

-- ── Коуч-карточки (интерфейс §10.10) ──────────────────────────────────────────
-- Пока вердикт заблокирован, оператор видит карточку только после апрува
-- руководителя (approved_at). Ответ оператора замыкает фидбек-луп.
CREATE TABLE analyzer.coaching_cards (
  card_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id       UUID NOT NULL REFERENCES analyzer.calls(call_id) ON DELETE CASCADE,
  operator_id   UUID NOT NULL,
  tips          JSONB NOT NULL,          -- [{ts,text}] — на турецком (язык оператора)
  approved_by   UUID,
  approved_at   TIMESTAMPTZ,
  delivered_at  TIMESTAMPTZ,             -- оператор открыл
  op_response   TEXT CHECK (op_response IN ('acknowledged','disputed')),
  op_dispute_reason TEXT,                -- Katılmıyorum → причина → в очередь руководителю
  responded_at  TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_an_cards_operator ON analyzer.coaching_cards(operator_id, created_at DESC);
CREATE INDEX idx_an_cards_call     ON analyzer.coaching_cards(call_id);

-- ── Версии скрипта казино (интерфейс §10.8) ───────────────────────────────────
-- Черновик — не версия: version присваивается только при вводе в бой.
CREATE TABLE analyzer.script_versions (
  script_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  casino_id    TEXT NOT NULL DEFAULT 'default',
  version      INT,                     -- NULL = черновик
  status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','archived')),
  blocks       JSONB NOT NULL DEFAULT '[]',
  -- блок: {n, title, text_tr, check_level: verbatim|meaning|none,
  --        criterion: <one of 9>|null, importance: critical|normal|minor,
  --        word_forms: [..], window_words: int}   (формы слов — только с носителем)
  created_by   UUID,
  activated_at TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_an_script_active ON analyzer.script_versions(casino_id) WHERE status = 'active';

-- ── Настройки казино + состояние вердикта (интерфейс §7, §10.13) ─────────────
-- Состояние вердикта — условие рендера экранов оператора и владельца (§12),
-- поэтому оно в данных, а не в конфиге интерфейса.
CREATE TABLE analyzer.settings (
  casino_id         TEXT PRIMARY KEY DEFAULT 'default',
  verdict_unlocked  BOOL NOT NULL DEFAULT false,
  verdict_unlocked_by UUID,
  verdict_unlocked_at TIMESTAMPTZ,
  random_sample_per_day INT NOT NULL DEFAULT 2,   -- 0 = выборка выключена
  min_review_time_s INT NOT NULL DEFAULT 20,      -- порог зачёта подтверждения (калибруется)
  config            JSONB NOT NULL DEFAULT '{}',  -- dev spec §12: rubric_block, weights, snr_min, модели…
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO analyzer.settings (casino_id) VALUES ('default');

-- ── Журнал доступа (иммутабельный, dev spec §4.1) ─────────────────────────────
CREATE TABLE analyzer.access_log (
  id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_id  UUID NOT NULL,
  call_id   UUID,
  action    TEXT NOT NULL,   -- view_audio|view_transcript|override|confirm|export|translation_check
  at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_an_access_call ON analyzer.access_log(call_id, at DESC);

COMMENT ON SCHEMA analyzer IS 'Call Analyzer: НЕ экспонировать через PostgREST. Доступ только через Flask API (RBAC) и пайплайн-сервис.';
