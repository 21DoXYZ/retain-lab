-- 0006: операционные права director в карточке игрока.
-- Директор — reads_all-роль, но политики INSERT заметок/звонков его не включали:
-- кнопки «Оффер» (пишут заметку) и «Позвонить» (фиксация звонка) падали бы на RLS.
-- Даём director право писать заметки/звонки ПО ЛЮБОМУ игроку (как support у заметок),
-- author_id/operator_id остаётся строго = сам (подмена невозможна).
-- Зеркалит фронт (player-card/access.ts) и Flask (api/calls.py CALL_ROLES).

DROP POLICY IF EXISTS notes_insert ON crm.notes;
CREATE POLICY notes_insert ON crm.notes FOR INSERT TO authenticated
WITH CHECK (
  author_id = (select auth.uid())
  AND (
    crm.is_admin()
    OR crm.my_role() IN ('support', 'director')
    OR casino_player_id IN (SELECT crm.my_players())
    OR (crm.my_role() = 'head_department' AND casino_player_id IN (SELECT crm.dept_player_ids()))
    OR (crm.my_role() = 'affiliate' AND casino_player_id IN (SELECT crm.affiliate_player_ids()))
  )
);

DROP POLICY IF EXISTS calls_insert ON crm.calls;
CREATE POLICY calls_insert ON crm.calls FOR INSERT TO authenticated
WITH CHECK (
  operator_id = (select auth.uid())
  AND (
    crm.is_admin()
    OR crm.my_role() IN ('operator', 'head_department', 'vip_manager', 'director')
    OR (crm.my_role() = 'affiliate' AND casino_player_id IN (SELECT crm.affiliate_player_ids()))
  )
);
