from datetime import date

from utils.backtesting.portfolio import replay_shared_capital


def test_shared_portfolio_enforces_position_limit_and_cash_reserve():
    trades = []
    for index, symbol in enumerate(("AAA", "BBB", "CCC")):
        trades.append({
            "symbol": symbol, "sector": "Bank", "entry_date": date(2024, 1, 1),
            "exit_date": date(2024, 1, 10), "entry_price": 100, "exit_price": 110,
            "quantity": 1000, "fees": 0, "latest_volume": 100000,
        })
    summary, curve = replay_shared_capital(trades, 100000, {
        "max_stock_pct": 10, "max_sector_pct": 30, "max_positions": 2,
        "cash_reserve_pct": 5, "max_volume_participation_pct": 10,
    })
    assert summary["accepted_signals"] == 2
    assert summary["rejected_signals"] == 1
    assert summary["net_return_pct"] > 0
    assert min(point["cash"] for point in curve) >= 5000
