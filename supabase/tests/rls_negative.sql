-- =============================================================================
-- rls_negative.sql — НЕГАТИВНЫЕ тесты RLS (адверсарий): под каждой ролью попытки
-- прочитать/записать ЧУЖОЕ должны вернуть 0 строк или ошибку. Плюс несколько
-- позитивных sanity-проверок (чтобы политики не пере-резали своё).
--
-- Как запускать (psql к локальному Supabase; берётся из `supabase status`):
--   psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -f supabase/tests/rls_negative.sql
-- либо через docker:
--   docker exec -i supabase_db_<ref> psql -U postgres -d postgres < supabase/tests/rls_negative.sql
--
-- Механика: критично выполнять запросы под ролью `authenticated` (postgres-суперюзер
-- ОБХОДИТ RLS!). Пользователя эмулируем через request.jwt.claims → auth.uid().
-- Любой FAIL поднимает EXCEPTION и валит скрипт (ненулевой код). В конце ROLLBACK.
-- Зависит от данных 0003_seed.sql (учётки 0000…000N, игроки 900001..900020).
-- =============================================================================

BEGIN;
SET LOCAL ROLE authenticated;

-- id-справочник (из seed):
--   op1=…0005 (cc)  op2=…0015 (cc)  op_wa=…0017 (wa)  head_cc=…0004  head_wa=…0014
--   head_retention=…0003  director=…0002  analyst=…0009  finance=…000a
--   viewer=…000e  affiliate(AF104)=…000d
-- Назначения: op1→{900001,900002,900003}; op2→{900002,900004,900005}; op_wa→{900008,900009}
-- AF104-игроки: 900001,900010,900012,900013 ; AF201: 900004,900005,900014,900018

-- ============================ ОПЕРАТОР (op1) ================================
SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-000000000005","role":"authenticated"}', true);

DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM crm.player_directory WHERE casino_player_id = 900004;  -- op2-only
  IF n = 0 THEN RAISE NOTICE 'PASS S1: operator не видит чужого игрока 900004';
  ELSE RAISE EXCEPTION 'FAIL S1: operator видит чужого игрока (% строк)', n; END IF;
END $$;

DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM crm.audit_log;                                          -- нет права
  IF n = 0 THEN RAISE NOTICE 'PASS S2: operator не читает audit_log';
  ELSE RAISE EXCEPTION 'FAIL S2: operator читает audit_log (% строк)', n; END IF;
END $$;

DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM crm.scheduled_calls                                     -- план чужого оператора
    WHERE operator_id = '00000000-0000-0000-0000-000000000015';
  IF n = 0 THEN RAISE NOTICE 'PASS S3: operator не видит план op2';
  ELSE RAISE EXCEPTION 'FAIL S3: operator видит чужой план (% строк)', n; END IF;
END $$;

DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM crm.crm_users                                           -- профиль другого оператора
    WHERE id = '00000000-0000-0000-0000-000000000015';
  IF n = 0 THEN RAISE NOTICE 'PASS S3b: operator не видит профиль op2';
  ELSE RAISE EXCEPTION 'FAIL S3b: operator видит чужой профиль (% строк)', n; END IF;
END $$;

DO $$ DECLARE ok boolean := false; BEGIN
  BEGIN
    INSERT INTO crm.notes(casino_player_id, author_id, content)
      VALUES (900004, '00000000-0000-0000-0000-000000000005', 'чужой игрок');         -- вне скоупа
  EXCEPTION WHEN OTHERS THEN ok := true; END;
  IF ok THEN RAISE NOTICE 'PASS S4: operator не пишет заметку по чужому игроку';
  ELSE RAISE EXCEPTION 'FAIL S4: operator записал заметку по чужому игроку!'; END IF;
END $$;

DO $$ DECLARE n int; BEGIN
  WITH d AS (DELETE FROM crm.notes RETURNING 1) SELECT count(*) INTO n FROM d;         -- удаляет только head_retention+
  IF n = 0 THEN RAISE NOTICE 'PASS S5: operator не удаляет заметки (0 строк)';
  ELSE RAISE EXCEPTION 'FAIL S5: operator удалил % заметок', n; END IF;
END $$;

DO $$ DECLARE n int; BEGIN
  WITH u AS (UPDATE crm.settings SET value='99' WHERE key='vip_threshold' RETURNING 1)
    SELECT count(*) INTO n FROM u;                                                     -- меняют только is_admin
  IF n = 0 THEN RAISE NOTICE 'PASS S6: operator не меняет settings (0 строк)';
  ELSE RAISE EXCEPTION 'FAIL S6: operator изменил settings'; END IF;
END $$;

DO $$ DECLARE ok boolean := false; BEGIN
  BEGIN
    UPDATE crm.crm_users SET role = 'super_admin'                                      -- эскалация привилегий
      WHERE id = '00000000-0000-0000-0000-000000000005';
  EXCEPTION WHEN OTHERS THEN ok := true; END;
  IF ok THEN RAISE NOTICE 'PASS S7: operator не эскалирует свою роль (guard-триггер)';
  ELSE RAISE EXCEPTION 'FAIL S7: operator поднял себе роль до super_admin!'; END IF;
END $$;

DO $$ DECLARE ok boolean := false; BEGIN
  BEGIN
    INSERT INTO crm.crm_users(id, full_name, role)
      VALUES (gen_random_uuid(), 'левый', 'operator');                                -- операторов заводят главы
  EXCEPTION WHEN OTHERS THEN ok := true; END;
  IF ok THEN RAISE NOTICE 'PASS S8: operator не создаёт пользователей';
  ELSE RAISE EXCEPTION 'FAIL S8: operator создал пользователя!'; END IF;
END $$;

-- позитив: своё видно и пишется
DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM crm.player_directory WHERE casino_player_id = 900002;    -- свой игрок
  IF n = 1 THEN RAISE NOTICE 'PASS P1: operator видит своего игрока 900002';
  ELSE RAISE EXCEPTION 'FAIL P1: operator не видит своего игрока (% строк)', n; END IF;
END $$;

DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM crm.player_assignments WHERE casino_player_id = 900002;  -- «также у: …» (op1+op2)
  IF n >= 2 THEN RAISE NOTICE 'PASS P2: operator видит co-назначения по своему игроку (% строк)', n;
  ELSE RAISE EXCEPTION 'FAIL P2: не виден co-assignee по 900002 (% строк)', n; END IF;
END $$;

DO $$ DECLARE ok boolean := true; BEGIN
  BEGIN
    INSERT INTO crm.notes(casino_player_id, author_id, content)
      VALUES (900001, '00000000-0000-0000-0000-000000000005', 'своя заметка');         -- свой игрок → ок
  EXCEPTION WHEN OTHERS THEN ok := false; END;
  IF ok THEN RAISE NOTICE 'PASS P5: operator пишет заметку по своему игроку';
  ELSE RAISE EXCEPTION 'FAIL P5: operator не смог записать заметку по своему игроку!'; END IF;
END $$;

-- ============================ АФФИЛИАТ (AF104) ==============================
SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-00000000000d","role":"authenticated"}', true);

DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM crm.player_directory WHERE casino_player_id = 900004;    -- AF201, не мой
  IF n = 0 THEN RAISE NOTICE 'PASS S9: аффилиат не видит игрока чужого кода (AF201)';
  ELSE RAISE EXCEPTION 'FAIL S9: аффилиат видит чужой код (% строк)', n; END IF;
END $$;

DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM crm.player_directory WHERE casino_player_id = 900006;    -- без кода
  IF n = 0 THEN RAISE NOTICE 'PASS S10: аффилиат не видит игрока без кода';
  ELSE RAISE EXCEPTION 'FAIL S10: аффилиат видит игрока без кода (% строк)', n; END IF;
END $$;

DO $$ DECLARE ok boolean := false; BEGIN
  BEGIN
    INSERT INTO crm.notes(casino_player_id, author_id, content)
      VALUES (900004, '00000000-0000-0000-0000-00000000000d', 'чужой код');
  EXCEPTION WHEN OTHERS THEN ok := true; END;
  IF ok THEN RAISE NOTICE 'PASS S11: аффилиат не пишет заметку по чужому коду';
  ELSE RAISE EXCEPTION 'FAIL S11: аффилиат записал заметку по чужому коду!'; END IF;
END $$;

DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM crm.player_directory WHERE affiliate_code = 'AF104';     -- позитив: только свои
  IF n = 4 THEN RAISE NOTICE 'PASS P3: аффилиат видит ровно 4 своих игрока (AF104)';
  ELSE RAISE EXCEPTION 'FAIL P3: аффилиат видит % игроков AF104 (ожидалось 4)', n; END IF;
END $$;

DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM crm.player_directory;                                    -- всего видит только своё
  IF n = 4 THEN RAISE NOTICE 'PASS P3b: аффилиат в каталоге видит только 4 строки';
  ELSE RAISE EXCEPTION 'FAIL P3b: аффилиат видит % строк каталога (ожидалось 4)', n; END IF;
END $$;

-- ============================ ГЛАВА КЦ (head_cc) ============================
SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-000000000004","role":"authenticated"}', true);

DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM crm.player_directory WHERE casino_player_id = 900008;    -- игрок WhatsApp-отдела
  IF n = 0 THEN RAISE NOTICE 'PASS S12: глава КЦ не видит игрока чужого (WA) отдела';
  ELSE RAISE EXCEPTION 'FAIL S12: глава КЦ видит игрока WA-отдела (% строк)', n; END IF;
END $$;

DO $$ DECLARE ok boolean := false; BEGIN
  BEGIN
    INSERT INTO crm.player_assignments(casino_player_id, operator_id, assigned_by)
      VALUES (900006, '00000000-0000-0000-0000-000000000017',                          -- op_wa из чужого отдела
              '00000000-0000-0000-0000-000000000004');
  EXCEPTION WHEN OTHERS THEN ok := true; END;
  IF ok THEN RAISE NOTICE 'PASS S13: глава КЦ не назначает на оператора чужого отдела';
  ELSE RAISE EXCEPTION 'FAIL S13: глава КЦ назначил игрока оператору WA!'; END IF;
END $$;

DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM crm.player_directory WHERE casino_player_id = 900001;    -- позитив: игрок своего отдела
  IF n = 1 THEN RAISE NOTICE 'PASS P4: глава КЦ видит игрока своего отдела';
  ELSE RAISE EXCEPTION 'FAIL P4: глава КЦ не видит игрока своего отдела (% строк)', n; END IF;
END $$;

-- ============================ АНАЛИТИК / ФИНАНСЫ / VIEWER / ДИРЕКТОР =========
SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-000000000009","role":"authenticated"}', true);
DO $$ DECLARE ok boolean := false; BEGIN
  BEGIN
    INSERT INTO crm.notes(casino_player_id, author_id, content)
      VALUES (900001, '00000000-0000-0000-0000-000000000009', 'аналитик пишет');
  EXCEPTION WHEN OTHERS THEN ok := true; END;
  IF ok THEN RAISE NOTICE 'PASS S14: аналитик не пишет заметки (read-only)';
  ELSE RAISE EXCEPTION 'FAIL S14: аналитик записал заметку!'; END IF;
END $$;

SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-00000000000a","role":"authenticated"}', true);
DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM crm.notes;                                               -- финансы заметки не читают
  IF n = 0 THEN RAISE NOTICE 'PASS S17: финансист не читает заметки';
  ELSE RAISE EXCEPTION 'FAIL S17: финансист читает заметки (% строк)', n; END IF;
END $$;

SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-00000000000e","role":"authenticated"}', true);
DO $$ DECLARE ok boolean := false; BEGIN
  BEGIN
    INSERT INTO crm.notes(casino_player_id, author_id, content)
      VALUES (900001, '00000000-0000-0000-0000-00000000000e', 'viewer пишет');
  EXCEPTION WHEN OTHERS THEN ok := true; END;
  IF ok THEN RAISE NOTICE 'PASS S15: viewer ничего не пишет (read-only demo)';
  ELSE RAISE EXCEPTION 'FAIL S15: viewer записал заметку!'; END IF;
END $$;

SELECT set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-000000000002","role":"authenticated"}', true);
DO $$ DECLARE ok boolean := false; BEGIN
  BEGIN
    INSERT INTO crm.player_assignments(casino_player_id, operator_id, assigned_by)
      VALUES (900006, '00000000-0000-0000-0000-000000000005',
              '00000000-0000-0000-0000-000000000002');
  EXCEPTION WHEN OTHERS THEN ok := true; END;
  IF ok THEN RAISE NOTICE 'PASS S16: директор не назначает игроков (read-only надзор)';
  ELSE RAISE EXCEPTION 'FAIL S16: директор создал назначение!'; END IF;
END $$;
-- позитив: директор видит весь каталог
DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM crm.player_directory;
  IF n = 20 THEN RAISE NOTICE 'PASS P6: директор видит весь каталог (20)';
  ELSE RAISE EXCEPTION 'FAIL P6: директор видит % игроков (ожидалось 20)', n; END IF;
END $$;

DO $$ BEGIN RAISE NOTICE '=== ВСЕ RLS-НЕГАТИВНЫЕ ТЕСТЫ ПРОЙДЕНЫ ==='; END $$;

ROLLBACK;
