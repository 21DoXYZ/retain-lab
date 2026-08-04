"""JSON-API пакет CRM-SPA (headless-бэкенд поверх player_board.py).

Единая точка входа для всех доменных blueprint'ов, которые SPA (Next.js :3000)
дёргает по HTTP с Supabase-JWT в заголовке. Логика расчётов НЕ дублируется —
доменные модули импортируют готовые helper-функции из `player_board`
(`q`, `offer_for`, `_rhythm`, `calc_ngr`, `_has_table`, `GN`, …) и переиспользуют
существующие SQL/формулы. Одни данные — одни цифры (паритет с HTML-страницами).

────────────────────────────────────────────────────────────────────────────
КАК ДОБАВИТЬ СВОЙ ДОМЕН (для агентов C1..C6, A4 и последующих)
────────────────────────────────────────────────────────────────────────────
1. Создай файл `api/<домен>.py` (например `api/money.py`, `api/cohorts.py`).
2. Объяви в нём модуль-уровневую переменную `bp` — это flask.Blueprint:

       from flask import Blueprint
       from .core import require_auth, api_json, mask_pii
       import player_board as pb          # готовые helper-функции борда

       bp = Blueprint('api_money', __name__, url_prefix='/api/v1')

       @bp.get('/money/overview')
       @require_auth(roles=['super_admin', 'director', 'finance'])
       def money_overview():
           cols, rows = pb.q("SELECT ...")          # переиспользуй SQL борда!
           return api_json({'rows': rows})

3. Всё. `register_api(app)` при старте борда сам найдёт файл, увидит `bp`
   и зарегистрирует его. Ядро (`api/core.py`) и `player_board.py` править НЕ нужно.

ПРАВИЛА для доменных модулей:
  • имя blueprint'а — уникальное (`api_<домен>`), иначе Flask откажет в регистрации;
  • url_prefix = '/api/v1' (единый префикс версии);
  • каждый эндпоинт закрыт `@require_auth(roles=[...])` по матрице ролей (раздел 1 плана);
  • PII (phone/email) в ответах прогоняй через `mask_pii(data, role)`;
  • НЕ переписывай финансовые формулы — импортируй их из `player_board`;
  • ответ — через `api_json(payload)` (единый конверт {ok, data} + корректный
    JSON для Decimal/date/NaN и кириллицы).

Единственная правка в `player_board.py` — строка регистрации пакета
(`from api import register_api` + `register_api(app)`), её делает только агент A3.
"""
from __future__ import annotations

import importlib
import os
import pkgutil
from pathlib import Path

from flask import Flask, Blueprint

__all__ = ['register_api']


def _cors_origins(app: Flask) -> list[str]:
    """Origin'ы SPA, которым разрешён доступ к /api/* — из env CORS_ORIGINS.

    На VPS фронт живёт на реальном домене, а не на localhost:3000: без этой
    настройки браузер режет КАЖДЫЙ запрос преполётом, экраны показывают ошибку
    загрузки, хотя бэкенд жив. Формат — список через запятую:

        CORS_ORIGINS=https://crm.example.com,https://www.crm.example.com

    Дефолт — localhost:3000 (dev). Список именно белый, а не '*': с
    supports_credentials=True звёздочка недопустима по спецификации CORS.
    """
    raw = os.environ.get('CORS_ORIGINS', '').strip()
    if not raw:
        app.logger.info('api: CORS_ORIGINS не задан → разрешён только '
                        'http://localhost:3000 (dev). Для VPS укажи домен SPA.')
        return ['http://localhost:3000']
    origins = [o.strip().rstrip('/') for o in raw.split(',') if o.strip()]
    app.logger.info('api: CORS разрешён для: %s', ', '.join(origins))
    return origins


def _iter_domain_modules():
    """Имена всех модулей api/*.py, кроме служебных (__init__ и dunder-файлов)."""
    pkg_dir = Path(__file__).resolve().parent
    for info in pkgutil.iter_modules([str(pkg_dir)]):
        name = info.name
        if name.startswith('_'):
            continue
        yield name


def register_api(app: Flask) -> list[str]:
    """Авто-обнаружение и регистрация всех blueprint'ов пакета `api`.

    Импортирует каждый модуль `api/*.py`, и если в нём есть модуль-уровневая
    переменная `bp` типа flask.Blueprint — регистрирует её на приложении.
    Также включает CORS (только для http://localhost:3000) на маршрутах /api/*.

    Сбой в одном доменном модуле (например, недописанный файл C-агента) НЕ
    роняет весь борд: ошибка логируется, остальные домены регистрируются.

    Возвращает список имён зарегистрированных blueprint'ов.
    """
    # CORS — только для SPA-origin и только на /api/*. Ставим один раз.
    if not app.config.get('_API_CORS_READY'):
        try:
            from flask_cors import CORS
            CORS(
                app,
                resources={r'/api/*': {'origins': _cors_origins(app)}},
                supports_credentials=True,
                allow_headers=['Authorization', 'Content-Type', 'X-Locale'],
                expose_headers=['Content-Type'],
                # PUT/DELETE — для CRUD цепочек/шаблонов/сегментов (этап 3);
                # без них браузерный preflight SPA режет эти ручки.
                methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
            )
            app.config['_API_CORS_READY'] = True
        except Exception as e:  # flask-cors не установлен — не валим борд
            app.logger.warning('api: CORS не подключён (%s). '
                               'Установи flask-cors в .venv для кросс-доменных запросов SPA.', e)

    registered: list[str] = []
    for mod_name in _iter_domain_modules():
        try:
            module = importlib.import_module(f'{__name__}.{mod_name}')
        except Exception as e:
            app.logger.error('api: не удалось импортировать домен %r: %s', mod_name, e)
            continue

        bp = getattr(module, 'bp', None)
        if not isinstance(bp, Blueprint):
            continue
        if bp.name in app.blueprints:
            registered.append(bp.name)
            continue
        try:
            app.register_blueprint(bp)
            registered.append(bp.name)
        except Exception as e:
            app.logger.error('api: не удалось зарегистрировать blueprint %r из %r: %s',
                             getattr(bp, 'name', '?'), mod_name, e)

    app.logger.info('api: зарегистрированы домены: %s', ', '.join(registered) or '(нет)')
    return registered
