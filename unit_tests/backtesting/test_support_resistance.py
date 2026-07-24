from copy import deepcopy

from utils.backtesting.support_resistance import calculate_zone_history, chart_zone_history, current_zones


def _rows(count: int = 90):
    rows = []
    for index in range(count):
        cycle = (index % 12) - 6
        close = 100 + cycle * 1.5 + index * .04
        rows.append({
            "date": f"2025-{index // 28 + 1:02d}-{index % 28 + 1:02d}",
            "open": close - .3,
            "high": close + 1.2,
            "low": close - 1.2,
            "close": close,
            "volume": 1000 + (index % 12) * 80,
            "technical_atr_14": 2.4,
        })
    return rows


def test_zone_history_is_strictly_point_in_time():
    rows = _rows()
    prefix = calculate_zone_history(rows[:60])
    changed = deepcopy(rows)
    for row in changed[60:]:
        row.update({"high": 10000, "low": 1, "close": 9000, "volume": 9_000_000})
    full = calculate_zone_history(changed)
    assert prefix == full[:60]


def test_pivot_is_not_available_until_confirmation_bars_complete():
    rows = [
        {"high": high, "low": low, "close": close, "volume": 1000, "technical_atr_14": 2}
        for high, low, close in [
            (106, 100, 103), (105, 99, 102), (104, 98, 101), (103, 90, 100),
            (104, 97, 101), (105, 98, 102), (106, 99, 103),
        ]
    ]
    history = calculate_zone_history(rows, pivot_span=3)
    assert history[5]["support"] is None
    assert history[6]["support"]["center"] == 90


def test_current_zones_returns_bounded_chart_contract():
    zones = current_zones(_rows())
    assert 1 <= len(zones) <= 6
    for zone in zones:
        assert zone["kind"] in {"support", "resistance"}
        assert zone["lower"] < zone["upper"]
        assert 0 <= zone["confidence"] <= 100
        assert zone["touches"] >= 1
        assert "touches" in zone["label"]


def test_chart_history_is_time_local_prominent_and_short():
    rows = _rows(180)
    snapshots = chart_zone_history(rows)
    assert len(snapshots) == len(rows)
    assert all(len(snapshot["zones"]) <= 2 for snapshot in snapshots)
    latest = snapshots[-1]
    for zone in latest["zones"]:
        assert zone["touches"] >= 2
        assert zone["confidence"] >= 42
        start_index = next(index for index, row in enumerate(rows) if row["date"] == zone["start_date"])
        assert len(rows) - 1 - start_index <= 120
    assert chart_zone_history(rows[:120]) == snapshots[:120]
