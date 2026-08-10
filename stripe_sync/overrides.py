"""Пользовательские правки кампаний/офферов поверх базового конфига (Phase 4+).

Продуктовая модель v1 - «автопилот под ключ»: СТРУКТУРА цепочек (стадии,
маппинг кампаний, гигиена) - платформенная, в git; а вот ТЕКСТЫ касаний,
тайминг шагов и щедрость офферов клиент правит из CRM. Правки лежат в
runtime-файле (том /secrets, rw у board, ro у saas-ops) и мержатся движком
при каждом тике - деплой не нужен.

Формат overrides.json:
{
  "hubcontent": {
    "campaigns": {"K3_payment_recovery": {"steps": {"1": {"subject": "...",
                  "body": "...", "delay_h": 12}}}},
    "offers": {"O1_tokens_100": {"max_per_user_30d": 1,
               "params": {"tokens": 150}}}
  }
}
"""

from __future__ import annotations

import copy
import json
import os
import tempfile

OVERRIDES_FILE = os.environ.get("CAMPAIGN_OVERRIDES_FILE", "/secrets/overrides.json")

STEP_TEXT_FIELDS = ("subject", "body", "cta_label", "cta_url")
OFFER_TOP_FIELDS = ("title", "max_per_user_30d", "cost_estimate")


def load_all(path: str = "") -> dict:
    try:
        with open(path or OVERRIDES_FILE) as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def load_tenant(tenant_id: str, path: str = "") -> dict:
    return load_all(path).get(tenant_id, {}) or {}


def _atomic_write(data: dict, path: str) -> None:
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".overrides-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def set_campaign_step(tenant_id: str, campaign_id: str, step_idx: int,
                      patch: dict | None, path: str = "") -> dict:
    """patch=None - сбросить правку шага к базовому тексту.

    В patch можно передать src: "generated" (собрал опросник/ИИ) или "manual"
    (правил владелец руками) - это видно на экране кампаний."""
    p = path or OVERRIDES_FILE
    data = load_all(p)
    t = data.setdefault(tenant_id, {})
    camps = t.setdefault("campaigns", {})
    steps = camps.setdefault(campaign_id, {}).setdefault("steps", {})
    key = str(step_idx)
    if patch is None:
        steps.pop(key, None)
        if not steps:
            camps.pop(campaign_id, None)
    else:
        steps[key] = patch
    _atomic_write(data, p)
    return t


def set_offer(tenant_id: str, offer_id: str, patch: dict | None,
              path: str = "") -> dict:
    p = path or OVERRIDES_FILE
    data = load_all(p)
    t = data.setdefault(tenant_id, {})
    offers = t.setdefault("offers", {})
    if patch is None:
        offers.pop(offer_id, None)
    else:
        offers[offer_id] = patch
    _atomic_write(data, p)
    return t


# ── Чистые мержи (их зовёт движок и GET-ручки; тестируются без файлов) ───────

def merge_campaign_conf(conf: dict, ov: dict) -> dict:
    """Возвращает копию конфига кампаний с наложенными правками шагов.
    Правятся только тексты и delay_h; структура шагов неизменна. У правленого
    шага появляется служебный флаг _edited (для бейджа в UI).

    Плюс РУЧНЫЕ кампании (custom_campaigns): владелец собрал в CRM кампанию
    на отфильтрованный сегмент. Аудитория зачислена снапшотом при запуске
    (manual_audience=true - тик их не дозачисляет и не выкидывает по смене
    стадии, только исполняет шаги). Архивные не попадают движку вовсе."""
    out = copy.deepcopy(conf)
    base_ids = {c.get("campaign_id") for c in out.get("campaigns", [])}
    for camp in (ov or {}).get("custom_campaigns", []) or []:
        cid = camp.get("campaign_id")
        if not cid or cid in base_ids or camp.get("status") == "archived":
            continue
        c = copy.deepcopy(camp)
        c["_custom"] = True
        c["manual_audience"] = True
        c.setdefault("entry_stage", "MANUAL")   # ни у кого нет такой стадии -
        c.setdefault("steps", [])               # автозачисление не сработает
        out.setdefault("campaigns", []).append(c)
    by_camp = (ov or {}).get("campaigns", {})
    for camp in out.get("campaigns", []):
        steps_ov = (by_camp.get(camp["campaign_id"]) or {}).get("steps", {})
        for idx_s, patch in steps_ov.items():
            try:
                step = camp["steps"][int(idx_s)]
            except (IndexError, ValueError):
                continue
            for f in STEP_TEXT_FIELDS:
                if patch.get(f) is not None:
                    step[f] = str(patch[f])
            if patch.get("delay_h") is not None:
                step["delay_h"] = float(patch["delay_h"])
            if patch.get("offer_id") is not None and step.get("action") == "offer":
                step["offer_id"] = str(patch["offer_id"])
            step["_edited"] = True
            # откуда текст: сборка по опроснику или ручная правка владельца.
            # Без этого экран кампаний не может честно сказать, чей это текст.
            step["_src"] = str(patch.get("src") or "manual")
    return out


def apply_ab_winners(conf: dict, winners: dict) -> dict:
    """Наложить победителей A/B (knowledge kind='ab_winners') на конфиг.

    Победивший текст замещает шаг, сплит шага гаснет (variants_off), источник
    'ab' виден бейджем. Зовётся ПОСЛЕ merge_campaign_conf: ручная правка
    владельца поверх победителя легитимна - но тогда его правка и победит."""
    if not winners:
        return conf
    out = copy.deepcopy(conf)
    for camp in out.get("campaigns", []):
        for i, step in enumerate(camp.get("steps", [])):
            w = winners.get(f"{camp['campaign_id']}#{i}")
            if not w or step.get("_edited"):
                continue
            for f, v in (w.get("patch") or {}).items():
                if f in STEP_TEXT_FIELDS:
                    step[f] = str(v)
            step["variants_off"] = True
            step["_edited"] = True
            step["_src"] = "ab"
    return out


def merge_catalog(catalog: dict, ov: dict) -> dict:
    """Копия каталога офферов с правками щедрости/лимитов. params мержатся
    по ключам (новые ключи не добавляются - исполнители ждут свой контракт).
    Плюс пользовательские офферы (custom_offers - созданы из CRM с нуля,
    для клиентов без git-пресета) и отключённые (disabled_offers)."""
    out = copy.deepcopy(catalog)
    ov = ov or {}
    by_offer = ov.get("offers", {})
    for offer in out.get("offers", []):
        patch = by_offer.get(offer["offer_id"])
        if not patch:
            continue
        for f in OFFER_TOP_FIELDS:
            if patch.get(f) is not None:
                offer[f] = patch[f]
        p_ov = patch.get("params") or {}
        for k, v in p_ov.items():
            if k in (offer.get("params") or {}) and v is not None:
                offer["params"][k] = v
        offer["_edited"] = True

    base_ids = {o["offer_id"] for o in out.get("offers", [])}
    for extra in ov.get("custom_offers", []) or []:
        if extra.get("offer_id") and extra["offer_id"] not in base_ids:
            e = copy.deepcopy(extra)
            e["_custom"] = True
            out.setdefault("offers", []).append(e)

    disabled = set(ov.get("disabled_offers", []) or [])
    if disabled:
        for o in out.get("offers", []):
            if o["offer_id"] in disabled:
                o["_disabled"] = True
    return out


def active_offers(catalog: dict) -> list:
    """Офферы, доступные выдаче (issue/campaign_tick): без отключённых."""
    return [o for o in catalog.get("offers", []) if not o.get("_disabled")]


def add_custom_campaign(tenant_id: str, camp: dict, path: str = "") -> None:
    """Ручная кампания владельца (уникальна по campaign_id, замена по id)."""
    p = path or OVERRIDES_FILE
    data = load_all(p)
    t = data.setdefault(tenant_id, {})
    lst = t.setdefault("custom_campaigns", [])
    lst[:] = [c for c in lst if c.get("campaign_id") != camp.get("campaign_id")]
    lst.append(camp)
    _atomic_write(data, p)


def set_custom_campaign_status(tenant_id: str, campaign_id: str, status: str,
                               path: str = "") -> bool:
    """active | paused | archived. False - кампании нет."""
    p = path or OVERRIDES_FILE
    data = load_all(p)
    lst = (data.get(tenant_id) or {}).get("custom_campaigns") or []
    for c in lst:
        if c.get("campaign_id") == campaign_id:
            c["status"] = status
            _atomic_write(data, p)
            return True
    return False


def add_custom_offer(tenant_id: str, offer: dict, path: str = "") -> None:
    p = path or OVERRIDES_FILE
    data = load_all(p)
    t = data.setdefault(tenant_id, {})
    lst = t.setdefault("custom_offers", [])
    lst[:] = [o for o in lst if o.get("offer_id") != offer.get("offer_id")]
    lst.append(offer)
    _atomic_write(data, p)


def replace_auto_offers(tenant_id: str, offers: list, prefixes: tuple = ("A_", "AI_"),
                        path: str = "") -> None:
    """Идемпотентная пересборка авто-каталога: снести прежние A_/AI_ офферы
    (и их disabled-флаги), записать новый набор. Ручные C_ не трогаются."""
    p = path or OVERRIDES_FILE
    data = load_all(p)
    t = data.setdefault(tenant_id, {})
    keep = [o for o in (t.get("custom_offers") or [])
            if not str(o.get("offer_id", "")).startswith(prefixes)]
    t["custom_offers"] = keep + list(offers)
    t["disabled_offers"] = [x for x in (t.get("disabled_offers") or [])
                            if not str(x).startswith(prefixes)]
    _atomic_write(data, p)


def set_offer_disabled(tenant_id: str, offer_id: str, disabled: bool,
                       path: str = "") -> None:
    p = path or OVERRIDES_FILE
    data = load_all(p)
    t = data.setdefault(tenant_id, {})
    cur = set(t.get("disabled_offers", []) or [])
    if disabled:
        cur.add(offer_id)
    else:
        cur.discard(offer_id)
    # свой (custom) оффер при отключении просто удаляем совсем
    if disabled:
        customs = t.get("custom_offers", []) or []
        if any(o.get("offer_id") == offer_id for o in customs):
            t["custom_offers"] = [o for o in customs if o.get("offer_id") != offer_id]
            cur.discard(offer_id)
    t["disabled_offers"] = sorted(cur)
    _atomic_write(data, p)
