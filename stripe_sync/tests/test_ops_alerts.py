"""Сторож платформы: сбор проблем и суточный дедуп."""

import ops_alerts


class _Q:
    def __init__(self, rows_by_marker):
        self.rows_by_marker = rows_by_marker

    def query(self, sql):
        class R:
            def __init__(self, rows): self.result_rows = rows
        for marker, rows in self.rows_by_marker.items():
            if marker in sql:
                return R(rows)
        return R([])


def test_collect_flags_all_four_classes():
    client = _Q({
        "pipeline_runs": [["hub", "trigger:T2", "ValueError: boom", 120]],
        "saas_events": [["hub", 500]],                       # молчит 500 мин > 360
        "error:%": [["hub", 25]],                            # всплеск отказов
        "callback_not_configured": [["hub", 162]],
    })
    probs = dict(ops_alerts.collect_problems(client))
    assert "hub|pipe|trigger:T2" in probs and "ValueError" in probs["hub|pipe|trigger:T2"]
    assert "hub|feed" in probs and "8ч" in probs["hub|feed"]
    assert "hub|senderr" in probs
    assert "hub|callback" in probs and "162" in probs["hub|callback"]


def test_feed_silence_threshold_and_spike_floor():
    client = _Q({
        "saas_events": [["hub", 200]],                       # 200 мин < 360 - тихо
        "error:%": [["hub", 5]],                             # ниже порога
    })
    assert ops_alerts.collect_problems(client) == []


def test_dedupe_window_filters_sent_keys():
    client = _Q({"ops_alert_log": [["hub|feed"]]})
    fresh = ops_alerts.fresh_only(client, [("hub|feed", "a"), ("hub|pipe|x", "b")])
    assert fresh == [("hub|pipe|x", "b")]
