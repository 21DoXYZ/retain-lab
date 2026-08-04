-- =============================================================================
-- CRM операционка (Supabase/Postgres) — схема, роли, таблицы, триггеры.
-- ЧЕРНОВИК под ТЗ «колл-центр + роли». Аналитика/модели остаются в ClickHouse;
-- здесь только операционное состояние (OLTP): кто чей игрок, заметки, звонки, план.
--
-- Схема `crm` изолирует наши таблицы от auth/public Supabase.
-- Ключ игрока — casino_player_id (UInt из ClickHouse); FK на игрока НЕТ (он не в Postgres),
-- поэтому держим лёгкий синк-каталог player_directory (см. ниже) для RLS и быстрых списков.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS crm;

-- pgcrypto — для crypt()/gen_salt() в seed (локальные пароли auth.users).
-- В Supabase уже установлен в схему extensions; IF NOT EXISTS делает вызов идемпотентным.
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

-- общий триггер updated_at
CREATE OR REPLACE FUNCTION crm.touch_updated_at() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$ LANGUAGE plpgsql;

-- ---- перечисления (роли/статусы из ТЗ) ----
-- ВСЕ 14 ролей системы (раздел 1 SPA_BUILD_PLAN.md). Порядок = как в плане.
-- Ядро этапа 1 — super_admin/head_retention/head_department/operator/affiliate;
-- остальные заложены в enum+RLS сразу (UI-пресеты доделываются в этап 1.5).
CREATE TYPE crm.user_role AS ENUM (
  'super_admin',        -- 1  мы / владелец платформы: всё + ключи/API
  'director',           -- 2  директор казино (C-level): read-only надзор над всей картиной
  'head_retention',     -- 3  глава ретеншена: всё, кроме системных ключей
  'head_department',    -- 4  глава КЦ / WhatsApp: свой отдел + выданные
  'operator',           -- 5  оператор: только назначенные ему игроки
  'vip_manager',        -- 6  VIP-менеджер: игроки vip_level >= порога + назначенные
  'affiliate_manager',  -- 7  наш трафик-менеджер: модуль трафика/аффилиатов
  'marketing_manager',  -- 8  руководитель маркетинга / CRM-менеджер
  'analyst',            -- 9  аналитик: вся аналитика read-only, без контактных PII
  'finance',            -- 10 финансист: деньги/аудит выводов
  'risk_officer',       -- 11 риск/фрод-офицер: аудит, флаги, записи звонков
  'support',            -- 12 саппорт: сокращённая карточка + заметки
  'affiliate',          -- 13 внешний аффилиат: только игроки своего affiliate_code
  'viewer'              -- 14 демо/гость: read-only, обезличенные данные
);
CREATE TYPE crm.department   AS ENUM ('retention','call_center','whatsapp');
CREATE TYPE crm.assign_status AS ENUM ('not_touched','no_answer','answered','agreed','refused','returned');
CREATE TYPE crm.call_outcome AS ENUM ('answered','no_answer','busy','wrong_number');
CREATE TYPE crm.call_result  AS ENUM ('interested','offer_declined','callback_requested','refused');
CREATE TYPE crm.sched_status AS ENUM ('planned','done','overdue','missed');

-- =============================================================================
-- crm_users — профиль пользователя CRM (расширяет auth.users Supabase)
-- =============================================================================
CREATE TABLE crm.crm_users (
  id             UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  full_name      TEXT NOT NULL,
  role           crm.user_role NOT NULL,
  department     crm.department,                 -- для head_department/operator
  affiliate_code TEXT,                           -- только для role='affiliate' (напр. 'AF104')
  is_active      BOOLEAN DEFAULT true NOT NULL,
  created_by     UUID REFERENCES crm.crm_users(id) ON DELETE SET NULL,  -- кто завёл (руководитель)
  created_at     TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at     TIMESTAMPTZ DEFAULT now() NOT NULL
);
COMMENT ON TABLE crm.crm_users IS 'Пользователи CRM: роль, отдел, для аффилиата — его код';
CREATE TRIGGER trg_crm_users_updated BEFORE UPDATE ON crm.crm_users
  FOR EACH ROW EXECUTE FUNCTION crm.touch_updated_at();

-- =============================================================================
-- player_directory — ЛЁГКИЙ синк из ClickHouse (обновляется run_loop / cron).
-- Нужен, чтобы RLS аффилиата и быстрые списки не ходили в ClickHouse на каждый запрос.
-- =============================================================================
CREATE TABLE crm.player_directory (
  casino_player_id BIGINT PRIMARY KEY,
  display_id       TEXT,
  affiliate_code   TEXT,                         -- для RLS аффилиата
  country          TEXT,
  vip_level        SMALLINT,
  lifecycle        TEXT,
  is_valid         BOOLEAN DEFAULT true NOT NULL,
  synced_at        TIMESTAMPTZ DEFAULT now() NOT NULL
);
COMMENT ON TABLE crm.player_directory IS 'Минимальный каталог игроков, синкается из ClickHouse (для RLS/списков)';
CREATE INDEX idx_player_dir_affiliate ON crm.player_directory(affiliate_code);

-- =============================================================================
-- player_assignments — кто чей игрок. ПЕРЕСЕЧЕНИЯ РАЗРЕШЕНЫ (игрок у нескольких).
-- =============================================================================
CREATE TABLE crm.player_assignments (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  casino_player_id BIGINT NOT NULL,
  operator_id      UUID NOT NULL REFERENCES crm.crm_users(id) ON DELETE CASCADE,
  assigned_by      UUID REFERENCES crm.crm_users(id) ON DELETE SET NULL,
  status           crm.assign_status DEFAULT 'not_touched' NOT NULL,
  last_touch_at    TIMESTAMPTZ,                  -- последнее касание (звонок/заметка)
  returned_at      TIMESTAMPTZ,                  -- депозит после касания (атрибуция)
  created_at       TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at       TIMESTAMPTZ DEFAULT now() NOT NULL,
  UNIQUE (casino_player_id, operator_id)         -- один игрок у оператора не дублируется
);
COMMENT ON TABLE crm.player_assignments IS 'Назначение игрока на оператора; пересечения разрешены (прозрачность через notes/calls)';
CREATE INDEX idx_assign_operator ON crm.player_assignments(operator_id);
CREATE INDEX idx_assign_player   ON crm.player_assignments(casino_player_id);
CREATE TRIGGER trg_assign_updated BEFORE UPDATE ON crm.player_assignments
  FOR EACH ROW EXECUTE FUNCTION crm.touch_updated_at();

-- =============================================================================
-- notes — заметки оператора (свободный текст + структурированные теги = фидбэк модели)
-- =============================================================================
CREATE TABLE crm.notes (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  casino_player_id BIGINT NOT NULL,
  author_id        UUID NOT NULL REFERENCES crm.crm_users(id) ON DELETE CASCADE,
  content          TEXT NOT NULL,
  tags             TEXT[] DEFAULT '{}' NOT NULL, -- 'offer_declined','callback','negative','returned'...
  linked_offer     TEXT,                          -- к какому офферу привязан тег 'offer_declined'
  created_at       TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at       TIMESTAMPTZ DEFAULT now() NOT NULL
  -- правка своей заметки 15 мин + удаление только Head of Retention — enforce в приложении
);
COMMENT ON TABLE crm.notes IS 'Заметки по игроку; теги — структурированный фидбэк для модели оффера';
CREATE INDEX idx_notes_player ON crm.notes(casino_player_id);
CREATE INDEX idx_notes_author ON crm.notes(author_id);
CREATE INDEX idx_notes_tags   ON crm.notes USING GIN(tags);
CREATE TRIGGER trg_notes_updated BEFORE UPDATE ON crm.notes
  FOR EACH ROW EXECUTE FUNCTION crm.touch_updated_at();

-- =============================================================================
-- calls — журнал звонков (Techsoft IP; исход в 2 клика)
-- =============================================================================
CREATE TABLE crm.calls (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  casino_player_id BIGINT NOT NULL,
  operator_id      UUID NOT NULL REFERENCES crm.crm_users(id) ON DELETE CASCADE,
  started_at       TIMESTAMPTZ DEFAULT now() NOT NULL,
  duration_sec     INTEGER,                       -- если телефония отдаёт
  outcome          crm.call_outcome NOT NULL,     -- дозвон/недозвон/занято/неверный номер
  result           crm.call_result,               -- заинтересован/оффер не подошёл/перезвонить/отказ
  provider_ref     TEXT,                          -- id звонка в Techsoft/Tegsoft
  recording_ref    TEXT,                          -- ссылка/ключ записи разговора (стрим через adapter; слушают risk_officer/главы)
  created_at       TIMESTAMPTZ DEFAULT now() NOT NULL
);
COMMENT ON TABLE crm.calls IS 'Журнал звонков: кто/кому/когда/исход; контроль КЦ и атрибуция';
COMMENT ON COLUMN crm.calls.recording_ref IS 'Ключ записи разговора у провайдера; стрим только через backend-adapter (не в браузер)';
CREATE INDEX idx_calls_player   ON crm.calls(casino_player_id);
CREATE INDEX idx_calls_operator ON crm.calls(operator_id, started_at DESC);

-- =============================================================================
-- scheduled_calls — календарь (план дня оператора)
-- =============================================================================
CREATE TABLE crm.scheduled_calls (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  casino_player_id BIGINT NOT NULL,
  operator_id      UUID NOT NULL REFERENCES crm.crm_users(id) ON DELETE CASCADE,
  scheduled_at     TIMESTAMPTZ NOT NULL,
  comment          TEXT,
  status           crm.sched_status DEFAULT 'planned' NOT NULL,
  by_system        BOOLEAN DEFAULT false NOT NULL,  -- предложено системой (тепловая карта)
  created_at       TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at       TIMESTAMPTZ DEFAULT now() NOT NULL
);
COMMENT ON TABLE crm.scheduled_calls IS 'Запланированные касания; автоподсказка времени по heatmap';
CREATE INDEX idx_sched_operator ON crm.scheduled_calls(operator_id, scheduled_at);
CREATE TRIGGER trg_sched_updated BEFORE UPDATE ON crm.scheduled_calls
  FOR EACH ROW EXECUTE FUNCTION crm.touch_updated_at();

-- =============================================================================
-- audit_log — каждое действие (основа прозрачности RevShare)
-- =============================================================================
CREATE TABLE crm.audit_log (
  id         BIGSERIAL PRIMARY KEY,
  actor_id   UUID REFERENCES crm.crm_users(id) ON DELETE SET NULL,
  action     TEXT NOT NULL,                       -- 'call','note','assign','reassign','export','login'...
  entity     TEXT,                                -- 'player','operator','assignment'...
  entity_id  TEXT,
  meta       JSONB,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
COMMENT ON TABLE crm.audit_log IS 'Аудит всех действий пользователей — доказуемость RevShare';
CREATE INDEX idx_audit_actor ON crm.audit_log(actor_id, created_at DESC);

-- =============================================================================
-- settings — конфиг CRM (key/value). Здесь живёт порог VIP для vip_manager и т.п.
-- Читают все аутентифицированные; меняют только super_admin/head_retention (RLS в 0002).
-- =============================================================================
CREATE TABLE crm.settings (
  key         TEXT PRIMARY KEY,
  value       TEXT NOT NULL,
  description TEXT,
  updated_at  TIMESTAMPTZ DEFAULT now() NOT NULL
);
COMMENT ON TABLE crm.settings IS 'Настройки CRM (key/value): vip_threshold, окна атрибуции и пр.';
CREATE TRIGGER trg_settings_updated BEFORE UPDATE ON crm.settings
  FOR EACH ROW EXECUTE FUNCTION crm.touch_updated_at();

-- Порог VIP по умолчанию = 3 (vip_level из ClickHouse: 0..5, где 3 ~ «VIP для менеджера»).
-- Открытый вопрос №2 плана; значение конфигурируемо без миграции.
INSERT INTO crm.settings(key, value, description) VALUES
  ('vip_threshold', '3', 'Минимальный vip_level, при котором игрок попадает в зону vip_manager (0..5)')
ON CONFLICT (key) DO NOTHING;

-- =============================================================================
-- Хелперы для RLS (single source of truth = crm_users; STABLE, security definer)
-- =============================================================================
CREATE OR REPLACE FUNCTION crm.my_role() RETURNS crm.user_role
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT role FROM crm.crm_users WHERE id = auth.uid()
$$;
CREATE OR REPLACE FUNCTION crm.my_department() RETURNS crm.department
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT department FROM crm.crm_users WHERE id = auth.uid()
$$;
CREATE OR REPLACE FUNCTION crm.my_affiliate_code() RETURNS TEXT
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT affiliate_code FROM crm.crm_users WHERE id = auth.uid()
$$;
-- игроки, назначенные текущему оператору
CREATE OR REPLACE FUNCTION crm.my_players() RETURNS SETOF BIGINT
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT casino_player_id FROM crm.player_assignments WHERE operator_id = auth.uid()
$$;
-- операторы того же отдела (для head_department). Возвращает пусто, если отдел не задан.
CREATE OR REPLACE FUNCTION crm.dept_operators() RETURNS SETOF UUID
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT id FROM crm.crm_users
  WHERE department IS NOT NULL AND department = crm.my_department()
$$;

-- игроки, назначенные операторам моего отдела (для head_department: «игроки своего отдела»)
CREATE OR REPLACE FUNCTION crm.dept_player_ids() RETURNS SETOF BIGINT
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT DISTINCT a.casino_player_id
  FROM crm.player_assignments a
  WHERE a.operator_id IN (SELECT crm.dept_operators())
$$;

-- игроки моего affiliate-кода (для внешнего аффилиата)
CREATE OR REPLACE FUNCTION crm.affiliate_player_ids() RETURNS SETOF BIGINT
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT d.casino_player_id FROM crm.player_directory d
  WHERE crm.my_affiliate_code() IS NOT NULL
    AND d.affiliate_code = crm.my_affiliate_code()
$$;

-- ---- конфиг / порог VIP ----
CREATE OR REPLACE FUNCTION crm.setting(p_key TEXT) RETURNS TEXT
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT value FROM crm.settings WHERE key = p_key
$$;
CREATE OR REPLACE FUNCTION crm.vip_threshold() RETURNS SMALLINT
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT COALESCE(NULLIF(crm.setting('vip_threshold'), '')::SMALLINT, 3::SMALLINT)
$$;

-- игроки в зоне vip_manager: vip_level >= порога (плюс явно назначенные — см. политики)
CREATE OR REPLACE FUNCTION crm.vip_player_ids() RETURNS SETOF BIGINT
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT d.casino_player_id FROM crm.player_directory d
  WHERE d.vip_level >= crm.vip_threshold()
$$;

-- =============================================================================
-- Хелперы-группы ролей (булевы). Централизуют матрицу прав, чтобы политики 0002
-- читались одной строкой и правились в одном месте. Все — по crm.my_role().
-- =============================================================================
-- полный CRUD по операционке (кроме системных ключей у head_retention — это UI/Flask-уровень)
CREATE OR REPLACE FUNCTION crm.is_admin() RETURNS BOOLEAN
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT crm.my_role() IN ('super_admin','head_retention')
$$;
CREATE OR REPLACE FUNCTION crm.is_super_admin() RETURNS BOOLEAN
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT crm.my_role() = 'super_admin'
$$;
-- кто видит ВЕСЬ каталог игроков (надзор/аналитика/справка), без операционного скоупа
CREATE OR REPLACE FUNCTION crm.reads_all_players() RETURNS BOOLEAN
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT crm.my_role() IN (
    'super_admin','head_retention','director','analyst','finance',
    'risk_officer','viewer','marketing_manager','affiliate_manager','support'
  )
$$;
-- кто видит ВЕСЬ журнал звонков (контроль КЦ, деньги, риск, аналитика)
CREATE OR REPLACE FUNCTION crm.reads_all_calls() RETURNS BOOLEAN
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT crm.my_role() IN (
    'super_admin','head_retention','director','finance','risk_officer','analyst','viewer'
  )
$$;
-- кто видит ВСЕ заметки (надзор/риск/маркетинг-фидбэк/саппорт/демо)
CREATE OR REPLACE FUNCTION crm.reads_all_notes() RETURNS BOOLEAN
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT crm.my_role() IN (
    'super_admin','head_retention','director','risk_officer','marketing_manager','support','viewer'
  )
$$;
-- кто видит ВЕСЬ audit_log (RevShare-прозрачность). head_department — только свой отдел (в политике отдельно)
CREATE OR REPLACE FUNCTION crm.reads_audit_all() RETURNS BOOLEAN
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = crm, public AS $$
  SELECT crm.my_role() IN ('super_admin','head_retention','director')
$$;

-- =============================================================================
-- Защита от эскалации привилегий: RLS в WITH CHECK видит только НОВУЮ строку и не
-- может сравнить OLD/NEW. Поэтому смену чувствительных полей crm_users (роль, отдел,
-- affiliate_code, is_active) стережёт триггер: менять их вправе только руководящие роли,
-- и никто (кроме super_admin) не может выдать/оставить роль super_admin.
-- Оператор может править ТОЛЬКО свой профиль (full_name) — sensitive-поля не меняются.
-- =============================================================================
CREATE OR REPLACE FUNCTION crm.guard_user_mutation() RETURNS TRIGGER
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = crm, public AS $$
DECLARE
  actor crm.user_role := crm.my_role();
BEGIN
  -- Доверенный серверный контекст без конечного пользователя (миграции, seed, сервисные
  -- задачи через service_role без JWT-субъекта) — сквозной проход. Реальный юзер всегда имеет auth.uid().
  IF auth.uid() IS NULL THEN
    RETURN NEW;
  END IF;

  IF TG_OP = 'INSERT' THEN
    -- кто кого заводит (раздел 1, пункт «кто создаёт кого»)
    IF actor = 'super_admin' THEN
      RETURN NEW;                                        -- любые роли
    ELSIF actor = 'head_retention' AND NEW.role IN ('head_department','operator','vip_manager','affiliate') THEN
      RETURN NEW;                                        -- ретеншн-вертикаль + кабинеты аффилиатов
    ELSIF actor = 'head_department' AND NEW.role = 'operator'
          AND NEW.department IS NOT NULL AND NEW.department = crm.my_department() THEN
      RETURN NEW;                                        -- оператор только своего отдела
    ELSIF actor = 'affiliate_manager' AND NEW.role = 'affiliate' THEN
      RETURN NEW;                                        -- кабинеты аффилиатов (по согласованию)
    END IF;
    RAISE EXCEPTION 'crm_users: role % не вправе создавать пользователя с ролью %', actor, NEW.role
      USING ERRCODE = 'insufficient_privilege';
  END IF;

  IF TG_OP = 'UPDATE' THEN
    -- смена только несенситивных полей (напр. full_name самим собой) — разрешена RLS-политикой
    IF NEW.role IS NOT DISTINCT FROM OLD.role
       AND NEW.department IS NOT DISTINCT FROM OLD.department
       AND NEW.affiliate_code IS NOT DISTINCT FROM OLD.affiliate_code
       AND NEW.is_active IS NOT DISTINCT FROM OLD.is_active
       AND NEW.id IS NOT DISTINCT FROM OLD.id THEN
      RETURN NEW;
    END IF;
    -- меняются чувствительные поля — нужен руководитель
    IF actor = 'super_admin' THEN
      RETURN NEW;
    ELSIF actor = 'head_retention'
          AND NEW.role <> 'super_admin' AND OLD.role <> 'super_admin' THEN
      RETURN NEW;                                        -- всё, кроме создания/трогания super_admin
    ELSIF actor = 'head_department'
          AND OLD.role = 'operator' AND NEW.role = 'operator'
          AND OLD.department = crm.my_department() THEN
      RETURN NEW;                                        -- блок/сброс операторов своего отдела
    END IF;
    RAISE EXCEPTION 'crm_users: role % не вправе менять чувствительные поля (роль/отдел/код/активность)', actor
      USING ERRCODE = 'insufficient_privilege';
  END IF;

  RETURN NEW;
END;
$$;
CREATE TRIGGER trg_crm_users_guard
  BEFORE INSERT OR UPDATE ON crm.crm_users
  FOR EACH ROW EXECUTE FUNCTION crm.guard_user_mutation();
