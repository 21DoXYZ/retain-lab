#!/usr/bin/env python3
"""chains/presets.py — сидер стартовых пресетов автоматизации.

Заводит три готовых сценария-ЧЕРНОВИКА (draft, НЕ активирует) вместе с их
триггерными сегментами, чтобы оператор сразу видел рабочие примеры «сегмент →
цепочка → путь», а не пустой экран. Пресеты — точки старта: офферы базовые
(ml_recommended / reload_cashback), тексты пустые, версия одна (v1, не боевая).

  1. «Пресет · 1-й → 2-й депозит» — сегмент preset_second_dep (dep_count=1 и
     lifecycle active/cooling): бонус ml_recommended → ML-ожидание (fallback 24 ч,
     окно 11:00–22:00) → условие «есть 2-й депозит» → конверсия / сообщение.
  2. «Пресет · Winback» — сегмент preset_winback (churned и есть история
     депозитов): reload_cashback → фикс-ожидание 48 ч → условие «депозит за 7 дней»
     → конверсия / второе касание.
  3. «Пресет · VIP → Пульт» — сегмент preset_vip_risk (vip_level ≥ 3 и p_churn > 0.5):
     единственный узел desk_task («не бонусом, а человеком») — задача менеджеру в
     Пульт, без бонусов и сообщений. Контроль 0 %: у VIP под риском ручное касание
     не «выключают» ради A/B.

ИДЕМПОТЕНТНОСТЬ. Сегменты сверяются по sys_name, цепочки — по name: создаётся
только недостающее. Повторный запуск ничего не дублирует и не трогает уже
существующие (в т.ч. демо-цепочку из UI-задач). «Пустая таблица» — частный случай
«создать всё недостающее».

Переиспользует боевые слои доступа (api/chains_store, api/segments_store) — тот же
SQL, что и у Flask-ручек, никакого дублирования. Запуск (venv, Flask доступен):
    SUPABASE_DB_URL=... .venv/bin/python -m chains.presets
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from api import chains_store as CS
from api import segments_store as SS

# Имя приветственного шаблона (создан в UI-задачах): если есть — подставим его id
# в узел send_message пресета «1-й → 2-й депозит»; если нет — узел уйдёт с пустым
# шаблоном (для casino_webhook это допустимо, контакты у казино).
WELCOME_TEMPLATE_NAME = 'Приветствие · 1-й депозит'


# ── спецификация пресетных сегментов (definition — JSON конструктора) ─────────
@dataclass(frozen=True)
class SegmentSpec:
    sys_name: str
    name: str
    description: str
    definition: dict


PRESET_SEGMENTS: tuple[SegmentSpec, ...] = (
    SegmentSpec(
        sys_name='preset_second_dep',
        name='Пресет · кандидаты на 2-й депозит',
        description='Один депозит, ещё «тёплые» (lifecycle active/cooling) — цель довести до второго.',
        definition={'all': [
            {'field': 'dep_count', 'op': 'eq', 'value': 1},
            {'field': 'lifecycle', 'op': 'in', 'value': ['active', 'cooling']},
        ]},
    ),
    SegmentSpec(
        sys_name='preset_winback',
        name='Пресет · Winback (ушедшие депозиторы)',
        description='Отток (lifecycle churned) с историей депозитов (dep_sum > 0) — кого возвращаем.',
        definition={'all': [
            {'field': 'lifecycle', 'op': 'in', 'value': ['churned']},
            {'field': 'dep_sum', 'op': 'gt', 'value': 0},
        ]},
    ),
    SegmentSpec(
        sys_name='preset_vip_risk',
        name='Пресет · VIP под риском оттока',
        description='VIP-уровень ≥ 3 и высокая вероятность оттока (p_churn > 0.5) — на личное касание.',
        definition={'all': [
            {'field': 'vip_level', 'op': 'gt', 'value': 2},        # >2 ⇔ ≥3 (уровни целые)
            {'field': 'p_churn', 'op': 'gt', 'value': 0.5},
        ]},
    ),
)


# ── построение definition цепочек (динамические ссылки на шаблон/оператора) ────
def _chain_second_dep(template_id: str) -> dict:
    """Бонус ml_recommended → ML-ожидание → условие «≥2 депозита» → цель / сообщение."""
    return {
        'trigger': {'kind': 'segment', 'sys_name': 'preset_second_dep', 'reentry_days': 30},
        'control_pct': 16,
        'goal': {'event': 'deposit', 'attribution_days': 14},
        'nodes': [
            {'id': 'n1', 'kind': 'action', 'action': 'bonus_grant', 'bonus': 'ml_recommended'},
            {'id': 'n2', 'kind': 'wait', 'mode': 'ml', 'fallback_hours': 24,
             'window': {'from': '11:00', 'to': '22:00'}},
            {'id': 'n3', 'kind': 'condition',
             'if': {'field': 'dep_count', 'op': 'gte', 'value': 2},
             'then': 'exit_converted', 'else': 'n4'},
            {'id': 'n4', 'kind': 'action', 'action': 'send_message', 'channel': 'casino_webhook',
             'template': template_id, 'params': {'bonus_amount': '{rec_bonus}'}},
        ],
    }


def _chain_winback(template_id: str) -> dict:
    """reload_cashback → фикс-ожидание 48 ч → условие «депозит за 7 дней» → цель / касание."""
    return {
        'trigger': {'kind': 'segment', 'sys_name': 'preset_winback', 'reentry_days': 30},
        'control_pct': 16,
        'goal': {'event': 'deposit', 'attribution_days': 14},
        'nodes': [
            {'id': 'n1', 'kind': 'action', 'action': 'bonus_grant', 'bonus': 'reload_cashback'},
            {'id': 'n2', 'kind': 'wait', 'mode': 'fixed', 'hours': 48,
             'window': {'from': '11:00', 'to': '22:00'}},
            {'id': 'n3', 'kind': 'condition',
             'if': {'field': 'deposit_recency_days', 'op': 'lte', 'value': 7},
             'then': 'exit_converted', 'else': 'n4'},
            {'id': 'n4', 'kind': 'action', 'action': 'send_message', 'channel': 'casino_webhook',
             'template': template_id, 'params': {}},
        ],
    }


def _chain_vip_desk(operator_id: str) -> dict:
    """Единственный узел desk_task: задача менеджеру в Пульт (без бонуса и сообщений).

    control_pct=0: ручное касание VIP под риском не «выключают» ради контрольной группы.
    """
    return {
        'trigger': {'kind': 'segment', 'sys_name': 'preset_vip_risk', 'reentry_days': 30},
        'control_pct': 0,
        'goal': {'event': 'deposit', 'attribution_days': 14},
        'nodes': [
            {'id': 'n1', 'kind': 'action', 'action': 'desk_task',
             'assign_to': operator_id, 'reason': 'VIP под риском — личное касание'},
        ],
    }


@dataclass(frozen=True)
class ChainSpec:
    name: str
    description: str
    definition: dict


def _preset_chains(template_id: str, operator_id: str) -> tuple[ChainSpec, ...]:
    return (
        ChainSpec('Пресет · 1-й → 2-й депозит',
                  'Довести игрока с одним депозитом до второго: бонус → ML-ожидание → проверка второго депозита.',
                  _chain_second_dep(template_id)),
        ChainSpec('Пресет · Winback',
                  'Вернуть ушедшего депозитора: кэшбэк-релоуд → пауза 48 ч → проверка депозита → второе касание.',
                  _chain_winback(template_id)),
        ChainSpec('Пресет · VIP → Пульт',
                  'VIP под риском оттока — задача менеджеру в Пульт на личное касание (не бонусом, а человеком).',
                  _chain_vip_desk(operator_id)),
    )


# ── резолв динамических ссылок ────────────────────────────────────────────────
def _welcome_template_id() -> str:
    """Id приветственного шаблона по имени (для узла send_message), '' если нет."""
    try:
        for t in CS.list_templates():
            if t['name'] == WELCOME_TEMPLATE_NAME:
                return t['template_id']
    except Exception:                                # noqa: BLE001 — нет шаблона = пустой узел
        pass
    return ''


def _head_retention_operator() -> str:
    """Оператор по умолчанию для desk_task — активный head_retention, '' если нет.

    Пресет-черновик: конкретного оператора менеджер выберет перед активацией;
    подставляем разумный дефолт, чтобы сценарий был исполним «как есть».
    """
    try:
        with SS.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT id::text AS id FROM crm.crm_users "
                        "WHERE role = 'head_retention' AND is_active "
                        "ORDER BY created_at LIMIT 1")
            row = cur.fetchone()
            return row['id'] if row else ''
    except Exception:                                # noqa: BLE001
        return ''


# ── сидер ─────────────────────────────────────────────────────────────────────
def _seed_segments() -> tuple[list[str], list[str]]:
    """Создать недостающие пресетные сегменты. Возвращает (created, existing) sys_name."""
    created, existing = [], []
    for spec in PRESET_SEGMENTS:
        if SS.get_by_sys_name(spec.sys_name) is not None:
            existing.append(spec.sys_name)
            continue
        SS.create_segment(spec.name, spec.sys_name, spec.description, spec.definition,
                          is_trigger=False, schedule_at='10:00', created_by=None)
        created.append(spec.sys_name)
    return created, existing


def _seed_chains(template_id: str, operator_id: str) -> tuple[list[str], list[str]]:
    """Создать недостающие пресетные цепочки-черновики. Возвращает (created, existing) имена."""
    existing_names = {c['name'] for c in CS.list_chains()}
    created, existing = [], []
    for spec in _preset_chains(template_id, operator_id):
        if spec.name in existing_names:
            existing.append(spec.name)
            continue
        chain_id = CS.create_chain(spec.name, spec.description, created_by=None)
        if chain_id is None:                         # гонка: имя уже занято — считаем существующим
            existing.append(spec.name)
            continue
        CS.save_definition(chain_id, spec.definition, created_by=None)   # draft v1, НЕ активируем
        created.append(spec.name)
    return created, existing


def seed() -> dict:
    """Досеять недостающие пресеты (сегменты + цепочки-черновики). Идемпотентно.

    Возвращает отчёт: {'segments': {'created', 'existing'}, 'chains': {'created', 'existing'}}.
    """
    template_id = _welcome_template_id()
    operator_id = _head_retention_operator()
    seg_created, seg_existing = _seed_segments()
    chn_created, chn_existing = _seed_chains(template_id, operator_id)
    return {
        'template_id': template_id,
        'operator_id': operator_id,
        'segments': {'created': seg_created, 'existing': seg_existing},
        'chains': {'created': chn_created, 'existing': chn_existing},
    }


def main() -> int:
    if not os.environ.get('SUPABASE_DB_URL', '').strip():
        print('presets: SUPABASE_DB_URL не задан — база автоматизации недоступна', file=sys.stderr)
        return 1
    report = seed()
    seg, chn = report['segments'], report['chains']
    print('presets: сегменты  создано=%s · уже были=%s'
          % (seg['created'] or '—', seg['existing'] or '—'))
    print('presets: цепочки   создано=%s · уже были=%s'
          % (chn['created'] or '—', chn['existing'] or '—'))
    tpl = report['template_id'] or '(пусто — casino_webhook не требует)'
    op = report['operator_id'] or '(пусто — оператор задаётся перед активацией)'
    print('presets: шаблон send_message=%s · desk_task оператор=%s' % (tpl, op))
    print('presets: все цепочки — ЧЕРНОВИКИ (draft), боевая активация — вручную.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
