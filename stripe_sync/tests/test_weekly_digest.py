"""Недельный дайджест: блок «письма -> деньги».

Ловушка тотала: строки money - ПО КАМПАНИЯМ, а один человек бывает тронут
несколькими кампаниями. Сумма по строкам задваивает и покупателей, и доллары
в заголовке блока («2 customers, $200» при одном клиенте с одним инвойсом).
Тотал обязан считаться отдельным дедуп-запросом (клиент один раз, инвойс
один раз), строки кампаний остаются как есть - как на экране Кампаний.
"""

import types

from stripe_sync.weekly_digest import build_digest


class FakeCH:
    def __init__(self, money=None, total=None):
        self.money = money or []
        self.total = total or [[0, 0]]

    def query(self, sql, parameters=None):
        if "event_type = 'signup'" in sql:
            rows = [[5, 1, 3, 10, 0, 0]]
        elif "user_actions ua" in sql:
            rows = [[10, 4, 3, 2]]
        elif "countIf(status = 'sent')" in sql:
            rows = [[7, 0, 1]]
        elif "uplift_reports" in sql:
            rows = [[0.0]]
        elif "HAVING revenue > 0" in sql:
            rows = self.money
        elif "sumIf(inv.usd" in sql:
            rows = self.total
        else:
            rows = []
        return types.SimpleNamespace(result_rows=rows)


def test_money_total_deduped_across_campaigns():
    """Один клиент, один инвойс $100, тронут ДВУМЯ кампаниями: строки кампаний
    показывают по $100 (перекрытие легально, как на экране), но тотал обязан
    быть 1 customer / $100, а не 2 / $200."""
    ch = FakeCH(money=[["K1_activation", 1, 100.0], ["K6_winback", 1, 100.0]],
                total=[[1, 100.0]])
    digest = build_digest(ch, "t1")
    assert "Paid after our emails this week: 1 customer" in digest
    assert "$100" in digest.split("Paid after")[1].splitlines()[0]
    assert "- K1_activation: 1 paid, $100" in digest
    assert "- K6_winback: 1 paid, $100" in digest
    assert "2 customers, $200" not in digest


def test_money_block_absent_without_revenue():
    digest = build_digest(FakeCH(), "t1")
    assert "Paid after our emails" not in digest
