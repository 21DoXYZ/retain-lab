-- 0009: фикс очереди проверки перевода (§10.11).
--
-- Было: очередь брала transcripts WHERE translation_verified=false, а ответ
-- «не совпадает» оставлял false → первый же mismatch блокировал очередь
-- навсегда, и заметка рецензента терялась (ручка её не читала).
--
-- Стало: отметка «проверено» отдельна от вердикта совпадения. Очередь идёт по
-- translation_checked_at IS NULL; заметка сохраняется.

ALTER TABLE analyzer.transcripts
  ADD COLUMN translation_checked_at TIMESTAMPTZ,
  ADD COLUMN translation_note TEXT;

COMMENT ON COLUMN analyzer.transcripts.translation_checked_at IS
  'Когда рецензент §10.11 проверил перевод (независимо от вердикта). NULL = ещё в очереди';
COMMENT ON COLUMN analyzer.transcripts.translation_note IS
  'Заметка рецензента «где не совпало» (опциональна)';
