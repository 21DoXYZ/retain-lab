"""Email-канал SaaS-кампаний: Resend API либо dry-run (дефолт, как senders.py).

DRY_RUN (SIGNALS_DRY_RUN=1 по умолчанию): письмо печатается, в сеть не уходит.
Реальный режим: RESEND_API_KEY + EMAIL_FROM (домен с DKIM/SPF — warm-up по
плану Phase 4). Плейсхолдеры {{...}} рендерятся из контекста; неизвестные
остаются как есть (видно в логе, что не хватает).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

_TIMEOUT = 30


@dataclass(frozen=True)
class EmailConfig:
    dry_run: bool = True
    resend_api_key: str = ""
    email_from: str = ""
    app_url: str = ""
    card_update_url: str = ""

    @classmethod
    def from_env(cls) -> "EmailConfig":
        return cls(
            dry_run=os.environ.get("SIGNALS_DRY_RUN", "1") not in ("0", "false", "False", ""),
            resend_api_key=os.environ.get("RESEND_API_KEY", "").strip(),
            email_from=os.environ.get("EMAIL_FROM", "").strip(),
            app_url=os.environ.get("APP_URL", "https://app.example.test").strip(),
            card_update_url=os.environ.get("BILLING_PORTAL_URL",
                                           "https://billing.example.test/portal").strip(),
        )


def render(template: str, ctx: dict) -> str:
    return re.sub(r"\{\{(\w+)\}\}",
                  lambda m: str(ctx.get(m.group(1), m.group(0))), template)


def send_email(to: str, subject: str, body: str, cfg: EmailConfig,
               ctx: dict | None = None) -> tuple[bool, str]:
    context = {"app_url": cfg.app_url, "card_update_url": cfg.card_update_url}
    context.update(ctx or {})
    subject_r, body_r = render(subject, context), render(body, context)

    if cfg.dry_run:
        print(f"[email dry_run] to={to} subj={subject_r!r}", flush=True)
        return True, "dry_run"
    if not cfg.resend_api_key or not cfg.email_from:
        return False, "email_not_configured"

    payload = json.dumps({"from": cfg.email_from, "to": [to],
                          "subject": subject_r, "text": body_r}).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg.resend_api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return (200 <= resp.status < 300), f"http_{resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except Exception as exc:
        return False, type(exc).__name__
