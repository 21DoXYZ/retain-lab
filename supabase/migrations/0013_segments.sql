-- 0013: Конструктор сегментов — определения (crm-слой, Supabase Postgres).
--
-- Схема automation НАМЕРЕННО не экспонируется через PostgREST (не добавлять в
-- exposed schemas!): браузер сюда не ходит. Читает/пишет Flask (api/segments.py,
-- RBAC по ролям marketing_manager/head_retention/super_admin), материализацию
-- гоняет materialize_segments.py. Определения (definition JSONB) — здесь; runtime
-- членство игроков — в ClickHouse retention.segment_members (тяжёлая аналитика).
-- Зеркалим приём схемы analyzer из 0007.
--
-- definition — дерево групп И/ИЛИ (вложенность ≤2) из условий по каталогу
-- api/segment_fields.py; валидируется компилятором api/segment_compiler.py ДО
-- записи (ручка отклоняет кривой JSON 422). Пример:
--   {"all":[{"field":"dep_count","op":"eq","value":1},
--           {"any":[{"field":"lifecycle","op":"in","value":["cooling","at_risk"]}]},
--           {"not_segment":"safety_restricted"},
--           {"event":{"type":"deposit","within_days":30,"op":"gte","count":1}}]}

CREATE SCHEMA IF NOT EXISTS automation;

CREATE TABLE IF NOT EXISTS automation.segments (
    segment_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    sys_name     TEXT NOT NULL UNIQUE CHECK (sys_name ~ '^[a-z][a-z0-9_]{2,63}$'),
    description  TEXT NOT NULL DEFAULT '',
    definition   JSONB NOT NULL,                    -- дерево условий (см. шапку)
    is_trigger   BOOLEAN NOT NULL DEFAULT false,    -- real-time вход (chain-runner каждый цикл)
    schedule_at  TIME NOT NULL DEFAULT '10:00',     -- время суточного пересчёта (Стамбул)
    created_by   UUID REFERENCES crm.crm_users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_segments_active
    ON automation.segments (archived_at) WHERE archived_at IS NULL;

COMMENT ON SCHEMA automation IS
    'Automation (сегменты/цепочки): НЕ экспонировать через PostgREST. Доступ только через Flask API (RBAC) и материализацию.';

-- RLS: политика минимальная — только сервисные роли. Flask ходит суперюзером
-- (SUPABASE_DB_URL=postgres) и обходит RLS; anon/authenticated не получают ничего
-- (схема не в exposed schemas). Это защита в глубину, основной гейт — Flask.
ALTER TABLE automation.segments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS segments_service_all ON automation.segments;
CREATE POLICY segments_service_all ON automation.segments
    FOR ALL TO service_role USING (true) WITH CHECK (true);

GRANT USAGE ON SCHEMA automation TO service_role;
GRANT ALL ON automation.segments TO service_role;
REVOKE ALL ON automation.segments FROM anon, authenticated;
