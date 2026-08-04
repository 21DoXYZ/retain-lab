-- =============================================================================
-- 0005 — сохранение истории при удалении учётки (флаг B1).
--
-- Было: crm.notes.author_id и crm.calls.operator_id — NOT NULL + FK ON DELETE CASCADE.
-- Проблема: удаление оператора КАСКАДОМ стирало его заметки и звонки → терялась
-- история/атрибуция/контроль КЦ (а audit_log при этом сохраняется через SET NULL).
--
-- Стало: обе колонки NULLABLE + FK ON DELETE SET NULL. Удаление учётки обнуляет
-- ссылку, но строки заметок/звонков остаются (обезличенная история сохраняется).
-- Вставки по-прежнему требуют author_id/operator_id = auth.uid() (RLS 0002), поэтому
-- NULL появляется ТОЛЬКО после удаления автора — новые записи всегда с автором.
-- =============================================================================

-- ── notes.author_id: CASCADE → SET NULL ──
ALTER TABLE crm.notes ALTER COLUMN author_id DROP NOT NULL;
ALTER TABLE crm.notes DROP CONSTRAINT IF EXISTS notes_author_id_fkey;
ALTER TABLE crm.notes ADD  CONSTRAINT notes_author_id_fkey
  FOREIGN KEY (author_id) REFERENCES crm.crm_users(id) ON DELETE SET NULL;

-- ── calls.operator_id: CASCADE → SET NULL ──
ALTER TABLE crm.calls ALTER COLUMN operator_id DROP NOT NULL;
ALTER TABLE crm.calls DROP CONSTRAINT IF EXISTS calls_operator_id_fkey;
ALTER TABLE crm.calls ADD  CONSTRAINT calls_operator_id_fkey
  FOREIGN KEY (operator_id) REFERENCES crm.crm_users(id) ON DELETE SET NULL;
