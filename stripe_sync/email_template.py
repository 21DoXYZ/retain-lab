"""Вёрстка письма: одна колонка, одна мысль, одно действие.

ПОЧЕМУ ТАК, А НЕ КРАСИВЕЕ. Письмо удержания читают в почтовом клиенте, часто
с телефона и часто с отключёнными картинками. Всё, что усложняет вёрстку -
колонки, фоновые изображения, внешние шрифты и стили - ломается в Outlook,
режется фильтрами и удлиняет загрузку. Поэтому: таблицы, инлайновые стили,
никаких внешних ресурсов, текстовая версия всегда рядом.

ЧТО ОБЯЗАТЕЛЬНО ЕСТЬ В КАЖДОМ ПИСЬМЕ:
  • preheader - строка, которую почтовик показывает рядом с темой; без неё
    в списке писем видно начало текста, и оно почти всегда неудачное;
  • заголовок - та же мысль, что в теме, чтобы человек не перечитывал;
  • одно действие кнопкой - ссылку в теле люди пропускают;
  • подпись продукта и отписка - без них письмо выглядит как спам.
"""

from __future__ import annotations

import html as _html
import re

LINK_RE = re.compile(r"https?://[^\s<>\"']+")
DEFAULT_BRAND_COLOR = "#101828"
MAX_PREHEADER = 110


def _safe_color(raw: str) -> str:
    """Цвет бренда клиента, если он разобран с сайта. Иначе тёмно-серый."""
    value = str(raw or "").strip()
    return value if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else DEFAULT_BRAND_COLOR


def split_cta(body: str) -> tuple[str, str]:
    """(текст без ссылки-кнопки, ссылка). Ссылку показываем кнопкой.

    Кнопкой становится ссылка в конце ЛЮБОГО абзаца (не только всего письма):
    после контентного прохода ссылки часто стоят в конце первого абзаца, а
    дальше идёт «ответь - читает человек». Ссылка в середине предложения
    остаётся текстом - она там по смыслу. Из нескольких кандидатов берём
    последний: он ближе к действию.
    """
    text = (body or "").strip()
    lines = text.split("\n")
    pick = None                       # (номер строки, match)
    for li, line in enumerate(lines):
        for m in LINK_RE.finditer(line):
            if line[m.end():].strip(" .!)»\"'") == "":
                pick = (li, m)
    if not pick:
        return text, ""
    li, m = pick
    lines[li] = lines[li][:m.start()].rstrip(" :-–—")
    cleaned = "\n".join(lines).strip()
    return cleaned, m.group(0)


def preheader(text: str, limit: int = MAX_PREHEADER) -> str:
    """Строка предпросмотра: первое предложение без ссылок."""
    clean = LINK_RE.sub("", (text or "").replace("\n", " ")).strip()
    clean = re.sub(r"\s{2,}", " ", clean)
    return clean[:limit].rstrip(" ,;:-")


def _safe_logo(raw: str) -> str:
    """Логотип - только https-картинка. javascript:/data: в письме не место."""
    url = str(raw or "").strip()
    return url if url.lower().startswith("https://") else ""


def render(subject: str, body: str, unsubscribe: str, brand: str = "",
           cta_label: str = "", brand_color: str = "", logo_url: str = "") -> str:
    """HTML письма. Все стили инлайном - иначе почтовики их выбрасывают."""
    color = _safe_color(brand_color)
    logo = _safe_logo(logo_url)
    text, link = split_cta(body)
    label = (cta_label or "").strip() or "Open"
    esc = _html.escape(text)
    esc = LINK_RE.sub(lambda m: f'<a href="{m.group(0)}" style="color:{color}">'
                                f'{m.group(0)}</a>', esc)
    paragraphs = "".join(
        f'<p style="margin:0 0 14px;line-height:1.6">{p}</p>'
        for p in esc.split("\n") if p.strip())

    button = ""
    if link:
        button = (
            '<table role="presentation" cellpadding="0" cellspacing="0" '
            'style="margin:22px 0 6px"><tr><td '
            f'style="background:{color};border-radius:8px">'
            f'<a href="{link}" style="display:inline-block;padding:12px 22px;'
            'font-weight:600;font-size:15px;color:#ffffff;text-decoration:none">'
            f'{_html.escape(label)}</a></td></tr></table>')

    head = _html.escape(brand) if brand else ""
    title = _html.escape((subject or "").strip())
    pre = _html.escape(preheader(body))

    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        f'<title>{title}</title></head>'
        '<body style="margin:0;padding:0;background:#f6f7f9">'
        # строка предпросмотра: видна в списке писем, но не в самом письме
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{pre}</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#f6f7f9;padding:24px 12px"><tr><td align="center">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:520px;background:#ffffff;border-radius:14px;'
        'padding:26px 24px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,'
        'Roboto,Arial,sans-serif;font-size:15px;color:#101828">'
        + (f'<tr><td style="padding-bottom:16px">'
           f'<img src="{logo}" alt="{head}" height="28" '
           f'style="display:block;border:0;max-height:28px"></td></tr>'
           if logo else
           (f'<tr><td style="padding-bottom:14px;font-size:13px;font-weight:600;'
            f'letter-spacing:.2px;color:{color}">{head}</td></tr>' if head else ""))
        + (f'<tr><td style="padding-bottom:12px;font-size:19px;font-weight:700;'
           f'line-height:1.3">{title}</td></tr>' if title else "")
        + f'<tr><td>{paragraphs}{button}</td></tr>'
        '<tr><td style="padding-top:18px;margin-top:8px;border-top:1px solid #eaecf0;'
        'font-size:12px;color:#98a2b3;line-height:1.5">'
        + (f'{head} · ' if head else "")
        + f'<a href="{unsubscribe}" style="color:#98a2b3">Unsubscribe</a>'
        '</td></tr></table></td></tr></table></body></html>'
    )
