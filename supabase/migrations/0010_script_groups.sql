-- 0010: A/B-скрипты — разные скрипты разным группам операторов.
--
-- Раньше: один активный скрипт на казино (uq_an_script_active per casino_id).
-- Теперь: руководитель собирает ГРУППЫ операторов и даёт каждой свой активный
-- скрипт. Звонок оператора оценивается по скрипту ЕГО группы; оператор без
-- группы (или группа без активного скрипта) → скрипт казино по умолчанию
-- (group_id IS NULL) — обратная совместимость с одиночным потоком сохранена.

CREATE TABLE analyzer.script_groups (
  group_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  casino_id  TEXT NOT NULL DEFAULT 'default',
  name       TEXT NOT NULL,               -- «Группа A», «Группа B» — задаёт руководитель
  created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_an_sgroups_casino ON analyzer.script_groups(casino_id);

-- Оператор состоит максимум в ОДНОЙ группе (PK на operator_id): иначе неоднозначно,
-- по какому скрипту его судить.
CREATE TABLE analyzer.script_group_members (
  operator_id UUID PRIMARY KEY,
  group_id    UUID NOT NULL REFERENCES analyzer.script_groups(group_id) ON DELETE CASCADE,
  added_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_an_sgmembers_group ON analyzer.script_group_members(group_id);

-- Скрипт привязывается к группе. NULL = скрипт казино по умолчанию (как было).
ALTER TABLE analyzer.script_versions
  ADD COLUMN group_id UUID REFERENCES analyzer.script_groups(group_id) ON DELETE CASCADE;

-- Активный скрипт теперь уникален per (казино, группа), а не per казино.
-- COALESCE к нулевому UUID: без него два активных default-скрипта (NULL != NULL)
-- прошли бы уникальность.
DROP INDEX IF EXISTS analyzer.uq_an_script_active;
CREATE UNIQUE INDEX uq_an_script_active
  ON analyzer.script_versions
     (casino_id, COALESCE(group_id, '00000000-0000-0000-0000-000000000000'::uuid))
  WHERE status = 'active';

COMMENT ON TABLE analyzer.script_groups IS
  'Группы операторов под A/B-скрипты (руководитель собирает вручную)';
COMMENT ON COLUMN analyzer.script_versions.group_id IS
  'Группа, которой принадлежит скрипт; NULL = скрипт казино по умолчанию';
