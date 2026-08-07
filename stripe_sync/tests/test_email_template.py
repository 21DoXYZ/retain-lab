"""Вёрстка письма: то, что реально увидит человек в почте."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from email_template import preheader, render, split_cta  # noqa: E402


def test_trailing_link_becomes_a_button():
    """Ссылку в конце письма читают как мусор, кнопку - нажимают."""
    text, link = split_cta("Обновите карту, это 30 секунд: https://app.x.com/billing")
    assert link == "https://app.x.com/billing"
    assert text.endswith("30 секунд")


def test_link_inside_a_sentence_stays_in_place():
    body = "Загляните на https://app.x.com/new и оцените, что изменилось"
    text, link = split_cta(body)
    assert link == "" and text == body


def test_preheader_is_clean_and_short():
    pre = preheader("Ваш платёж не прошёл. Обновите карту: https://app.x.com/billing")
    assert "http" not in pre and len(pre) <= 110 and pre.startswith("Ваш платёж")


def test_rendered_email_has_everything_a_letter_needs():
    html = render("Payment issue", "Update your card: https://app.x.com/billing",
                  "https://retivo.digital/public/unsubscribe?t=1",
                  brand="Hub Content", cta_label="Update card", brand_color="#f21d32")
    assert "Update card" in html and "unsubscribe" in html.lower()
    assert "Hub Content" in html and "#f21d32" in html
    assert "display:none" in html                 # строка предпросмотра
    assert "<img" not in html and "http://cdn" not in html   # без внешних ресурсов


def test_html_is_escaped_and_bad_colour_is_ignored():
    html = render("<script>", "тело <b>жирным</b>", "https://u", brand_color="удали-меня")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "#101828" in html                      # подставился безопасный цвет
