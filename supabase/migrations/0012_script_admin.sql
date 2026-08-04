-- 0012: гигиена именованных скриптов (продолжение 0011).
-- Архив вместо удаления: версии остаются в статистике (audit.script_version),
-- скрипт лишь исчезает из селекторов. Дефолт и назначенные группам скрипты
-- архивировать нельзя (энфорсит API).
ALTER TABLE analyzer.scripts
    ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT false;
