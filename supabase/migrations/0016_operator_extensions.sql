-- 0016: TG-Soft-креды оператора (extension + персональный токен) для телефонии.
--
-- Блокер звонков: у оператора нет ни extension, ни своего токена → originate
-- падает / идёт от общего супер-юзера. В TG-Soft у каждого оператора своя учётка
-- со своим токеном (делится по ролям). Задача: подшить токен КАЖДОГО оператора к
-- его CRM-аккаунту, чтобы вызов по API шёл от его имени; extension — его SIP-номер.
--
-- Управляется в CRM (экран «Внутренние номера»): super_admin/главы. Доступ ТОЛЬКО
-- через Flask (api/calls.py, RBAC), как crm.calls. token — секрет: наружу отдаём
-- лишь признак has_token, сам токен из API не возвращаем.
-- Читает tegsoft.lookup.operator_ext (ext) и api/calls.py (token для originate).

CREATE TABLE IF NOT EXISTS crm.operator_extensions (
    operator_id UUID PRIMARY KEY REFERENCES crm.crm_users(id) ON DELETE CASCADE,
    ext         TEXT,
    usercode    TEXT,          -- логин учётки оператора в Tegsoft (для performLogin)
    password    TEXT,          -- пароль учётки (секрет). Токен получаем логином на лету
    token       TEXT,          -- альтернатива: постоянный API-токен оператора
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by  UUID REFERENCES crm.crm_users(id) ON DELETE SET NULL,
    -- строка существует, если задан хоть один кред (ext / логин+пароль / токен)
    CHECK (ext IS NOT NULL OR token IS NOT NULL OR usercode IS NOT NULL)
);

COMMENT ON TABLE crm.operator_extensions IS
    'TG-Soft-креды оператора (extension + токен). Доступ только через Flask API (RBAC). token — секрет, наружу не отдаём.';

ALTER TABLE crm.operator_extensions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS operator_extensions_service_all ON crm.operator_extensions;
CREATE POLICY operator_extensions_service_all ON crm.operator_extensions
    FOR ALL TO service_role USING (true) WITH CHECK (true);

GRANT ALL ON crm.operator_extensions TO service_role;
