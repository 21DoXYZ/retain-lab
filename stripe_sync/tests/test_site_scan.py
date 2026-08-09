

# ── Цвет бренда с сайта: контекст и кластеры, а не голая частота ─────────────

def test_brand_color_cta_context_beats_raw_frequency():
    """Урок hubcontent: зелёные галочки где-то в глубине не должны побеждать
    цвет кнопки. Контекст (--primary, .btn) весит больше частоты."""
    from stripe_sync.site_scan import brand_color_from_html
    html = "<div>" + "#22cc44 " * 20 + "</div>"          # мусор частотой
    css = [":root{--primary:#2563eb} .btn{background:#2563eb}"]
    assert brand_color_from_html(html, css) == "#2563eb"


def test_brand_color_dark_family_clusters_together():
    """Монохромный бренд размазан по оттенкам (#0a0a0a/#141414/#1f1f1f) -
    семейство голосует вместе и уверенно побеждает."""
    from stripe_sync.site_scan import brand_color_from_html
    html = ("#0a0a0a " * 10 + "#141414 " * 10 + "#1f1f1f " * 12
            + "#22cc44 " * 9)
    out = brand_color_from_html(html, [])
    assert out in ("#0a0a0a", "#141414", "#1f1f1f")


def test_brand_color_white_is_background_not_brand():
    from stripe_sync.site_scan import brand_color_from_html
    assert brand_color_from_html("#ffffff " * 50 + "#fefefe " * 30, []) == ""


def test_brand_color_ambiguous_stays_silent():
    """Два равных кандидата - честнее промолчать, чем угадать чужой бренд."""
    from stripe_sync.site_scan import brand_color_from_html
    html = "#2563eb " * 10 + "#cc2244 " * 10
    assert brand_color_from_html(html, []) == ""


def test_brand_color_theme_meta_counts():
    from stripe_sync.site_scan import brand_color_from_html
    html = '<meta name="theme-color" content="#7c3aed">' + "#22cc44 " * 3
    assert brand_color_from_html(html, []) == "#7c3aed"
