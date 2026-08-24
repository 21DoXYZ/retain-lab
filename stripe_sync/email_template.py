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


def signature_html(sig: dict, color: str) -> str:
    """Корпоративная подпись как у живого человека в Gmail: фото (или круг с
    инициалами), имя жирным, роль, компания-ссылка. Всё инлайном, одна
    строка таблицы - переживает любой почтовик."""
    name = _html.escape(str(sig.get("name") or "").strip())
    if not name:
        return ""
    role = _html.escape(str(sig.get("role") or "").strip())
    company = _html.escape(str(sig.get("company") or "").strip())
    site = str(sig.get("site") or "").strip()
    avatar = _safe_logo(str(sig.get("avatar_url") or ""))

    if avatar:
        photo = (f'<img src="{avatar}" width="44" height="44" alt="{name}" '
                 'style="display:block;border-radius:50%;border:0">')
    else:
        initials = "".join(w[0] for w in name.split()[:2]).upper()
        photo = (f'<div style="width:44px;height:44px;border-radius:50%;'
                 f'background:{color};color:#ffffff;font-weight:700;'
                 'font-size:17px;line-height:44px;text-align:center">'
                 f'{initials}</div>')

    company_html = company
    if company and site.lower().startswith("https://"):
        company_html = (f'<a href="{site}" style="color:#667085;'
                        f'text-decoration:none">{company}</a>')
    line2 = " · ".join(x for x in (role, company_html) if x)
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'style="margin-top:26px"><tr>'
        f'<td style="vertical-align:middle;padding-right:12px">{photo}</td>'
        '<td style="vertical-align:middle;font-size:14px;line-height:1.45">'
        f'<div style="font-weight:600;color:#101828">{name}</div>'
        + (f'<div style="font-size:13px;color:#667085">{line2}</div>' if line2 else "")
        + '</td></tr></table>')


def render(subject: str, body: str, unsubscribe: str, brand: str = "",
           cta_label: str = "", brand_color: str = "", logo_url: str = "",
           signature: dict | None = None) -> str:
    """HTML письма В СТИЛЕ ЛИЧНОГО: белый фон без «карточки», без шапки-бренда
    и без дубля темы заголовком - человек так не пишет, а Gmail за
    нотификационную обвязку ссылает во вкладку Updates. Одна скромная кнопка
    (если в тексте есть ссылка-действие), корпоративная подпись с фото,
    тихая отписка. Все стили инлайном - иначе почтовики их выбрасывают."""
    color = _safe_color(brand_color)
    text, link = split_cta(body)
    label = (cta_label or "").strip() or "Open"
    esc = _html.escape(text)
    esc = LINK_RE.sub(lambda m: f'<a href="{m.group(0)}" style="color:{color}">'
                                f'{m.group(0)}</a>', esc)
    paragraphs = "".join(
        f'<p style="margin:0 0 16px;line-height:1.6">{p}</p>'
        for p in esc.split("\n") if p.strip())

    button = ""
    if link:
        button = (
            '<table role="presentation" cellpadding="0" cellspacing="0" '
            'style="margin:6px 0 10px"><tr><td '
            f'style="background:{color};border-radius:8px">'
            f'<a href="{link}" style="display:inline-block;padding:11px 20px;'
            'font-weight:600;font-size:14px;color:#ffffff;text-decoration:none">'
            f'{_html.escape(label)}</a></td></tr></table>')

    title = _html.escape((subject or "").strip())
    pre = _html.escape(preheader(body))
    sig_block = signature_html(signature or {}, color)

    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        f'<title>{title}</title></head>'
        '<body style="margin:0;padding:0;background:#ffffff">'
        # строка предпросмотра: видна в списке писем, но не в самом письме
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{pre}</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        '<tr><td align="center">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:560px;padding:28px 20px;text-align:left;'
        'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,'
        'Roboto,Arial,sans-serif;font-size:15px;color:#101828">'
        f'<tr><td>{paragraphs}{button}{sig_block}</td></tr>'
        '<tr><td style="padding-top:28px;font-size:12px;color:#98a2b3;'
        'line-height:1.5">'
        f'<a href="{unsubscribe}" style="color:#98a2b3">Unsubscribe</a>'
        '</td></tr></table></td></tr></table></body></html>'
    )
