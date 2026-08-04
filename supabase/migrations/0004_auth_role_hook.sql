-- =============================================================================
-- 0004 — custom_access_token_hook: кладёт роль/отдел/affiliate_code ПРИЛОЖЕНИЯ
-- в app_metadata выпускаемого access-token (JWT).
--
-- Зачем: Supabase-токен по умолчанию несёт лишь Postgres-роль (`role`='authenticated')
-- и провайдера в app_metadata. Прикладная роль (operator/head_retention/…) в токен НЕ
-- попадала → Flask _extract_role=None → все эндпоинты отдавали 403. Хук читает
-- crm.crm_users по event.user_id и вкладывает claims в app_metadata (авторитетно —
-- пользователь не может подменить, в отличие от user_metadata).
--
-- Канонический паттерн Supabase (сверено через Context7 — custom-access-token-hook):
-- функция выполняется от имени supabase_auth_admin (GoTrue), поэтому ему явно выдаём
-- EXECUTE на функцию + SELECT на crm.crm_users + RLS-политику чтения. Прочим ролям
-- EXECUTE отзываем (хук — не публичный API).
--
-- Включение: supabase/config.toml → [auth.hook.custom_access_token] enabled=true,
--   uri = "pg-functions://postgres/public/custom_access_token_hook".
-- =============================================================================

CREATE OR REPLACE FUNCTION public.custom_access_token_hook(event jsonb)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  claims       jsonb;
  v_role       crm.user_role;
  v_department crm.department;
  v_aff        text;
  v_is_active  boolean;
BEGIN
  SELECT cu.role, cu.department, cu.affiliate_code, cu.is_active
    INTO v_role, v_department, v_aff, v_is_active
    FROM crm.crm_users cu
    WHERE cu.id = (event->>'user_id')::uuid;

  claims := event->'claims';

  -- гарантируем объект app_metadata в claims
  IF claims->'app_metadata' IS NULL OR jsonb_typeof(claims->'app_metadata') <> 'object' THEN
    claims := jsonb_set(claims, '{app_metadata}', '{}'::jsonb);
  END IF;

  IF v_role IS NOT NULL THEN
    -- прикладная роль (авторитетно, читается Flask _extract_role → app_metadata.role)
    claims := jsonb_set(claims, '{app_metadata,role}',      to_jsonb(v_role::text));
    claims := jsonb_set(claims, '{app_metadata,is_active}', to_jsonb(COALESCE(v_is_active, true)));
    IF v_department IS NOT NULL THEN
      claims := jsonb_set(claims, '{app_metadata,department}', to_jsonb(v_department::text));
    END IF;
    IF v_aff IS NOT NULL THEN
      claims := jsonb_set(claims, '{app_metadata,affiliate_code}', to_jsonb(v_aff));
    END IF;
  END IF;

  event := jsonb_set(event, '{claims}', claims);
  RETURN event;
END;
$$;

-- ── доступ GoTrue (supabase_auth_admin вызывает хук при выпуске токена) ──
GRANT USAGE ON SCHEMA public TO supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.custom_access_token_hook(jsonb) TO supabase_auth_admin;
REVOKE EXECUTE ON FUNCTION public.custom_access_token_hook(jsonb) FROM authenticated, anon, public;

-- ── хук читает crm.crm_users → нужен доступ на схему/типы/таблицу + RLS-политика ──
GRANT USAGE ON SCHEMA crm TO supabase_auth_admin;
GRANT USAGE ON TYPE crm.user_role  TO supabase_auth_admin;
GRANT USAGE ON TYPE crm.department TO supabase_auth_admin;
GRANT SELECT ON crm.crm_users TO supabase_auth_admin;

-- crm.crm_users под RLS (0002). supabase_auth_admin НЕ имеет BYPASSRLS → нужна политика.
DROP POLICY IF EXISTS auth_admin_read_crm_users ON crm.crm_users;
CREATE POLICY auth_admin_read_crm_users ON crm.crm_users
  AS PERMISSIVE FOR SELECT
  TO supabase_auth_admin
  USING (true);
