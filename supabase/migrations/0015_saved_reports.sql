-- 0015: Сохранённые отчёты конструктора (Этап 3, Волна 5 — W5-T3).
--
-- Схема automation НАМЕРЕННО не экспонируется через PostgREST (не добавлять в
-- exposed schemas!): браузер сюда не ходит. Читает/пишет Flask (api/reports.py +
-- api/reports_store.py, RBAC по ролям REPORT_ROLES). Зеркалит приём схем analyzer
-- (0007) и automation (0013/0014): определения живут в Postgres, доступ — только
-- через приложение с ролевым гейтом.
--
-- Порядок относительно 0013_segments.sql / 0014_chains.sql (параллельные задачи)
-- неважен: все три создают схему automation идемпотентно (CREATE SCHEMA IF NOT EXISTS).

CREATE SCHEMA IF NOT EXISTS automation;

-- ── Сохранённый отчёт ─────────────────────────────────────────────────────────
-- spec — тот же JSON-контракт, что принимает POST /reports/run (метрики × разрезы ×
-- фильтры × период); валидируется компилятором api/report_builder.py ДО записи
-- (ручка отклоняет кривой spec 422). Доступ (зеркалом RLS, гейт в Flask):
--   • visibility='personal' — виден только владельцу (owner_id);
--   • visibility='shared'   — виден всем ролям с доступом к модулю (REPORT_ROLES);
--   • visibility='roles'    — виден ролям из массива roles (+ владельцу).
-- is_official — «канонический отчёт компании» (рекомендация Василия: один на
-- компанию); ставит только director/head_retention/super_admin (проверка в ручке).
-- owner_id ON DELETE CASCADE: удаление сотрудника уносит его личные отчёты.
CREATE TABLE IF NOT EXISTS automation.saved_reports (
    report_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    spec        JSONB NOT NULL,
    owner_id    UUID NOT NULL REFERENCES crm.crm_users(id) ON DELETE CASCADE,
    visibility  TEXT NOT NULL DEFAULT 'personal'
                CHECK (visibility IN ('personal', 'shared', 'roles')),
    roles       crm.user_role[] NOT NULL DEFAULT '{}',   -- для visibility='roles'
    is_official BOOLEAN NOT NULL DEFAULT false,           -- «канонический отчёт компании»
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_id, name)                               -- у автора имена уникальны
);

-- Список видимых отчёту: официальные сверху, затем свежие (ORDER BY is_official, updated_at).
CREATE INDEX IF NOT EXISTS idx_saved_reports_list
    ON automation.saved_reports (is_official DESC, updated_at DESC);
-- Быстрый разбор visibility='roles' (roles @> ARRAY[роль]).
CREATE INDEX IF NOT EXISTS idx_saved_reports_roles
    ON automation.saved_reports USING GIN (roles);

COMMENT ON TABLE automation.saved_reports IS
    'Сохранённые отчёты конструктора: НЕ экспонировать через PostgREST. Доступ только через Flask API (RBAC).';

-- ── RLS (минимальная, defense-in-depth) ───────────────────────────────────────
-- Схема не в PostgREST → анон/authenticated роли сюда не ходят вовсе. Гейт —
-- Flask (@require_auth по ролям). Flask ходит суперюзером (SUPABASE_DB_URL=postgres)
-- и обходит RLS; anon/authenticated не получают ничего. Так даже случайное
-- подключение схемы к PostgREST не откроет данные (зеркало 0013/0014).
ALTER TABLE automation.saved_reports ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS saved_reports_service_all ON automation.saved_reports;
CREATE POLICY saved_reports_service_all ON automation.saved_reports
    FOR ALL TO service_role USING (true) WITH CHECK (true);

GRANT USAGE ON SCHEMA automation TO service_role;
GRANT ALL ON automation.saved_reports TO service_role;
REVOKE ALL ON automation.saved_reports FROM anon, authenticated;
