-- 0011: именованные скрипты (запрос владельца 17.07.2026).
-- Раньше «скрипт» был приклеен к группе операторов: один поток draft→active на
-- (казино, группа), имя жило только на группе, дефолт = group_id IS NULL.
-- Нельзя было «создать новый скрипт, сохранить, создать ещё и выбрать какой куда».
--
-- Теперь скрипт — самостоятельная именованная сущность (analyzer.scripts),
-- версии привязаны к скрипту (script_versions.script_ref), а маршрутизация —
-- отдельно: у группы поле script_ref («какой скрипт идёт этой группе»,
-- NULL = наследует дефолт), дефолт казино — analyzer.casino_default_script.
-- Старые колонки (group_id в script_versions) остаются для истории/статистики.

-- ── 1. Реестр именованных скриптов ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analyzer.scripts (
    script_ref  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    casino_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    created_by  UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (casino_id, name)
);

-- ── 2. Привязки ─────────────────────────────────────────────────────────────
ALTER TABLE analyzer.script_versions
    ADD COLUMN IF NOT EXISTS script_ref UUID REFERENCES analyzer.scripts(script_ref) ON DELETE CASCADE;
ALTER TABLE analyzer.script_groups
    ADD COLUMN IF NOT EXISTS script_ref UUID REFERENCES analyzer.scripts(script_ref) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS analyzer.casino_default_script (
    casino_id  TEXT PRIMARY KEY,
    script_ref UUID NOT NULL REFERENCES analyzer.scripts(script_ref) ON DELETE CASCADE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 3. Бэкфилл существующих потоков версий ──────────────────────────────────
-- Дефолтный поток (group_id IS NULL) → скрипт «Основной» + назначение дефолтом.
-- Каждый групповой поток → скрипт с именем группы + привязка группе.
DO $$
DECLARE
    cid TEXT;
    g   RECORD;
    ref UUID;
BEGIN
    FOR cid IN SELECT DISTINCT casino_id FROM analyzer.script_versions LOOP
        -- казино-дефолт
        IF EXISTS (SELECT 1 FROM analyzer.script_versions
                   WHERE casino_id = cid AND group_id IS NULL AND script_ref IS NULL) THEN
            INSERT INTO analyzer.scripts (casino_id, name) VALUES (cid, 'Основной')
                ON CONFLICT (casino_id, name) DO UPDATE SET name = EXCLUDED.name
                RETURNING script_ref INTO ref;
            UPDATE analyzer.script_versions SET script_ref = ref
                WHERE casino_id = cid AND group_id IS NULL AND script_ref IS NULL;
            INSERT INTO analyzer.casino_default_script (casino_id, script_ref)
                VALUES (cid, ref) ON CONFLICT (casino_id) DO NOTHING;
        END IF;
        -- групповые потоки
        FOR g IN SELECT DISTINCT sg.group_id, sg.name
                 FROM analyzer.script_groups sg
                 JOIN analyzer.script_versions sv ON sv.group_id = sg.group_id
                 WHERE sg.casino_id = cid AND sv.script_ref IS NULL LOOP
            INSERT INTO analyzer.scripts (casino_id, name)
                VALUES (cid, 'Скрипт: ' || g.name)
                ON CONFLICT (casino_id, name) DO UPDATE SET name = EXCLUDED.name
                RETURNING script_ref INTO ref;
            UPDATE analyzer.script_versions SET script_ref = ref
                WHERE group_id = g.group_id AND script_ref IS NULL;
            UPDATE analyzer.script_groups SET script_ref = ref WHERE group_id = g.group_id;
        END LOOP;
    END LOOP;
END $$;

-- ── 4. Инварианты новой модели ──────────────────────────────────────────────
-- Одна active и один draft на СКРИПТ (раньше — на (казино, группа)).
-- Старый индекс мешает нескольким именованным active со свободным group_id — сносим.
DROP INDEX IF EXISTS analyzer.uq_an_script_active;
CREATE UNIQUE INDEX IF NOT EXISTS uq_an_script_active_ref
    ON analyzer.script_versions (script_ref) WHERE status = 'active' AND script_ref IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_an_script_draft_ref
    ON analyzer.script_versions (script_ref) WHERE status = 'draft' AND script_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_an_groups_script ON analyzer.script_groups (script_ref);
