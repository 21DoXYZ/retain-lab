"""SaaS-раннер кампаний K1-K5 (Phase 4, v1): стадия -> цепочка -> касания.

Один тик (идемпотентный, крон — Phase 6):
  1. ENROLL — юзеры user_actions в entry_stage кампании, не заходившие в неё
     последние 30 дней; 10% (md5-детерминированный holdout) — контроль: шаги
     не исполняются, конверсия сравнивается в uplift-отчёте.
  2. EXECUTE — у активных enrollment'ов исполняются все шаги, чей срок
     (enrolled_at + delay_h) наступил: email (saas_senders, dry-run дефолт) или
     offer (issue.py: гигиена+лог offers_issued). Контроль двигается по шагам
     молча.
  3. EXIT — стадия сменилась -> exited (атрибуция цели — Phase 6);
     шаги кончились -> done.

Отличие от плана REBUILD (§Phase 4, задокументированное): казино-движок chains/
привязан к casino_player_id UInt32 / player_features — SaaS-цепочки v1 живут в
этом лёгком раннере на общих слоях (user_actions/offers/holdout). Перенос в
automation.* с UI-конструктором — после EN-словаря SPA (остаток Phase 5).

Запуск:  docker compose ... run --rm --no-deps stripe-webhook python campaign_tick.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from executors import ExecConfig
from hygiene import holdout_split
from issue import issue_offer
from saas_senders import EmailConfig, send_email

CAMPAIGNS_PATH = Path(__file__).parent / "saas_campaigns.json"
REENTRY_DAYS = 30


def _now_dt() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


# ── чистая логика (тестируется без CH) ───────────────────────────────────────

def due_steps(steps: list[dict], enrolled_at: datetime, step_idx: int,
              now: datetime) -> list[int]:
    """Индексы шагов, начиная со step_idx, чей срок наступил (подряд)."""
    out = []
    for i in range(step_idx, len(steps)):
        if enrolled_at + timedelta(hours=float(steps[i]["delay_h"])) <= now:
            out.append(i)
        else:
            break
    return out


def next_step_time(steps: list[dict], enrolled_at: datetime, step_idx: int) -> datetime:
    if step_idx >= len(steps):
        return enrolled_at
    return enrolled_at + timedelta(hours=float(steps[step_idx]["delay_h"]))


def exit_status(current_stage: str, entry_stage: str, step_idx: int,
                n_steps: int) -> str | None:
    """None = остаётся active."""
    if current_stage != entry_stage:
        return "exited"
    if step_idx >= n_steps:
        return "done"
    return None


# ── I/O ──────────────────────────────────────────────────────────────────────

def _save(client, tenant: str, camp_id: str, row: dict) -> None:
    now = _fmt(_now_dt())
    client.insert(
        "retention.campaign_enrollments",
        [[tenant, camp_id, row["identity_id"], row["control"], row["entry_stage"],
          row["step_idx"], _fmt(row["next_step_at"]), row["status"],
          _fmt(row["enrolled_at"]), now]],
        column_names=["tenant_id", "campaign_id", "identity_id", "control",
                      "entry_stage", "step_idx", "next_step_at", "status",
                      "enrolled_at", "updated_at"],
    )


def _log_send(client, tenant: str, camp_id: str, identity: str, step_idx: int,
              action: str, detail: str, status: str, reason: str = "") -> None:
    client.insert(
        "retention.campaign_send_log",
        [[tenant, camp_id, identity, step_idx, action, detail, status, reason,
          _fmt(_now_dt())]],
        column_names=["tenant_id", "campaign_id", "identity_id", "step_idx",
                      "action", "detail", "status", "reason", "ts"],
    )


def tick(client, tenant: str) -> dict[str, int]:
    cfgs = json.loads(CAMPAIGNS_PATH.read_text())
    conf = cfgs.get(tenant)
    if not conf:
        raise SystemExit(f"нет кампаний для тенанта {tenant}")
    control_pct = int(conf.get("control_pct", 10))
    email_cfg = EmailConfig.from_env()
    exec_cfg = ExecConfig.from_env()
    now = _now_dt()
    stats = {"enrolled": 0, "control": 0, "steps": 0, "done": 0, "exited": 0}

    stages = {r[0]: (r[1], r[2]) for r in client.query(
        "SELECT identity_id, stage, email_norm FROM retention.user_actions "
        "WHERE tenant_id = %(t)s", parameters={"t": tenant}).result_rows}

    for camp in conf["campaigns"]:
        cid, steps = camp["campaign_id"], camp["steps"]

        enrolled = {r[0]: dict(zip(
            ["identity_id", "control", "entry_stage", "step_idx",
             "next_step_at", "status", "enrolled_at"], r)) for r in client.query(
            """
            SELECT identity_id, control, entry_stage, step_idx, next_step_at,
                   status, enrolled_at
            FROM retention.campaign_enrollments_current
            WHERE tenant_id = %(t)s AND campaign_id = %(c)s
              AND (status = 'active' OR enrolled_at >= now() - INTERVAL %(d)s DAY)
            """, parameters={"t": tenant, "c": cid, "d": REENTRY_DAYS},
        ).result_rows}

        # 1. ENROLL
        for identity, (stage, _email) in stages.items():
            if stage != camp["entry_stage"] or identity in enrolled:
                continue
            control = holdout_split(tenant, cid, identity, control_pct)
            row = {"identity_id": identity, "control": 1 if control else 0,
                   "entry_stage": stage, "step_idx": 0,
                   "next_step_at": next_step_time(steps, now, 0),
                   "status": "active", "enrolled_at": now}
            _save(client, tenant, cid, row)
            enrolled[identity] = row
            stats["enrolled"] += 1
            stats["control"] += 1 if control else 0

        # 2. EXECUTE + 3. EXIT
        for identity, row in enrolled.items():
            if row["status"] != "active":
                continue
            enrolled_at = row["enrolled_at"] if isinstance(row["enrolled_at"], datetime) \
                else datetime.fromisoformat(str(row["enrolled_at"]))
            stage_now, email = stages.get(identity, ("", ""))

            for i in due_steps(steps, enrolled_at, int(row["step_idx"]), now):
                step = steps[i]
                if not row["control"]:
                    if step["action"] == "email":
                        if email:
                            ok, detail = send_email(email, step["subject"], step["body"], email_cfg)
                            _log_send(client, tenant, cid, identity, i, "email",
                                      step["subject"], detail if ok else "rejected",
                                      "" if ok else detail)
                        else:
                            _log_send(client, tenant, cid, identity, i, "email",
                                      step["subject"], "rejected", "no_email")
                    elif step["action"] == "offer":
                        status, reason = issue_offer(
                            client, tenant, identity, step["offer_id"],
                            campaign_id=cid, control_pct=0, cfg=exec_cfg)
                        _log_send(client, tenant, cid, identity, i, "offer",
                                  step["offer_id"], status, reason)
                    stats["steps"] += 1
                row["step_idx"] = i + 1

            status = exit_status(stage_now, row["entry_stage"],
                                 int(row["step_idx"]), len(steps))
            if status:
                row["status"] = status
                stats[status if status in ("done", "exited") else "done"] += 1
            row["next_step_at"] = next_step_time(steps, enrolled_at, int(row["step_idx"]))
            row["enrolled_at"] = enrolled_at
            _save(client, tenant, cid, row)

    return stats


def main() -> None:
    import clickhouse_connect

    tenant = os.environ.get("TENANT_ID", "hubcontent")
    client = clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"),
    )
    stats = tick(client, tenant)
    print(f"[campaigns] tenant={tenant} " +
          " ".join(f"{k}={v}" for k, v in stats.items()))


if __name__ == "__main__":
    main()
