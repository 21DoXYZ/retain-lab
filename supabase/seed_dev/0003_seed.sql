-- =============================================================================
-- 0003 — SEED для локальной разработки/демо (НЕ для прод-БД клиента).
-- Заводит по учётке на каждую из 14 ролей + 3 оператора КЦ и 1 WhatsApp + аффилиат
-- AF104, ~20 игроков в каталоге, назначения/заметки/звонки/план — для живого демо.
--
-- Пароль у ВСЕХ тестовых учёток: crm12345  (логин = e-mail, напр. operator@crm.local).
-- Меняется одним значением в crm._seed_user ниже.
--
-- ВНИМАНИЕ: это migration-файл, значит он применится и на проде при db push. Для боевого
-- деплоя клиенту этот файл исключить из пуша (или обернуть в guard по env). Локально —
-- нужен, т.к. DoD требует «supabase db reset зелёный: все миграции + seed применяются».
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

-- ---- хелпер: завести auth.users + auth.identities + crm.crm_users одним вызовом ----
CREATE OR REPLACE FUNCTION crm._seed_user(
  p_id uuid, p_email text, p_password text, p_full_name text,
  p_role crm.user_role, p_department crm.department DEFAULT NULL, p_affiliate_code text DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = auth, crm, extensions, public AS $$
BEGIN
  -- auth.users: минимальный набор колонок для входа по email/паролю в локальном GoTrue.
  INSERT INTO auth.users (
    instance_id, id, aud, role, email, encrypted_password,
    email_confirmed_at, created_at, updated_at,
    raw_app_meta_data, raw_user_meta_data, is_super_admin,
    confirmation_token, recovery_token, email_change_token_new, email_change
  ) VALUES (
    '00000000-0000-0000-0000-000000000000', p_id, 'authenticated', 'authenticated', p_email,
    extensions.crypt(p_password, extensions.gen_salt('bf')),
    now(), now(), now(),
    '{"provider":"email","providers":["email"]}'::jsonb,
    jsonb_build_object('full_name', p_full_name),
    false, '', '', '', ''
  ) ON CONFLICT (id) DO NOTHING;

  -- auth.identities: без строки identity вход не проходит в свежих версиях GoTrue.
  INSERT INTO auth.identities (
    id, user_id, provider_id, identity_data, provider, last_sign_in_at, created_at, updated_at
  ) VALUES (
    gen_random_uuid(), p_id, p_id::text,
    jsonb_build_object('sub', p_id::text, 'email', p_email),
    'email', now(), now(), now()
  ) ON CONFLICT (provider_id, provider) DO NOTHING;

  -- crm.crm_users: триггер guard пропускает (auth.uid() = NULL в seed-контексте).
  INSERT INTO crm.crm_users (id, full_name, role, department, affiliate_code)
  VALUES (p_id, p_full_name, p_role, p_department, p_affiliate_code)
  ON CONFLICT (id) DO NOTHING;
END;
$$;

-- ======================= 14 РОЛЕЙ (по одной учётке) =========================
-- id-схема: 0000…000N (человекочитаемо). Пароль всем — crm12345.
SELECT crm._seed_user('00000000-0000-0000-0000-000000000001','super_admin@crm.local',      'crm12345','Платформа (мы)',           'super_admin',       NULL,          NULL);
SELECT crm._seed_user('00000000-0000-0000-0000-000000000002','director@crm.local',         'crm12345','Директор',           'director',          NULL,          NULL);
SELECT crm._seed_user('00000000-0000-0000-0000-000000000003','head_retention@crm.local',   'crm12345','Глава ретеншена',           'head_retention',    'retention',   NULL);
SELECT crm._seed_user('00000000-0000-0000-0000-000000000008','marketing@crm.local',        'crm12345','Руководитель маркетинга',   'marketing_manager', NULL,          NULL);
SELECT crm._seed_user('00000000-0000-0000-0000-000000000009','analyst@crm.local',          'crm12345','Аналитик',                  'analyst',           NULL,          NULL);
SELECT crm._seed_user('00000000-0000-0000-0000-00000000000a','finance@crm.local',          'crm12345','Финансист',                 'finance',           NULL,          NULL);

-- ============= ДОП. ОПЕРАТОРЫ КЦ (ещё 2) + ОПЕРАТОР WA + ГЛАВА WA ============

-- created_by: проставим руководителей (для реалистичной картины «кто завёл»)
UPDATE crm.crm_users SET created_by = '00000000-0000-0000-0000-000000000003'
  WHERE id IN ('00000000-0000-0000-0000-000000000004','00000000-0000-0000-0000-000000000006',
               '00000000-0000-0000-0000-00000000000d','00000000-0000-0000-0000-000000000014');
UPDATE crm.crm_users SET created_by = '00000000-0000-0000-0000-000000000004'
  WHERE id IN ('00000000-0000-0000-0000-000000000005','00000000-0000-0000-0000-000000000015',
               '00000000-0000-0000-0000-000000000016');
UPDATE crm.crm_users SET created_by = '00000000-0000-0000-0000-000000000014'
  WHERE id = '00000000-0000-0000-0000-000000000017';

DROP FUNCTION crm._seed_user(uuid, text, text, text, crm.user_role, crm.department, text);

-- ======================= КАТАЛОГ ИГРОКОВ (~20) ==============================
-- vip_level 0..5 (порог vip_manager = 3); lifecycle из ClickHouse-словаря;
-- affiliate_code: AF104 (наш тестовый аффилиат), AF201 (другой), NULL (без кода).
INSERT INTO crm.player_directory (casino_player_id, display_id, affiliate_code, country, vip_level, lifecycle) VALUES
  (900001,'P-900001','AF104','TR',2,'cooling'),
  (900002,'P-900002', NULL, 'TR',1,'active'),
  (900003,'P-900003', NULL, 'TR',0,'at_risk'),
  (900004,'P-900004','AF201','GE',3,'dormant'),
  (900005,'P-900005','AF201','TR',1,'churned'),
  (900006,'P-900006', NULL, 'TR',0,'active'),
  (900007,'P-900007', NULL, 'TR',2,'cooling'),
  (900008,'P-900008', NULL, 'TR',4,'active'),
  (900009,'P-900009', NULL, 'GE',3,'active'),
  (900010,'P-900010','AF104','TR',5,'active'),
  (900011,'P-900011', NULL, 'TR',4,'cooling'),
  (900012,'P-900012','AF104','TR',1,'at_risk'),
  (900013,'P-900013','AF104','GE',0,'churned'),
  (900014,'P-900014','AF201','TR',2,'dormant'),
  (900015,'P-900015', NULL, 'TR',3,'cooling'),
  (900016,'P-900016', NULL, 'TR',0,'never'),
  (900017,'P-900017', NULL, 'TR',1,'active'),
  (900018,'P-900018','AF201','GE',5,'dormant'),
  (900019,'P-900019', NULL, 'TR',2,'active'),
  (900020,'P-900020', NULL, 'TR',0,'active')
ON CONFLICT (casino_player_id) DO NOTHING;

-- ======================= НАЗНАЧЕНИЯ (пересечения есть) ======================
-- op1/op2/op3 = call_center; op_wa = whatsapp; 900002 — у op1 И op2 («также у: …»).
INSERT INTO crm.player_assignments (casino_player_id, operator_id, assigned_by, status) VALUES
  (900001,'00000000-0000-0000-0000-000000000005','00000000-0000-0000-0000-000000000004','not_touched'),
  (900002,'00000000-0000-0000-0000-000000000005','00000000-0000-0000-0000-000000000004','answered'),
  (900003,'00000000-0000-0000-0000-000000000005','00000000-0000-0000-0000-000000000004','not_touched'),
  (900002,'00000000-0000-0000-0000-000000000015','00000000-0000-0000-0000-000000000004','not_touched'),
  (900004,'00000000-0000-0000-0000-000000000015','00000000-0000-0000-0000-000000000004','no_answer'),
  (900005,'00000000-0000-0000-0000-000000000015','00000000-0000-0000-0000-000000000004','not_touched'),
  (900006,'00000000-0000-0000-0000-000000000016','00000000-0000-0000-0000-000000000004','not_touched'),
  (900007,'00000000-0000-0000-0000-000000000016','00000000-0000-0000-0000-000000000004','agreed'),
  (900008,'00000000-0000-0000-0000-000000000017','00000000-0000-0000-0000-000000000014','not_touched'),
  (900009,'00000000-0000-0000-0000-000000000017','00000000-0000-0000-0000-000000000014','answered'),
  (900010,'00000000-0000-0000-0000-000000000006','00000000-0000-0000-0000-000000000003','not_touched'),
  (900011,'00000000-0000-0000-0000-000000000006','00000000-0000-0000-0000-000000000003','not_touched')
ON CONFLICT (casino_player_id, operator_id) DO NOTHING;

-- ======================= ЗАМЕТКИ (теги = фидбэк модели) =====================
INSERT INTO crm.notes (casino_player_id, author_id, content, tags, linked_offer) VALUES
  (900001,'00000000-0000-0000-0000-000000000005','Игрок остыл, предложил кэшбэк — не зашло', ARRAY['offer_declined'], 'cashback_20'),
  (900002,'00000000-0000-0000-0000-000000000005','Договорились созвониться завтра вечером',  ARRAY['callback'], NULL),
  (900002,'00000000-0000-0000-0000-000000000015','Не берёт трубку, в WhatsApp прочитал',      ARRAY[]::text[], NULL),
  (900007,'00000000-0000-0000-0000-000000000016','Согласился на депозит после звонка',        ARRAY['returned'], NULL),
  (900010,'00000000-0000-0000-0000-000000000006','VIP доволен, ждёт турнир по слотам',        ARRAY['returned'], NULL),
  (900012,'00000000-0000-0000-0000-00000000000d','Мой игрок, веду в другое казино, вернётся к пятнице', ARRAY[]::text[], NULL);

-- ======================= ЗВОНКИ (журнал; исход 2 кликами) ===================
INSERT INTO crm.calls (casino_player_id, operator_id, duration_sec, outcome, result, provider_ref, recording_ref) VALUES
  (900001,'00000000-0000-0000-0000-000000000005',145,'answered','interested','tg-001','rec-900001-001'),
  (900002,'00000000-0000-0000-0000-000000000015', NULL,'no_answer', NULL, 'tg-002', NULL),
  (900006,'00000000-0000-0000-0000-000000000016', NULL,'busy',      NULL, 'tg-003', NULL),
  (900008,'00000000-0000-0000-0000-000000000017',200,'answered','callback_requested','tg-004','rec-900008-004'),
  (900007,'00000000-0000-0000-0000-000000000016', 96,'answered','interested','tg-005', NULL);

-- ======================= ПЛАН ЗВОНКОВ (просрочка + автослот) ================
INSERT INTO crm.scheduled_calls (casino_player_id, operator_id, scheduled_at, comment, status, by_system) VALUES
  (900003,'00000000-0000-0000-0000-000000000005', now() + interval '1 day',  'Удобно в пятницу вечером', 'planned', false),
  (900001,'00000000-0000-0000-0000-000000000005', now() - interval '1 day',  'Перезвон после кэшбэка',   'overdue', false),
  (900004,'00000000-0000-0000-0000-000000000015', now() + interval '2 hours','Автослот по heatmap',      'planned', true),
  (900009,'00000000-0000-0000-0000-000000000017', now() + interval '3 hours','Сопровождение лояльного',  'planned', false);

-- ======================= АУДИТ (примеры действий) ===========================
INSERT INTO crm.audit_log (actor_id, action, entity, entity_id, meta) VALUES
  ('00000000-0000-0000-0000-000000000005','call',  'player',    '900001', '{"outcome":"answered"}'::jsonb),
  ('00000000-0000-0000-0000-000000000005','note',  'player',    '900001', '{"tags":["offer_declined"]}'::jsonb),
  ('00000000-0000-0000-0000-000000000004','assign','assignment','900002', '{"operator":"operator2","mode":"split"}'::jsonb),
  ('00000000-0000-0000-0000-000000000003','export','players',    NULL,     '{"format":"xlsx","rows":20}'::jsonb),
  ('00000000-0000-0000-0000-00000000000d','login', NULL,         NULL,     '{}'::jsonb);
