-- Список получателей для «Назначить WhatsApp» (кнопка передачи игрока в карточке).
-- Проблема: выпадашка грузилась клиентски из crm.crm_users, а RLS (crm_users_select)
-- даёт ОПЕРАТОРУ видеть только самого себя → у оператора список получателей пустой
-- (не видел ни WhatsApp-менеджера WpNehir, ни руководителей). Карточку открыли
-- операторам — теперь кнопкой пользуются они, и баг вылез.
--
-- Решение: SECURITY DEFINER функция, отдающая ТОЛЬКО список возможных получателей
-- (id/имя/отдел/роль активных операторов/VIP/руководителей, кроме себя) в обход RLS.
-- Это не раскрывает базу игроков (staff-имена, не PII), и запись назначения по-
-- прежнему проходит через RLS player_assignments — граница безопасности цела.
CREATE OR REPLACE FUNCTION crm.handoff_recipients()
RETURNS TABLE (id UUID, full_name TEXT, department TEXT, role TEXT)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT id, full_name, department::TEXT, role::TEXT
  FROM crm.crm_users
  WHERE is_active
    AND role IN ('operator', 'vip_manager', 'head_department', 'head_retention')
    AND id <> (SELECT auth.uid())
  ORDER BY full_name
$$;

REVOKE ALL ON FUNCTION crm.handoff_recipients() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION crm.handoff_recipients() TO authenticated;
