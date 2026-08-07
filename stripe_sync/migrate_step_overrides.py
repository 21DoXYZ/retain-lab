"""Разовая миграция: правки шагов -> индексы новой структуры кампаний.

ЗАЧЕМ. Правки текстов и привязки офферов хранятся по (campaign_id, step_idx).
Две перестройки каркаса (ретайминг + вставка inapp-шагов) сдвинули индексы, и
правки тенантов молча съехали: привязка оффера попадала в email-шаг (merge её
защитно игнорировал - оффер оставался НЕ привязан), а текст письма ложился на
шаг-оффер.

ЯВНАЯ ТАБЛИЦА, А НЕ УНИВЕРСАЛЬНОЕ ПРАВИЛО. Первая версия переносила «тексты
по порядку на email-шаги» - и сломала K3, где правка «0» была текстом
БАННЕРА, а не письма: отличить их по содержимому нельзя (обе несут только
subject/body). Знание, каким был старый каркас, есть только у автора
перестройки - оно и записано здесь таблицей.

Каждая запись применяется ТОЛЬКО если тип правки совпадает с ожиданием
('bind' - правка с offer_id, 'text' - без), а целевой шаг - с типом действия.
Поэтому повторный запуск ничего не портит: у мигрированных ключей типы уже
не совпадают с ожиданиями таблицы.

Запуск: python migrate_step_overrides.py [--dry]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# campaign_tick не импортируем: он живёт только в плоском мире джобов, а
# миграцию запускает и борд (у него /secrets на запись). Путь к каркасу
# считается от самого файла - он лежит рядом.
CAMPAIGNS_PATH = Path(__file__).resolve().parent / "saas_campaigns.json"

try:
    from overrides import OVERRIDES_FILE
except ImportError:
    from stripe_sync.overrides import OVERRIDES_FILE  # type: ignore

# (старый индекс, тип правки) -> новый индекс. Старый каркас: K1/K2/K5 =
# email,offer,email; K4 = offer,email,email; K6 = email,offer,email;
# K3 = inapp,email,email,email (не менялся в голове - записей нет).
TRANSITION = {
    "K1_activation": {("0", "text"): 1, ("1", "bind"): 3, ("2", "text"): 2},
    "K2_trial_conversion": {("0", "text"): 1, ("1", "bind"): 2, ("2", "text"): 3},
    "K4_save": {("0", "bind"): 2, ("1", "text"): 1, ("2", "text"): 3},
    "K5_upgrade": {("0", "text"): 1, ("1", "bind"): 2, ("2", "text"): 3},
    # старый текст «аккаунт и история целы» - это ПОСЛЕДНЕЕ слово: на д90
    "K6_winback": {("0", "text"): 0, ("1", "bind"): 2, ("2", "text"): 3},
}

EXPECTED_ACTION = {"bind": ("offer",), "text": ("email", "message", "inapp")}


def _kind(patch: dict) -> str:
    return "bind" if patch.get("offer_id") is not None else "text"


def remap_campaign(cid: str, steps_conf: list, overrides: dict) -> tuple[dict, list]:
    """Правки одной кампании -> новые индексы по таблице. (result, notes)."""
    table = TRANSITION.get(cid) or {}
    out, notes = {}, []
    for old_idx in sorted(overrides, key=lambda k: int(k)):
        patch = overrides[old_idx]
        new_idx = table.get((str(old_idx), _kind(patch)))
        if new_idx is None:
            out[str(old_idx)] = patch          # записи нет - правка на месте
            continue
        if not (0 <= new_idx < len(steps_conf)) or \
                steps_conf[new_idx].get("action") not in EXPECTED_ACTION[_kind(patch)]:
            notes.append(f"{_kind(patch)} {old_idx} отброшена: целевой шаг не подходит")
            continue
        if str(new_idx) in out:
            notes.append(f"{_kind(patch)} {old_idx} отброшена: место {new_idx} занято")
            continue
        out[str(new_idx)] = patch
        if str(new_idx) != str(old_idx):
            notes.append(f"{_kind(patch)} {old_idx} -> {new_idx}")
    return out, notes


def migrate(overrides_path: str = "", campaigns_path: str = "",
            dry: bool = False) -> dict:
    ov_path = overrides_path or OVERRIDES_FILE
    conf = json.loads((campaigns_path and open(campaigns_path).read())
                      or CAMPAIGNS_PATH.read_text())
    data = json.load(open(ov_path))
    steps_by_cid = {c["campaign_id"]: c["steps"]
                    for c in conf["_default"]["campaigns"]}

    changed = {}
    for tenant, block in data.items():
        camps = (block or {}).get("campaigns") or {}
        for cid, camp_ov in camps.items():
            steps_ov = camp_ov.get("steps") or {}
            if not steps_ov or cid not in steps_by_cid:
                continue
            new_steps, notes = remap_campaign(cid, steps_by_cid[cid], steps_ov)
            if new_steps != steps_ov:
                camp_ov["steps"] = new_steps
                changed[f"{tenant}/{cid}"] = notes

    if changed and not dry:
        json.dump(data, open(ov_path, "w"), ensure_ascii=False, indent=2)
    for key, notes in changed.items():
        print(f"[migrate] {key}: " + "; ".join(notes), flush=True)
    if not changed:
        print("[migrate] правки уже на своих местах", flush=True)
    return changed


if __name__ == "__main__":
    migrate(dry="--dry" in sys.argv)
