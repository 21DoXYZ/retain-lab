-- 0008: рекомендации «когда звонить» + их фиксация.
--
-- Каждая выданная рекомендация ПИШЕТСЯ: слот, основание, контекст. Принятие
-- (оператор запланировал по ней звонок) отмечается accepted_at, а исход
-- сверяется аналитикой по crm.calls рядом со слотом. Это учебные данные для
-- будущей модели тайминга: v1 — правила (пик активности игрока + статистика
-- дозвонов), модель придёт, когда накопятся исходы.
--
-- Схема analyzer: НЕ экспонируется через PostgREST (браузер ходит через Flask).

CREATE TABLE analyzer.call_recommendations (
  rec_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  casino_player_id BIGINT NOT NULL,
  operator_id      UUID,                      -- кому показана (NULL = ещё не привязана)
  kind             TEXT NOT NULL CHECK (kind IN ('best_time','retry')),
  slot             TIMESTAMPTZ NOT NULL,      -- рекомендованное время звонка
  basis            TEXT NOT NULL,             -- peak_hour|retry_rule|answer_stats — почему
  context          JSONB NOT NULL DEFAULT '{}',  -- {attempt, prev_outcome, peak_day, peak_hour…}
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  accepted_at      TIMESTAMPTZ,               -- оператор запланировал по рекомендации
  schedule_id      UUID                       -- ссылка на crm.scheduled_calls (мягкая)
);
CREATE INDEX idx_an_rec_player ON analyzer.call_recommendations(casino_player_id, created_at DESC);
CREATE INDEX idx_an_rec_slot   ON analyzer.call_recommendations(slot);

COMMENT ON TABLE analyzer.call_recommendations IS
  'Рекомендации времени звонка + фиксация принятия; исход сверяется по crm.calls (обучающие данные для модели тайминга)';
