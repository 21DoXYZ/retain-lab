"""Replenishment Autopilot v1: предиктивный реордер расходников (спека
REPLENISHMENT-AUTOPILOT.md). Ставка №1 JTBD-ресёрча e-commerce ЮВА, механика
проверена в проде у SimbaGo (carestatus).

ЧТО ДЕЛАЕТ ОДИН ПРОГОН (идемпотентный, ops_loop раз в час):
  1. Планы из заказов: событие order_confirmed с meta.items -> для каждого
     eligible SKU план ACTIVE (или QUEUED, если цикл той же пары ещё идёт).
     predicted_days = базлайн пары | медиана SKU у тенанта | default_days из
     атрибутов; ничего из этого нет - плана НЕТ (принцип «не гадать»).
     Дубль-защита: plan_id детерминирован по (tenant, identity, sku, order_ref).
  2. Ответы: новый заказ той же пары закрывает цикл REORDERED и открывает
     следующий план; replenishment_confirmed (явное «закончилось») закрывает
     USER_CONFIRMED - ЕДИНСТВЕННОЕ, что двигает EWMA-базлайн;
     replenishment_still_have даёт +7 дней к циклу (не учится);
     replenishment_optout снимает пару с отслеживания навсегда.
  3. Дозревание: сегодня >= started + predicted + extension - lead_days ->
     событие replenishment_due в шину (saas_events) с {{product}} и подписанной
     реордер-ссылкой. Частота зашита в ДВИЖКЕ, не в промпте: не чаще 1/7д на
     план, не больше max_per_customer_week (деф. 2) на identity в неделю.

Касание дальше ведёт штатный контур кампаний: trigger_tick зачисляет в
K7_replenishment по событию replenishment_due, campaign_tick шлёт whatsapp с
фолбэком email со всеми общими предохранителями (autopilot/dry-run, тихие
часы, частотный колпак, бюджет личного номера).

Конфиг тенанта (tenants.json, ключ replenishment): enabled=false по умолчанию -
выключено означает НОЛЬ активности (ни планов, ни событий).

Вертикали: тот же движок обслуживает сервисные бизнесы (салон/клиника/
груминг/ТО) через конфиг - vertical="service" + plan_source_events=
["visit_completed"]. Цикл сервиса = интервал между визитами: meta визита несёт
{service: "..."} (нормализуется в sku, qty=1), следующий визит пары закрывает
цикл REORDERED и учит EWMA фактическим интервалом (см. advance_plans), K7
получает сервисный текст напоминания (apply_vertical_campaign_defaults).
Всё остальное - EWMA, лимиты, K7-контур, reply-intents - общее.

Запуск: TENANT_ID=<пространство> python replenishment.py
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from statistics import median

try:                                    # борд импортирует пакетом, джобы плоско
    from wa_templates import reorder_code
except ImportError:
    from stripe_sync.wa_templates import reorder_code  # type: ignore

# Дефолты конфига тенанта. lead_days=4 - решение владельца по открытому
# вопросу спеки; reorder_url_template - шаблон предзаполненного чекаута
# ТЕНАНТА с плейсхолдерами {sku} и {code} (чекаут на его стороне; у сервисного
# тенанта это ссылка записи - плейсхолдеры те же).
#
# Вертикали (решение владельца 2026-09-18): продукт один, Brain общий,
# вертикаль = конфиг тенанта. vertical="service" (салон/клиника/груминг/ТО):
# цикл - время МЕЖДУ визитами, а не расход упаковки; plan_source_events -
# какие события создают план (сервисный тенант ставит ["visit_completed"]
# или оба). Дефолты воспроизводят прежнее ecom-поведение один в один.
DEFAULTS = {
    "enabled": False,
    "lead_days": 4,
    "reorder_url_template": "",
    "max_per_customer_week": 2,
    "plan_source_events": ["order_confirmed"],
    "vertical": "ecom",
}

VERTICALS = ("ecom", "service")

EWMA_ALPHA = 0.3          # вес свежего цикла в базлайне
STILL_HAVE_EXT_DAYS = 7   # «ещё есть» = +7 дней к циклу
PLAN_DUE_COOLDOWN_D = 7   # не чаще одного replenishment_due в 7 дней на план

EVT_ORDER = "order_confirmed"
EVT_DUE = "replenishment_due"
EVT_CONFIRMED = "replenishment_confirmed"
EVT_STILL_HAVE = "replenishment_still_have"
EVT_OPTOUT = "replenishment_optout"


def _now_dt() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


# ── чистая логика (тестируется без CH) ───────────────────────────────────────

def replenishment_config(tenant_conf: dict) -> dict:
    """Конфиг replenishment тенанта поверх дефолтов. Кривые значения не роняют
    джоб - берётся дефолт (выключенный контур важнее упавшего)."""
    raw = (tenant_conf or {}).get("replenishment") or {}
    cfg = dict(DEFAULTS)
    cfg["enabled"] = bool(raw.get("enabled", cfg["enabled"]))
    cfg["reorder_url_template"] = str(
        raw.get("reorder_url_template") or cfg["reorder_url_template"])
    for key in ("lead_days", "max_per_customer_week"):
        try:
            cfg[key] = max(0, int(raw.get(key, cfg[key])))
        except (TypeError, ValueError):
            pass
    vertical = str(raw.get("vertical") or "").strip().lower()
    cfg["vertical"] = vertical if vertical in VERTICALS else "ecom"
    events = raw.get("plan_source_events")
    if isinstance(events, list):
        clean = []
        for ev in events:
            ev = str(ev or "").strip()
            if ev and ev not in clean:
                clean.append(ev)
        if clean:
            cfg["plan_source_events"] = clean
        else:
            cfg["plan_source_events"] = list(DEFAULTS["plan_source_events"])
    else:
        cfg["plan_source_events"] = list(DEFAULTS["plan_source_events"])
    return cfg


def plan_id_for(tenant: str, identity: str, sku: str, order_ref: str) -> str:
    """Детерминированный id плана = дубль-защита: повтор события того же
    заказа порождает тот же plan_id и отсекается по списку существующих."""
    seed = f"{tenant}|{identity}|{sku}|{order_ref}".encode()
    return hashlib.md5(seed).hexdigest()


def parse_items(meta: str) -> list[dict]:
    """meta заказа -> [{sku, qty, name}]. Мусор молча пропускаем: чужая
    интеграция не должна ронять прогон."""
    try:
        items = json.loads(meta or "{}").get("items") or []
    except (ValueError, TypeError):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        sku = str(it.get("sku") or "").strip()
        if not sku:
            continue
        out.append({"sku": sku,
                    "qty": it.get("qty") or 1,
                    "name": str(it.get("name") or it.get("title") or "").strip()})
    return out


def parse_source_items(meta: str) -> list[dict]:
    """meta плана-источника -> [{sku, qty, name}]. Путь items (заказ) - как
    был, без изменений. Если items нет, сервисное событие (visit_completed)
    может нести {service: "grooming-full"}: нормализуем в тот же вид -
    sku = услуга, qty = 1, дальше весь контур (атрибуты, базлайны, K7)
    работает без ветвлений."""
    items = parse_items(meta)
    if items:
        return items
    try:
        m = json.loads(meta or "{}")
    except (ValueError, TypeError):
        return []
    service = str(m.get("service") or "").strip()
    if not service:
        return []
    name = str(m.get("service_name") or m.get("name") or "").strip()
    return [{"sku": service, "qty": 1, "name": name}]


def predicted_for(identity: str, sku: str, baselines: dict, medians: dict,
                  defaults: dict) -> int:
    """predicted_days пары: базлайн пары -> медиана SKU -> default_days.
    0 = данных нет вообще: план не создаём, а не выдумываем цикл.

    Лестница общая для обеих вертикалей: у сервиса базлайн - это EWMA на
    фактических интервалах МЕЖДУ визитами пары (никакой «упаковки» нет),
    медиана - по всем клиентам той же услуги, default_days - из sku_attrs."""
    base = baselines.get((identity, sku), (0.0, 0))[0]
    if base > 0:
        return max(1, round(base))
    med = medians.get(sku) or 0
    if med > 0:
        return max(1, round(med))
    return int(defaults.get(sku) or 0)


def sku_medians(baselines: dict) -> dict:
    """{sku: медиана базлайнов пар тенанта} - предиктор для новой пары
    знакомого SKU (тёплый старт без первого цикла)."""
    by_sku: dict[str, list[float]] = {}
    for (_identity, sku), (base, _cycles) in baselines.items():
        if base > 0:
            by_sku.setdefault(sku, []).append(float(base))
    return {sku: median(vals) for sku, vals in by_sku.items()}


def build_plans(tenant: str, orders: list[dict], eligible: set, baselines: dict,
                medians: dict, defaults: dict, active_pairs: set,
                existing_plan_ids: set, optout_pairs: set) -> list[dict]:
    """Планы из подтверждённых заказов. orders: [{identity_id, order_ref, ts,
    items}], по времени. План только при явной привязке клиент×SKU (принцип 1);
    пара с идущим циклом получает QUEUED."""
    active = set(active_pairs)
    out: list[dict] = []
    for order in sorted(orders, key=lambda o: o["ts"]):
        identity = order["identity_id"]
        for item in order["items"]:
            sku = item["sku"]
            pair = (identity, sku)
            if sku not in eligible or pair in optout_pairs:
                continue
            pid = plan_id_for(tenant, identity, sku, order["order_ref"])
            if pid in existing_plan_ids:
                continue                       # дубль-защита по order_ref
            predicted = predicted_for(identity, sku, baselines, medians, defaults)
            if predicted <= 0:
                continue                       # цикла не знаем - не гадаем
            status = "QUEUED" if pair in active else "ACTIVE"
            active.add(pair)
            out.append({"plan_id": pid, "identity_id": identity, "sku": sku,
                        "order_ref": order["order_ref"], "status": status,
                        "started_at": order["ts"], "predicted_days": predicted,
                        "extension_days": 0, "finished_at": None,
                        "finish_reason": ""})
    return out


def ewma_update(baseline: float, cycles_count: int,
                cycle_days: float) -> tuple[float, int]:
    """EWMA базлайна по подтверждённому циклу. Первый цикл = сам цикл."""
    cycle_days = float(cycle_days)
    if cycles_count <= 0 or baseline <= 0:
        return round(cycle_days, 2), 1
    new = (1 - EWMA_ALPHA) * float(baseline) + EWMA_ALPHA * cycle_days
    return round(new, 2), cycles_count + 1


def reorder_close_ts(plan: dict, orders_by_pair: dict):
    """Момент реордера: заказ той же пары ПОСЛЕ старта цикла, другой order_ref.
    None - реордера не было."""
    hits = [ts for ts, ref in
            orders_by_pair.get((plan["identity_id"], plan["sku"]), [])
            if ts > plan["started_at"] and ref != plan["order_ref"]]
    return min(hits) if hits else None


def confirm_close_ts(plan: dict, confirms_by_plan: dict, confirms_by_pair: dict):
    """Момент явного «закончилось». Ответ адресуется plan_id (подписанный код)
    либо парой identity×sku - принимаем оба."""
    hits = [ts for ts in confirms_by_plan.get(plan["plan_id"], [])
            if ts > plan["started_at"]]
    hits += [ts for ts in
             confirms_by_pair.get((plan["identity_id"], plan["sku"]), [])
             if ts > plan["started_at"]]
    return min(hits) if hits else None


def extension_days_for(plan: dict, still_by_pair: dict) -> int:
    """+7 дней за каждый ответ «ещё есть» внутри цикла. Выводится из событий
    заново каждый прогон - идемпотентно, без счётчика-мутанта."""
    n = len([ts for ts in
             still_by_pair.get((plan["identity_id"], plan["sku"]), [])
             if ts > plan["started_at"]])
    return STILL_HAVE_EXT_DAYS * n


def advance_plans(plans: list[dict], orders_by_pair: dict,
                  confirms_by_plan: dict, confirms_by_pair: dict,
                  still_by_pair: dict, optout_pairs: set, baselines: dict,
                  now: datetime,
                  vertical: str = "ecom") -> tuple[list[dict], list[dict]]:
    """Смена состояний планов за прогон (чистая). Возвращает
    (обновления планов, обновления базлайнов).

    Порядок закрытия: явное «закончилось» и реордер соревнуются по времени -
    закрывает более раннее. Optout отменяет и ACTIVE, и QUEUED планы пары.
    Освободившаяся пара продвигает самый старый QUEUED в ACTIVE (запасной
    пакет начали в момент конца прежнего).

    Обучение EWMA зависит от вертикали:
      - ecom (дефолт, поведение как было): двигает ТОЛЬКО USER_CONFIRMED
        (принцип 2 спеки) - реордер закрывает цикл REORDERED, но скорость НЕ
        обучает: заказ мог быть впрок, «кончилось» знает только клиент.
      - service: следующий visit_completed той же пары закрывает цикл
        (тот же REORDERED) И учит EWMA фактическим интервалом между визитами.
        Визит - достоверный факт из первых рук: цикл сервиса ЕСТЬ интервал
        между визитами, подтверждение клиента «кончилось» не требуется.
        USER_CONFIRMED учит по-прежнему в обеих вертикалях.
    """
    updates: list[dict] = []
    base_updates: list[dict] = []
    freed: dict[tuple, datetime] = {}
    for plan in plans:
        if plan["status"] != "ACTIVE":
            continue
        pair = (plan["identity_id"], plan["sku"])
        if pair in optout_pairs:
            updates.append({**plan, "status": "FINISHED", "finished_at": now,
                            "finish_reason": "CANCELLED"})
            continue                       # QUEUED пары отменит ветка ниже
        r_ts = reorder_close_ts(plan, orders_by_pair)
        c_ts = confirm_close_ts(plan, confirms_by_plan, confirms_by_pair)
        closed = min((t for t in (r_ts, c_ts) if t is not None), default=None)
        if closed is None:
            ext = extension_days_for(plan, still_by_pair)
            if ext != int(plan["extension_days"]):
                updates.append({**plan, "extension_days": ext})
            continue
        # при равенстве времён явное подтверждение важнее (оно ещё и учит)
        reason = "USER_CONFIRMED" if c_ts is not None and c_ts <= closed \
            else "REORDERED"
        updates.append({**plan, "status": "FINISHED", "finished_at": closed,
                        "finish_reason": reason})
        freed[pair] = closed
        if reason == "USER_CONFIRMED" or vertical == "service":
            cycle = max(1.0, (closed - plan["started_at"]).total_seconds() / 86400)
            old_base, old_cycles = baselines.get(pair, (0.0, 0))
            new_base, new_cycles = ewma_update(old_base, old_cycles, cycle)
            base_updates.append({"identity_id": plan["identity_id"],
                                 "sku": plan["sku"],
                                 "baseline_days": new_base,
                                 "last_cycle_days": round(cycle, 2),
                                 "cycles_count": new_cycles})
    queued = sorted((p for p in plans if p["status"] == "QUEUED"),
                    key=lambda p: p["started_at"])
    promoted: set = set()
    for plan in queued:
        pair = (plan["identity_id"], plan["sku"])
        if pair in optout_pairs:
            updates.append({**plan, "status": "FINISHED", "finished_at": now,
                            "finish_reason": "CANCELLED"})
        elif pair in freed and pair not in promoted:
            promoted.add(pair)
            updates.append({**plan, "status": "ACTIVE",
                            "started_at": freed[pair], "extension_days": 0})
    return updates, base_updates


def due_on(plan: dict, lead_days: int) -> date:
    """Дата напоминания: конец цикла минус lead_days."""
    started = plan["started_at"]
    started_d = started.date() if isinstance(started, datetime) else started
    return started_d + timedelta(days=int(plan["predicted_days"])
                                 + int(plan["extension_days"]) - int(lead_days))


def select_due(plans: list[dict], today: date, lead_days: int,
               last_due_by_plan: dict, week_counts: dict,
               max_per_customer_week: int) -> list[dict]:
    """Кому напоминать СЕЙЧАС. Частотные лимиты живут здесь, в движке:
    не чаще 1/7д на план, не больше max_per_customer_week на identity."""
    counts = dict(week_counts)
    out: list[dict] = []
    for plan in sorted(plans, key=lambda p: due_on(p, lead_days)):
        if plan["status"] != "ACTIVE":
            continue
        if due_on(plan, lead_days) > today:
            continue
        last = last_due_by_plan.get(plan["plan_id"])
        if last is not None and (today - last).days < PLAN_DUE_COOLDOWN_D:
            continue
        identity = plan["identity_id"]
        if counts.get(identity, 0) >= int(max_per_customer_week):
            continue
        counts[identity] = counts.get(identity, 0) + 1
        out.append(plan)
    return out


def reorder_url(template: str, sku: str, code: str) -> str:
    """Реордер-ссылка тенанта: {sku} и {code} в его шаблоне чекаута.
    Нет шаблона - нет ссылки (диалоговый фолбэк оператором из WA-инбокса)."""
    template = str(template or "").strip()
    if not template:
        return ""
    return (template.replace("{sku}", urllib.parse.quote(str(sku), safe=""))
                    .replace("{code}", urllib.parse.quote(str(code), safe="")))


# Дефолтный текст K7-напоминания по вертикали. _default в saas_campaigns.json
# остаётся ecom-текстом («Running low on ...») и НЕ трогается; сервисному
# тенанту базовый текст шага подменяется здесь, ДО наложения overrides и
# A/B-победителей в campaign_tick - правка владельца из CRM ложится поверх,
# как на любой базовый текст. Плейсхолдеры те же: {{product}} = услуга,
# {{reorder_url}} = ссылка записи из reorder_url_template.
K7_CAMPAIGN_ID = "K7_replenishment"
K7_VERTICAL_STEP_TEXT = {
    "service": {
        "subject": "Time for your next {{product}}?",
        "body": "Judging by your last visit, it is about time for your next "
                "{{product}}.\n\nBook again in one tap - same service, pick a "
                "slot that suits you: {{reorder_url}}\n\nNot due yet? Just "
                "ignore this and we will check back later. If you would rather "
                "not get these reminders, reply and we will stop.",
        "cta_label": "Book again",
    },
}


def apply_vertical_campaign_defaults(conf: dict, repl_cfg: dict) -> dict:
    """Базовый текст K7 по вертикали тенанта (чистая). vertical="ecom" (дефолт)
    возвращает конфиг НЕТРОНУТЫМ - тот же объект, ноль изменений поведения.
    Для service подменяются только текстовые поля первого уровня шага
    (subject/body/cta_label); структура шагов, каналы, goal - как в базе."""
    texts = K7_VERTICAL_STEP_TEXT.get(str(repl_cfg.get("vertical") or ""))
    if not texts:
        return conf
    out = copy.deepcopy(conf)
    for camp in out.get("campaigns", []) or []:
        if camp.get("campaign_id") != K7_CAMPAIGN_ID:
            continue
        for step in camp.get("steps", []) or []:
            for field, value in texts.items():
                step[field] = value
    return out


# ── I/O ──────────────────────────────────────────────────────────────────────

PLAN_COLUMNS = ["tenant_id", "plan_id", "identity_id", "sku", "order_ref",
                "status", "started_at", "predicted_days", "extension_days",
                "finished_at", "finish_reason", "updated_at"]
BASELINE_COLUMNS = ["tenant_id", "identity_id", "sku", "baseline_days",
                    "last_cycle_days", "cycles_count", "updated_at"]
EVENT_COLUMNS = ["tenant_id", "event_id", "event_type", "ts", "source",
                 "client_user_id", "email_hash", "meta"]


def _parse_ts(raw) -> datetime:
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None)
    return datetime.fromisoformat(str(raw)).replace(tzinfo=None)


def _load_orders(client, tenant: str,
                 event_types: list[str] | None = None) -> list[dict]:
    """События-источники планов (деф. order_confirmed; сервисный тенант через
    plan_source_events добавляет visit_completed) с items или service,
    дедуплицированные по event_id (сниппет и вебхуки перепосылают).
    order_ref из meta, фолбэк - event_id."""
    rows = client.query(
        """
        SELECT identity_id, event_id, any(ts) AS ts, any(meta) AS meta
        FROM retention.saas_events_resolved
        WHERE tenant_id = %(t)s AND event_type IN %(e)s
        GROUP BY identity_id, event_id
        """, parameters={"t": tenant,
                         "e": list(event_types or [EVT_ORDER])}).result_rows
    out = []
    for identity, event_id, ts, meta in rows:
        items = parse_source_items(meta)
        if not items:
            continue
        try:
            ref = str(json.loads(meta or "{}").get("order_ref") or "").strip()
        except (ValueError, TypeError):
            ref = ""
        out.append({"identity_id": identity, "order_ref": ref or str(event_id),
                    "ts": _parse_ts(ts), "items": items})
    return out


def _load_response_events(client, tenant: str, event_type: str) -> list[dict]:
    """Ответы юзеров (confirmed/still_have/optout): plan_id и/или sku в meta."""
    rows = client.query(
        """
        SELECT identity_id, event_id, any(ts) AS ts, any(meta) AS meta
        FROM retention.saas_events_resolved
        WHERE tenant_id = %(t)s AND event_type = %(e)s
        GROUP BY identity_id, event_id
        """, parameters={"t": tenant, "e": event_type}).result_rows
    out = []
    for identity, _event_id, ts, meta in rows:
        try:
            m = json.loads(meta or "{}")
        except (ValueError, TypeError):
            m = {}
        out.append({"identity_id": identity, "ts": _parse_ts(ts),
                    "plan_id": str(m.get("plan_id") or ""),
                    "sku": str(m.get("sku") or "")})
    return out


def _save_plans(client, tenant: str, plans: list[dict], now: datetime) -> None:
    if not plans:
        return
    now_s = _fmt(now)
    rows = [[tenant, p["plan_id"], p["identity_id"], p["sku"], p["order_ref"],
             p["status"], p["started_at"], int(p["predicted_days"]),
             int(p["extension_days"]), p.get("finished_at"),
             p.get("finish_reason") or "", now_s] for p in plans]
    client.insert("retention.replenishment_plans", rows,
                  column_names=PLAN_COLUMNS)


def run(client, tenant: str, cfg: dict, now: datetime | None = None) -> dict:
    """Один прогон контура. enabled=false -> НОЛЬ активности (клиент не
    трогается вовсе)."""
    if not cfg.get("enabled"):
        return {"skipped": "disabled"}
    now = now or _now_dt()
    today = now.date()

    attrs = client.query(
        "SELECT sku, eligible, default_days "
        "FROM retention.replenishment_sku_attrs_current WHERE tenant_id = %(t)s",
        parameters={"t": tenant}).result_rows
    eligible = {r[0] for r in attrs if int(r[1] or 0)}
    defaults = {r[0]: int(r[2] or 0) for r in attrs}
    if not eligible:
        return {"skipped": "no_eligible_skus"}

    baselines = {(r[0], r[1]): (float(r[2] or 0), int(r[3] or 0))
                 for r in client.query(
        "SELECT identity_id, sku, baseline_days, cycles_count "
        "FROM retention.consumption_baselines_current WHERE tenant_id = %(t)s",
        parameters={"t": tenant}).result_rows}

    plans = [{"plan_id": r[0], "identity_id": r[1], "sku": r[2],
              "order_ref": r[3], "status": r[4], "started_at": _parse_ts(r[5]),
              "predicted_days": int(r[6] or 0), "extension_days": int(r[7] or 0),
              "finished_at": None, "finish_reason": ""}
             for r in client.query(
        "SELECT plan_id, identity_id, sku, order_ref, status, started_at, "
        "predicted_days, extension_days "
        "FROM retention.replenishment_plans_current WHERE tenant_id = %(t)s",
        parameters={"t": tenant}).result_rows]

    orders = _load_orders(client, tenant, cfg.get("plan_source_events"))
    orders_by_pair: dict[tuple, list] = {}
    product_names: dict[str, str] = {}
    for order in orders:
        for item in order["items"]:
            orders_by_pair.setdefault(
                (order["identity_id"], item["sku"]), []).append(
                (order["ts"], order["order_ref"]))
            if item["name"]:
                product_names[item["sku"]] = item["name"]

    confirms = _load_response_events(client, tenant, EVT_CONFIRMED)
    confirms_by_plan: dict[str, list] = {}
    confirms_by_pair: dict[tuple, list] = {}
    for ev in confirms:
        if ev["plan_id"]:
            confirms_by_plan.setdefault(ev["plan_id"], []).append(ev["ts"])
        elif ev["sku"]:
            confirms_by_pair.setdefault(
                (ev["identity_id"], ev["sku"]), []).append(ev["ts"])
    still_by_pair: dict[tuple, list] = {}
    plan_sku = {p["plan_id"]: (p["identity_id"], p["sku"]) for p in plans}
    for ev in _load_response_events(client, tenant, EVT_STILL_HAVE):
        pair = plan_sku.get(ev["plan_id"]) if ev["plan_id"] else None
        pair = pair or ((ev["identity_id"], ev["sku"]) if ev["sku"] else None)
        if pair:
            still_by_pair.setdefault(pair, []).append(ev["ts"])
    optout_pairs = set()
    for ev in _load_response_events(client, tenant, EVT_OPTOUT):
        pair = plan_sku.get(ev["plan_id"]) if ev["plan_id"] else None
        pair = pair or ((ev["identity_id"], ev["sku"]) if ev["sku"] else None)
        if pair:
            optout_pairs.add(pair)

    # 1. ответы двигают существующие циклы (реордер/подтверждение/optout/+7д)
    updates, base_updates = advance_plans(
        plans, orders_by_pair, confirms_by_plan, confirms_by_pair,
        still_by_pair, optout_pairs, baselines, now,
        vertical=cfg.get("vertical") or "ecom")
    _save_plans(client, tenant, updates, now)
    if base_updates:
        now_s = _fmt(now)
        client.insert(
            "retention.consumption_baselines",
            [[tenant, b["identity_id"], b["sku"], b["baseline_days"],
              b["last_cycle_days"], b["cycles_count"], now_s]
             for b in base_updates],
            column_names=BASELINE_COLUMNS)
        for b in base_updates:
            baselines[(b["identity_id"], b["sku"])] = (
                b["baseline_days"], b["cycles_count"])

    # состояние после ответов - для создания и дозревания
    by_id = {p["plan_id"]: p for p in plans}
    for upd in updates:
        by_id[upd["plan_id"]] = upd
    plans = list(by_id.values())
    active_pairs = {(p["identity_id"], p["sku"]) for p in plans
                    if p["status"] in ("ACTIVE", "QUEUED")}

    # 2. новые планы из заказов
    created = build_plans(tenant, orders, eligible, baselines,
                          sku_medians(baselines), defaults, active_pairs,
                          set(by_id), optout_pairs)
    _save_plans(client, tenant, created, now)
    plans += created

    # 3. дозревание -> события replenishment_due в шину
    last_due_by_plan = {}
    week_counts: dict[str, int] = {}
    for r in client.query(
        "SELECT JSONExtractString(meta, 'plan_id') AS plan, max(ts), "
        "countIf(ts >= now() - INTERVAL 7 DAY) "
        "FROM retention.saas_events "
        "WHERE tenant_id = %(t)s AND event_type = %(e)s AND plan != '' "
        "GROUP BY plan",
            parameters={"t": tenant, "e": EVT_DUE}).result_rows:
        last_due_by_plan[r[0]] = _parse_ts(r[1]).date()
    for r in client.query(
        "SELECT JSONExtractString(meta, 'identity_id') AS ident, count() "
        "FROM retention.saas_events "
        "WHERE tenant_id = %(t)s AND event_type = %(e)s AND ident != '' "
        "AND ts >= now() - INTERVAL 7 DAY GROUP BY ident",
            parameters={"t": tenant, "e": EVT_DUE}).result_rows:
        week_counts[r[0]] = int(r[1])

    due = select_due(plans, today, cfg["lead_days"], last_due_by_plan,
                     week_counts, cfg["max_per_customer_week"])
    contacts = {r[0]: (str(r[1] or ""), str(r[2] or "")) for r in client.query(
        "SELECT identity_id, client_user_id, email_hash "
        "FROM retention.identities_current WHERE tenant_id = %(t)s",
        parameters={"t": tenant}).result_rows}
    events = []
    for plan in due:
        cuid, email_hash = contacts.get(plan["identity_id"], ("", ""))
        if not cuid and not email_hash:
            continue                       # событию не к кому резолвиться
        code = reorder_code(tenant, plan["plan_id"])
        meta = {"plan_id": plan["plan_id"], "identity_id": plan["identity_id"],
                "sku": plan["sku"],
                "product": product_names.get(plan["sku"]) or plan["sku"],
                "reorder_code": code,
                "reorder_url": reorder_url(cfg["reorder_url_template"],
                                           plan["sku"], code)}
        events.append([
            tenant, f"repl_due_{plan['plan_id']}_{today.isoformat()}", EVT_DUE,
            _fmt(now), "replenishment", cuid, email_hash,
            json.dumps(meta, ensure_ascii=False, separators=(",", ":"))])
    if events:
        client.insert("retention.saas_events", events,
                      column_names=EVENT_COLUMNS)

    return {"plans_created": len(created), "plans_updated": len(updates),
            "baselines": len(base_updates), "due": len(events)}


def main() -> None:
    import clickhouse_connect
    from saas_senders import load_tenant_channels

    tenant = os.environ.get("TENANT_ID", "").strip()
    if not tenant:
        raise SystemExit("нужен TENANT_ID: джоб работает в пространстве клиента")
    cfg = replenishment_config(load_tenant_channels(tenant))
    if not cfg["enabled"]:
        # выключено = ноль активности; к ClickHouse даже не подключаемся
        print(f"[replenishment] tenant={tenant} disabled - пропуск", flush=True)
        return

    client = clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"),
    )
    stats = run(client, tenant, cfg)
    print(f"[replenishment] tenant={tenant} "
          + " ".join(f"{k}={v}" for k, v in stats.items()), flush=True)


if __name__ == "__main__":
    main()
