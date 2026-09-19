"""Ответы юзеров из почтового ящика тенанта (Google/IMAP).

Владелец выбрал путь «через Google» вместо Resend inbound (2026-09-16):
рассылки уходят от care@..., ответы падают в тот же Google-ящик, и без
этого джоба система их не видит - хотя каждое письмо просит «просто
ответь». Раз в 5 минут читаем ящик по IMAP (BODY.PEEK - письма НЕ
помечаются прочитанными, ящик команды не трогаем) и забираем письма от
известных нам юзеров:

  • письмо пишется в retention.email_replies (дедуп по Message-ID);
  • все живые цепочки ответившего останавливаются - после ответа человека
    дожимает человек, а не робот;
  • на Home ответ виден первой строкой («Требуют тебя»).

Конфиг тенанта (secrets/tenants.json):
  "imap_user": "care@hubcontent.ai",
  "imap_app_password": "<16 букв app password>",
  "imap_host": "imap.gmail.com"  (необязательно, это дефолт)

Письма от НЕизвестных адресов не трогаем вовсе: это обычная почта команды,
нам она не принадлежит.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import os
import re
from datetime import datetime, timedelta, timezone

LOOKBACK_DAYS = 3          # свежее окно: старые треды не ворошим
MAX_BODY = 4000

_OWN_SENDERS = re.compile(r"@(reply\.)?hubcontent\.ai$|@retivo\.digital$", re.I)


def _decode(value: str) -> str:
    """RFC2047-заголовок -> человеческая строка."""
    out = []
    for part, enc in email.header.decode_header(value or ""):
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", "replace"))
        else:
            out.append(part)
    return "".join(out)


def _plain_text(msg: email.message.Message) -> str:
    """text/plain из письма; нет - грубо ободрать html."""
    def _one(part) -> str:
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, "replace")

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" \
                    and "attachment" not in str(part.get("Content-Disposition") or ""):
                return _one(part)
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return re.sub(r"<[^>]+>", " ", _one(part))
        return ""
    if msg.get_content_type() == "text/html":
        return re.sub(r"<[^>]+>", " ", _one(msg))
    return _one(msg)


def _strip_quotes(text: str) -> str:
    """Убрать процитированный хвост: реплай-маркеры и '>'-строки."""
    lines = []
    for ln in (text or "").splitlines():
        low = ln.strip().lower()
        if ln.strip().startswith(">"):
            continue
        # "On Tue, ... wrote:" / "16.09.2026 ... написал(а):" - дальше цитата
        if re.match(r"^(on .{5,80} wrote:|\d{1,2}[./]\d{1,2}[./]\d{2,4}.{0,60}"
                    r"(написал|wrote))", low):
            break
        lines.append(ln)
    return "\n".join(lines).strip()


def parse_message(raw: bytes) -> dict:
    """Сырое IMAP-письмо -> {from_email, subject, text, message_id}."""
    msg = email.message_from_bytes(raw)
    _name, addr = email.utils.parseaddr(str(msg.get("From") or ""))
    return {
        "from_email": (addr or "").strip().lower(),
        "subject": _decode(str(msg.get("Subject") or ""))[:200],
        "text": _strip_quotes(_plain_text(msg))[:MAX_BODY],
        "message_id": str(msg.get("Message-ID") or "").strip()[:200],
    }


def is_own(addr: str) -> bool:
    """Наши же адреса (рассылка, алерты) - не «ответ юзера»."""
    return bool(_OWN_SENDERS.search(addr or ""))


def _ch():
    import clickhouse_connect
    return clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"))


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _store_reply(ch, tenant: str, inb: dict) -> int:
    """email_replies + стоп всех живых цепочек ответившего. -> цепочек."""
    rows = ch.query(
        "SELECT identity_id FROM retention.identities "
        "WHERE tenant_id = %(t)s AND email_norm = %(e)s LIMIT 1",
        parameters={"t": tenant, "e": inb["from_email"]}).result_rows
    identity = str(rows[0][0]) if rows else ""
    now = _now()
    ch.insert(
        "retention.email_replies",
        [[tenant, inb["from_email"], identity, inb["subject"],
          inb["text"], inb["message_id"], now]],
        column_names=["tenant_id", "from_email", "identity_id", "subject",
                      "body", "provider_id", "ts"])
    if not identity:
        return 0
    active = ch.query(
        "SELECT campaign_id, control, entry_stage, step_idx, next_step_at, "
        "enrolled_at FROM retention.campaign_enrollments_current "
        "WHERE tenant_id = %(t)s AND identity_id = %(i)s AND status = 'active'",
        parameters={"t": tenant, "i": identity}).result_rows
    if active:
        ch.insert(
            "retention.campaign_enrollments",
            [[tenant, str(r[0]), identity, int(r[1]), str(r[2]), int(r[3]),
              r[4], "exited", r[5], now] for r in active],
            column_names=["tenant_id", "campaign_id", "identity_id", "control",
                          "entry_stage", "step_idx", "next_step_at", "status",
                          "enrolled_at", "updated_at"])
    return len(active)


def _seen_ids(ch, tenant: str) -> set[str]:
    return {str(r[0]) for r in ch.query(
        "SELECT DISTINCT provider_id FROM retention.email_replies "
        "WHERE tenant_id = %(t)s AND ts >= now() - INTERVAL 14 DAY",
        parameters={"t": tenant}).result_rows}


def poll_tenant(ch, tenant: str, conf: dict) -> None:
    user = str(conf.get("imap_user") or "").strip()
    pwd = str(conf.get("imap_app_password") or "").strip()
    if not user or not pwd:
        return
    host = str(conf.get("imap_host") or "imap.gmail.com")
    since = (datetime.now(tz=timezone.utc)
             - timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")

    box = imaplib.IMAP4_SSL(host)
    try:
        box.login(user, pwd)
        box.select("INBOX", readonly=True)
        _st, data = box.search(None, f'(SINCE "{since}")')
        uids = (data[0] or b"").split()
        if not uids:
            return
        seen = _seen_ids(ch, tenant)
        # адреса наших юзеров разом: дешевле одного запроса на письмо
        known = {str(r[0]) for r in ch.query(
            "SELECT DISTINCT email_norm FROM retention.identities "
            "WHERE tenant_id = %(t)s AND email_norm != ''",
            parameters={"t": tenant}).result_rows}
        got, stopped = 0, 0
        for uid in uids[-500:]:
            # Двухфазно: сперва только заголовки (лёгкие), полное тело - лишь
            # для писем наших юзеров. PEEK: флаги не трогаем, ящик живой.
            _st, hdr = box.fetch(
                uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)])")
            raw_h = next((p[1] for p in hdr if isinstance(p, tuple)), None)
            if not raw_h:
                continue
            head = parse_message(raw_h)
            if (not head["from_email"] or is_own(head["from_email"])
                    or head["from_email"] not in known
                    or (head["message_id"] and head["message_id"] in seen)):
                continue
            _st, msg_data = box.fetch(uid, "(BODY.PEEK[])")
            raw = next((p[1] for p in msg_data if isinstance(p, tuple)), None)
            if not raw:
                continue
            inb = parse_message(raw)
            stopped += _store_reply(ch, tenant, inb)
            seen.add(inb["message_id"])
            got += 1
        if got:
            print(f"[mail] {tenant}: {got} ответов, цепочек остановлено "
                  f"{stopped}", flush=True)
    finally:
        try:
            box.logout()
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    from channels_admin import load_tenants
    ch = _ch()
    ok, failed = 0, 0
    for tenant, conf in load_tenants().items():
        if not str((conf or {}).get("imap_app_password") or "").strip():
            continue                       # ящик не подключён - не считается
        try:
            poll_tenant(ch, tenant, conf or {})
            ok += 1
        except Exception as exc:  # noqa: BLE001 - один ящик не валит остальные
            failed += 1
            print(f"[mail] {tenant}: poll failed: {type(exc).__name__}: {exc}",
                  flush=True)
    if failed and not ok:
        # все подключённые ящики упали (протух пароль и т.п.) - выходим
        # с ошибкой, чтобы ops_loop записал pipeline_runs error и сторож
        # разбудил владельца; иначе ответы копились бы в ящике молча
        raise SystemExit(1)


if __name__ == "__main__":
    main()
