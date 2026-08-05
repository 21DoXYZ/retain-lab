"""Сервисные модули используют плоские импорты (import executors) — так они
запускаются в Docker как top-level скрипты. Для pytest добавляем каталог
сервиса в sys.path, чтобы пакетный импорт stripe_sync.campaign_tick резолвил
свои плоские зависимости."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
