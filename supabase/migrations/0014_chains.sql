-- 0014: Цепочки автоматизации (Этап 3, фаза 3а — W4-T3).
--
-- Схема automation НАМЕРЕННО не экспонируется через PostgREST (не добавлять в
-- exposed schemas!): браузер сюда не ходит. Читает/пишет Flask (api/chains.py,
-- RBAC по ролям) и chain-runner (W4-T4). Это зеркалит подход схемы analyzer
-- (0007): определения живут в Postgres, доступ — только через приложение.
--
-- Что здесь:
--   • chains            — сама цепочка (имя, статус, автор);
--   • chain_versions    — версии definition; активная версия «замораживается» —
--                         игроки внутри доходят по своей version_id (ТЗ §2.5:
--                         изменение активной = новая версия, старые не трогаются);
--   • chain_enrollments — членство игрока в прогоне цепочки (+анти-дубль);
--   • templates         — шаблоны сообщений с языковыми версиями и {vars}.
--
-- Порядок относительно 0013_segments.sql (параллельная задача W4-T1) неважен:
-- обе миграции создают схему automation идемпотентно (CREATE SCHEMA IF NOT EXISTS).

CREATE SCHEMA IF NOT EXISTS automation;

-- ── Цепочка ───────────────────────────────────────────────────────────────────
-- Статус — машина состояний: draft → active → paused → (archived). draft можно
-- редактировать (имя/описание/definition); active/paused редактируют definition
-- только через новую версию. created_by ссылается на автора (crm.crm_users);
-- ON DELETE SET NULL — удаление сотрудника не рушит историю цепочек.
CREATE TABLE IF NOT EXISTS automation.chains (
    chain_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL UNIQUE,
    description  TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'draft'
                 CHECK (status IN ('draft', 'active', 'paused', 'archived')),
    created_by   UUID REFERENCES crm.crm_users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at TIMESTAMPTZ,             -- когда цепочку в последний раз ввели в бой
    archived_at  TIMESTAMPTZ
);

-- ── Версии definition ─────────────────────────────────────────────────────────
-- Черновик = строка с activated_at IS NULL (последняя по version_no). Ввод в бой
-- проставляет activated_at и НЕ трогает предыдущие версии: активные enrollments
-- ссылаются на свою version_id и доходят по замороженному определению.
CREATE TABLE IF NOT EXISTS automation.chain_versions (
    version_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chain_id     UUID NOT NULL REFERENCES automation.chains ON DELETE CASCADE,
    version_no   INT NOT NULL,
    definition   JSONB NOT NULL,          -- см. JSON-схему цепочки (валидируется в api/chains.py)
    created_by   UUID REFERENCES crm.crm_users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at TIMESTAMPTZ,             -- NULL = черновик; иначе — момент ввода в бой
    UNIQUE (chain_id, version_no)
);
CREATE INDEX IF NOT EXISTS idx_chain_versions_chain
    ON automation.chain_versions (chain_id, version_no DESC);

-- ── Членство игрока в прогоне цепочки ─────────────────────────────────────────
-- ab_group: main — исполняем действия; control — контрольная группа (действия НЕ
-- исполняются, но конверсия считается). next_wake_at — когда runner-у продолжить.
CREATE TABLE IF NOT EXISTS automation.chain_enrollments (
    enrollment_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chain_id         UUID NOT NULL REFERENCES automation.chains ON DELETE CASCADE,
    version_id       UUID NOT NULL REFERENCES automation.chain_versions,
    casino_player_id BIGINT NOT NULL,
    current_node     TEXT NOT NULL,
    state            TEXT NOT NULL DEFAULT 'active'
                     CHECK (state IN ('active', 'done', 'converted', 'exited')),
    ab_group         TEXT NOT NULL DEFAULT 'main' CHECK (ab_group IN ('main', 'control')),
    entered_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    next_wake_at     TIMESTAMPTZ,
    exited_at        TIMESTAMPTZ,
    exit_reason      TEXT
);
-- Анти-дубль: один игрок не может активно идти по одной цепочке дважды.
CREATE UNIQUE INDEX IF NOT EXISTS uq_chain_active_player
    ON automation.chain_enrollments (chain_id, casino_player_id) WHERE state = 'active';
-- Выборки runner-а: «кого продвигать в этой цепочке» и «кого будить сейчас».
CREATE INDEX IF NOT EXISTS idx_chain_enr_chain_state
    ON automation.chain_enrollments (chain_id, state);
CREATE INDEX IF NOT EXISTS idx_chain_enr_wake
    ON automation.chain_enrollments (next_wake_at) WHERE state = 'active';

-- ── Шаблоны сообщений ─────────────────────────────────────────────────────────
-- texts — языковые версии с плейсхолдерами {vars}, например:
--   {"ru": "Здравствуйте! Ваш бонус {bonus_amount}₺", "en": "...", "tr": "..."}
-- Рендер {vars} и выбор языка — на стороне отправителей (W4-T4).
CREATE TABLE IF NOT EXISTS automation.templates (
    template_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL UNIQUE,
    channel_kind TEXT NOT NULL
                 CHECK (channel_kind IN ('casino_webhook', 'email', 'telegram')),
    texts        JSONB NOT NULL DEFAULT '{}',
    created_by   UUID REFERENCES crm.crm_users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── RLS (минимальная, defense-in-depth) ───────────────────────────────────────
-- Схема не в PostgREST → анон/authenticated роли сюда не ходят вовсе. Гейт —
-- Flask (@require_auth по ролям). RLS включаем без политик: для не-владельца
-- (роли anon/authenticated) это deny-all, а Flask ходит под postgres (обходит
-- RLS). Так даже случайное подключение схемы к PostgREST не откроет данные.
ALTER TABLE automation.chains ENABLE ROW LEVEL SECURITY;
ALTER TABLE automation.chain_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE automation.chain_enrollments ENABLE ROW LEVEL SECURITY;
ALTER TABLE automation.templates ENABLE ROW LEVEL SECURITY;

COMMENT ON SCHEMA automation IS 'Сегменты и цепочки автоматизации: НЕ экспонировать через PostgREST. Доступ только через Flask API (RBAC) и chain-runner.';
