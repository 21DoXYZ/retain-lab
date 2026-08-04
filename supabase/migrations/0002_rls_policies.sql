-- =============================================================================
-- 0002 — RLS-политики для crm.* под матрицу прав (SPA_BUILD_PLAN.md раздел 1 +
-- ТЗ колл-центра п.1.2). Defense-in-depth: БД физически режет чужие строки, даже
-- если приложение ошибётся. Все ролевые проверки — через SECURITY DEFINER-хелперы
-- из 0001 (обходят RLS crm_users → нет рекурсии, см. Supabase RLS best practices).
--
-- Конвенции:
--   * все политики TO authenticated (anon не получает НИЧЕГО — операционка под auth);
--   * auth.uid() оборачиваем в (select auth.uid()) — план выполняется 1 раз на запрос;
--   * отдельные политики на SELECT/INSERT/UPDATE/DELETE (в рамках команды — OR);
--   * service_role (backend: синк каталога, webhook звонков) обходит RLS штатно.
-- =============================================================================

-- ---- ПРАВА НА СХЕМУ/ОБЪЕКТЫ (RLS фильтрует строки ТОЛЬКО поверх table privileges) ----
GRANT USAGE ON SCHEMA crm TO authenticated, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA crm TO authenticated;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA crm TO authenticated;
GRANT EXECUTE                        ON ALL FUNCTIONS IN SCHEMA crm TO authenticated;

GRANT ALL     ON ALL TABLES    IN SCHEMA crm TO service_role;
GRANT ALL     ON ALL SEQUENCES IN SCHEMA crm TO service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA crm TO service_role;

-- audit_log неизменяем (доказуемость RevShare): у authenticated отбираем UPDATE/DELETE,
-- политик на UPDATE/DELETE тоже НЕ создаём. Правки/чистка — только через service_role/DBA.
REVOKE UPDATE, DELETE ON crm.audit_log FROM authenticated;

-- ---- ВКЛЮЧАЕМ RLS НА КАЖДОЙ ТАБЛИЦЕ crm.* ----
ALTER TABLE crm.crm_users          ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm.player_directory   ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm.player_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm.notes              ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm.calls              ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm.scheduled_calls    ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm.audit_log          ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm.settings           ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- crm_users — профили. Sensitive-поля (роль/отдел/код/активность) дополнительно
-- стережёт триггер crm.guard_user_mutation (0001) — RLS не видит OLD.
-- =============================================================================
-- Видят: сам себя все; is_admin и director — всех; head_department — свой отдел;
-- affiliate_manager — карточки аффилиатов (управляет кабинетами).
CREATE POLICY crm_users_select ON crm.crm_users FOR SELECT TO authenticated
USING (
  id = (select auth.uid())
  OR crm.is_admin()
  OR crm.my_role() = 'director'
  OR (crm.my_role() = 'head_department' AND id IN (SELECT crm.dept_operators()))
  OR (crm.my_role() = 'affiliate_manager' AND role = 'affiliate')
);

-- Кто кого заводит (раздел 1 «кто создаёт кого»); дубль-страж — триггер.
CREATE POLICY crm_users_insert ON crm.crm_users FOR INSERT TO authenticated
WITH CHECK (
  crm.is_super_admin()
  OR (crm.my_role() = 'head_retention'  AND role IN ('head_department','operator','vip_manager','affiliate'))
  OR (crm.my_role() = 'head_department' AND role = 'operator' AND department = crm.my_department())
  OR (crm.my_role() = 'affiliate_manager' AND role = 'affiliate')
);

-- Свой профиль (full_name; смену роли/отдела режет триггер); is_admin — любого;
-- head_department — операторов своего отдела (блок/сброс, без выпихивания из отдела).
CREATE POLICY crm_users_update ON crm.crm_users FOR UPDATE TO authenticated
USING (
  id = (select auth.uid())
  OR crm.is_admin()
  OR (crm.my_role() = 'head_department' AND id IN (SELECT crm.dept_operators()))
)
WITH CHECK (
  id = (select auth.uid())
  OR crm.is_admin()
  OR (crm.my_role() = 'head_department' AND department = crm.my_department())
);

-- Удаление (передача игроков — на уровне приложения): super_admin — любого;
-- head_retention — любого кроме super_admin; head_department — оператора своего отдела.
CREATE POLICY crm_users_delete ON crm.crm_users FOR DELETE TO authenticated
USING (
  crm.is_super_admin()
  OR (crm.my_role() = 'head_retention'  AND role <> 'super_admin')
  OR (crm.my_role() = 'head_department' AND role = 'operator' AND id IN (SELECT crm.dept_operators()))
);

-- =============================================================================
-- player_directory — каталог (синк из ClickHouse через service_role, RLS обходится).
-- =============================================================================
-- Читают: надзор/аналитика — всех; оператор — своих; глава — игроков отдела;
-- vip_manager — vip_level>=порога ИЛИ назначенных; аффилиат — свой код.
CREATE POLICY player_dir_select ON crm.player_directory FOR SELECT TO authenticated
USING (
  crm.reads_all_players()
  OR casino_player_id IN (SELECT crm.my_players())                       -- оператор/vip: только СВОИ назначенные
  OR (crm.my_role() = 'head_department' AND casino_player_id IN (SELECT crm.dept_player_ids()))
  OR (crm.my_role() = 'vip_manager'
      AND (vip_level >= crm.vip_threshold() OR casino_player_id IN (SELECT crm.my_players())))
  OR (crm.my_role() = 'affiliate' AND affiliate_code = crm.my_affiliate_code())
);
-- Ручные правки каталога — только super_admin (штатно синкает service_role).
CREATE POLICY player_dir_insert ON crm.player_directory FOR INSERT TO authenticated
  WITH CHECK (crm.is_super_admin());
CREATE POLICY player_dir_update ON crm.player_directory FOR UPDATE TO authenticated
  USING (crm.is_super_admin()) WITH CHECK (crm.is_super_admin());
CREATE POLICY player_dir_delete ON crm.player_directory FOR DELETE TO authenticated
  USING (crm.is_super_admin());

-- =============================================================================
-- player_assignments — кто чей игрок (пересечения разрешены).
-- =============================================================================
-- Оператор видит свои назначения И все назначения по СВОИМ игрокам («также у: …»).
CREATE POLICY assign_select ON crm.player_assignments FOR SELECT TO authenticated
USING (
  crm.is_admin()
  OR crm.my_role() IN ('director','analyst','finance','risk_officer','viewer')
  OR operator_id = (select auth.uid())
  OR (crm.my_role() = 'head_department' AND operator_id IN (SELECT crm.dept_operators()))
  OR casino_player_id IN (SELECT crm.my_players())
);
-- Раздача: is_admin — между отделами; глава — внутри своего отдела.
CREATE POLICY assign_insert ON crm.player_assignments FOR INSERT TO authenticated
WITH CHECK (
  crm.is_admin()
  OR (crm.my_role() = 'head_department' AND operator_id IN (SELECT crm.dept_operators()))
);
-- Статус/перекидывание: is_admin, глава (свой отдел), оператор (только СВОИ, без передачи).
CREATE POLICY assign_update ON crm.player_assignments FOR UPDATE TO authenticated
USING (
  crm.is_admin()
  OR (crm.my_role() = 'head_department' AND operator_id IN (SELECT crm.dept_operators()))
  OR operator_id = (select auth.uid())
)
WITH CHECK (
  crm.is_admin()
  OR (crm.my_role() = 'head_department' AND operator_id IN (SELECT crm.dept_operators()))
  OR operator_id = (select auth.uid())
);
-- Убрать из очереди: is_admin и глава своего отдела.
CREATE POLICY assign_delete ON crm.player_assignments FOR DELETE TO authenticated
USING (
  crm.is_admin()
  OR (crm.my_role() = 'head_department' AND operator_id IN (SELECT crm.dept_operators()))
);

-- =============================================================================
-- notes — заметки (структурированные теги = фидбэк модели оффера).
-- =============================================================================
-- Видят все по назначенным игрокам (с авторами); надзор/риск/маркетинг/саппорт/демо — все.
CREATE POLICY notes_select ON crm.notes FOR SELECT TO authenticated
USING (
  crm.reads_all_notes()
  OR author_id = (select auth.uid())
  OR casino_player_id IN (SELECT crm.my_players())
  OR (crm.my_role() = 'head_department'
      AND (author_id IN (SELECT crm.dept_operators()) OR casino_player_id IN (SELECT crm.dept_player_ids())))
  OR (crm.my_role() = 'affiliate' AND casino_player_id IN (SELECT crm.affiliate_player_ids()))
);
-- Пишут по своим игрокам: оператор/vip (my_players), глава (игроки отдела), аффилиат (свой код),
-- саппорт (любой игрок), is_admin. author_id всегда = сам.
CREATE POLICY notes_insert ON crm.notes FOR INSERT TO authenticated
WITH CHECK (
  author_id = (select auth.uid())
  AND (
    crm.is_admin()
    OR crm.my_role() = 'support'
    OR casino_player_id IN (SELECT crm.my_players())
    OR (crm.my_role() = 'head_department' AND casino_player_id IN (SELECT crm.dept_player_ids()))
    OR (crm.my_role() = 'affiliate' AND casino_player_id IN (SELECT crm.affiliate_player_ids()))
  )
);
-- Правит только автор (окно 15 мин — в приложении).
CREATE POLICY notes_update ON crm.notes FOR UPDATE TO authenticated
USING (author_id = (select auth.uid()))
WITH CHECK (author_id = (select auth.uid()));
-- Удаляют только head_retention и super_admin (ТЗ п.4.1).
CREATE POLICY notes_delete ON crm.notes FOR DELETE TO authenticated
USING (crm.is_admin());

-- =============================================================================
-- calls — журнал звонков (append-only; исход добивается 2 кликами → UPDATE автора).
-- =============================================================================
-- Видят: деньги/риск/надзор/аналитика — весь журнал (контроль КЦ); оператор — по своим
-- игрокам и свои звонки; глава — по отделу; аффилиат — по своим игрокам.
CREATE POLICY calls_select ON crm.calls FOR SELECT TO authenticated
USING (
  crm.reads_all_calls()
  OR operator_id = (select auth.uid())
  OR casino_player_id IN (SELECT crm.my_players())
  OR (crm.my_role() = 'head_department'
      AND (operator_id IN (SELECT crm.dept_operators()) OR casino_player_id IN (SELECT crm.dept_player_ids())))
  OR (crm.my_role() = 'affiliate' AND casino_player_id IN (SELECT crm.affiliate_player_ids()))
);
-- Фиксирует звонок тот, кто звонил (operator_id = сам); право звонка — по матрице.
-- Webhook-приёмник Tegsoft пишет через service_role (RLS обходится).
CREATE POLICY calls_insert ON crm.calls FOR INSERT TO authenticated
WITH CHECK (
  operator_id = (select auth.uid())
  AND (
    crm.is_admin()
    OR crm.my_role() IN ('operator','head_department','vip_manager')
    OR (crm.my_role() = 'affiliate' AND casino_player_id IN (SELECT crm.affiliate_player_ids()))
  )
);
-- Исход/результат добивает автор звонка (или is_admin).
CREATE POLICY calls_update ON crm.calls FOR UPDATE TO authenticated
USING (crm.is_admin() OR operator_id = (select auth.uid()))
WITH CHECK (crm.is_admin() OR operator_id = (select auth.uid()));
-- Чистка журнала — только head_retention/super_admin (целостность контроля КЦ).
CREATE POLICY calls_delete ON crm.calls FOR DELETE TO authenticated
USING (crm.is_admin());

-- =============================================================================
-- scheduled_calls — план дня оператора / сводка главы.
-- =============================================================================
CREATE POLICY sched_select ON crm.scheduled_calls FOR SELECT TO authenticated
USING (
  crm.is_admin() OR crm.my_role() = 'director'
  OR operator_id = (select auth.uid())
  OR (crm.my_role() = 'head_department' AND operator_id IN (SELECT crm.dept_operators()))
);
CREATE POLICY sched_insert ON crm.scheduled_calls FOR INSERT TO authenticated
WITH CHECK (
  crm.is_admin()
  OR operator_id = (select auth.uid())
  OR (crm.my_role() = 'head_department' AND operator_id IN (SELECT crm.dept_operators()))
);
CREATE POLICY sched_update ON crm.scheduled_calls FOR UPDATE TO authenticated
USING (
  crm.is_admin()
  OR operator_id = (select auth.uid())
  OR (crm.my_role() = 'head_department' AND operator_id IN (SELECT crm.dept_operators()))
)
WITH CHECK (
  crm.is_admin()
  OR operator_id = (select auth.uid())
  OR (crm.my_role() = 'head_department' AND operator_id IN (SELECT crm.dept_operators()))
);
CREATE POLICY sched_delete ON crm.scheduled_calls FOR DELETE TO authenticated
USING (
  crm.is_admin()
  OR operator_id = (select auth.uid())
  OR (crm.my_role() = 'head_department' AND operator_id IN (SELECT crm.dept_operators()))
);

-- =============================================================================
-- audit_log — неизменяемый журнал действий (INSERT всем; чтение — руководящим).
-- =============================================================================
-- Читают весь: super_admin/head_retention/director; head_department — свой отдел.
CREATE POLICY audit_select ON crm.audit_log FOR SELECT TO authenticated
USING (
  crm.reads_audit_all()
  OR (crm.my_role() = 'head_department' AND actor_id IN (SELECT crm.dept_operators()))
);
-- Пишет любой аутентифицированный, но только от своего имени (actor_id = сам).
CREATE POLICY audit_insert ON crm.audit_log FOR INSERT TO authenticated
WITH CHECK (actor_id = (select auth.uid()));
-- UPDATE/DELETE политик НЕТ → запрещено всем (кроме service_role/DBA). Immutable.

-- =============================================================================
-- settings — конфиг (порог VIP и пр.).
-- =============================================================================
-- Читают все аутентифицированные (напр. клиенту нужен vip_threshold).
CREATE POLICY settings_select ON crm.settings FOR SELECT TO authenticated
USING (true);
-- Меняют только super_admin/head_retention.
CREATE POLICY settings_insert ON crm.settings FOR INSERT TO authenticated
  WITH CHECK (crm.is_admin());
CREATE POLICY settings_update ON crm.settings FOR UPDATE TO authenticated
  USING (crm.is_admin()) WITH CHECK (crm.is_admin());
CREATE POLICY settings_delete ON crm.settings FOR DELETE TO authenticated
  USING (crm.is_admin());
