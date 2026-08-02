from datetime import date

import pytest

from utils.backtesting.portfolio import replay_shared_capital
from utils.backtesting.recommendation_bot import (
    _apply_exit_strategy,
    _optimize_multi_trade_portfolio,
    _validate_config,
)


def test_recommendation_bot_allocation_is_user_selected_in_five_percent_steps():
    assert _validate_config({"max_stock_pct": 5})["max_stock_pct"] == 5
    assert _validate_config({"max_stock_pct": 35})["max_stock_pct"] == 35
    with pytest.raises(ValueError, match="multiples of 5"):
        _validate_config({"max_stock_pct": 12})
    strict = _validate_config({
        "minimum_prior_expectancy_pct": 2, "minimum_prior_profit_factor": 1.5,
        "recent_trade_window": 16, "minimum_recent_win_rate": 60,
        "minimum_recent_expectancy_pct": 1,
        "symbol_cooldown_days": 20, "ranking_mode": "risk_adjusted_expectancy",
    })
    assert strict["minimum_prior_expectancy_pct"] == 2
    assert strict["minimum_prior_profit_factor"] == 1.5
    assert strict["recent_trade_window"] == 16
    assert strict["minimum_recent_win_rate"] == 60
    assert strict["minimum_recent_expectancy_pct"] == 1
    assert strict["symbol_cooldown_days"] == 20


def test_research_controls_can_explicitly_disable_conservative_thresholds():
    config = _validate_config({
        "minimum_confidence": 0, "minimum_average_volume": 0,
        "minimum_prior_expectancy_pct": 0, "minimum_prior_profit_factor": 0,
        "minimum_recent_win_rate": 0, "minimum_recent_expectancy_pct": 0,
        "symbol_cooldown_days": 0,
    })
    assert config["minimum_confidence"] == 0
    assert config["minimum_average_volume"] == 0
    assert config["minimum_recent_win_rate"] == 0
    assert config["minimum_recent_expectancy_pct"] == 0
    assert config["symbol_cooldown_days"] == 0


def test_recommendation_bot_uses_shared_cash_and_ten_share_lots():
    trades = [
        {
            "symbol": symbol, "sector": "Banking", "entry_date": date(2026, 1, 1),
            "entry_price": 100.0, "exit_date": date(2026, 1, 10), "exit_price": 110.0,
            "holding_days": 7, "latest_volume": 100000,
        }
        for symbol in ("AAA", "BBB", "CCC")
    ]
    summary, _ = replay_shared_capital(trades, 100000, {
        "max_stock_pct": 10, "max_sector_pct": 100, "max_positions": 10,
        "cash_reserve_pct": 0, "max_volume_participation_pct": 10,
        "charge_model": "nepse_equity", "investor_type": "individual",
        "apply_cgt": True, "dp_charge": 25, "fee_pct": .4, "fixed_fee": 0,
        "allocation_basis": "current_equity", "quantity_lot_size": 10,
    })
    assert summary["accepted_signals"] == 3
    assert summary["final_equity"] > 100000


def test_recommendation_bot_waits_when_shared_cash_is_fully_committed():
    trades = [
        {
            "symbol": symbol, "sector": "Other", "entry_date": date(2026, 1, 1),
            "entry_price": 100.0, "exit_date": date(2026, 1, 10), "exit_price": 101.0,
            "holding_days": 7, "latest_volume": 100000,
        }
        for symbol in ("AAA", "BBB")
    ]
    summary, _ = replay_shared_capital(trades, 100000, {
        "max_stock_pct": 100, "max_sector_pct": 100, "max_positions": 10,
        "cash_reserve_pct": 0, "max_volume_participation_pct": 10,
        "charge_model": "nepse_equity", "investor_type": "individual",
        "apply_cgt": True, "dp_charge": 25, "fee_pct": .4, "fixed_fee": 0,
        "allocation_basis": "current_equity", "quantity_lot_size": 10,
    })
    assert summary["accepted_signals"] == 1
    assert summary["rejected_signals"] == 1


def test_recommendation_bot_captures_only_funded_orders_with_net_results():
    trades = [
        {
            "symbol": symbol, "sector": "Other", "entry_date": date(2026, 1, 1),
            "entry_price": 100.0, "exit_date": date(2026, 1, 10), "exit_price": 110.0,
            "holding_days": 7, "latest_volume": 100000, "preset_name": "Test strategy",
        }
        for symbol in ("AAA", "BBB")
    ]
    summary, _ = replay_shared_capital(trades, 100000, {
        "max_stock_pct": 100, "max_sector_pct": 100, "max_positions": 10,
        "cash_reserve_pct": 0, "max_volume_participation_pct": 10,
        "charge_model": "nepse_equity", "investor_type": "individual",
        "apply_cgt": True, "dp_charge": 25, "fee_pct": .4, "fixed_fee": 0,
        "allocation_basis": "current_equity", "quantity_lot_size": 10,
        "capture_executions": True,
    })
    assert len(summary["executions"]) == 1
    assert summary["executions"][0]["quantity"] % 10 == 0
    assert summary["executions"][0]["net_return_pct"] > 0
    assert summary["executions"][0]["total_charges"] > 0


def test_hard_stop_waits_for_minimum_holding_sessions():
    candidate = {
        "symbol": "AAA", "entry_date": date(2026, 1, 1), "entry_price": 100.0,
        "exit_date": date(2026, 1, 20), "exit_price": 100.0,
    }
    quotes = {"AAA": [
        {
            "session_date": date(2026, 1, day),
            "open_price": close + 2,
            "high_price": close + 3,
            "low_price": close - 1,
            "close_price": close,
        }
        for day, close in ((1, 100), (2, 80), (3, 79), (4, 78), (5, 77), (6, 76))
    ]}
    result = _apply_exit_strategy([candidate], quotes, {
        "exit_strategy": "hard_stop", "hard_stop_pct": 5, "trailing_stop_pct": 8,
        "take_profit_pct": 15, "slippage_pct": 0, "min_holding_days": 5,
        "max_holding_days": 90,
    }, date(2026, 1, 31))
    assert result[0]["exit_date"] == date(2026, 1, 6)
    assert result[0]["exit_reason"] == "hard_stop"
    assert result[0]["exit_price"] == 78


def test_strategy_exit_is_protected_by_hard_stop_after_minimum_hold():
    candidate = {
        "symbol": "AAA", "entry_date": date(2026, 1, 1), "entry_price": 100.0,
        "exit_date": date(2026, 1, 20), "exit_price": 100.0,
    }
    quotes = {"AAA": [
        {
            "session_date": date(2026, 1, day),
            "open_price": close + 2,
            "high_price": close + 3,
            "low_price": close - 1,
            "close_price": close,
        }
        for day, close in ((1, 100), (2, 96), (3, 94), (4, 93), (5, 92), (6, 91), (20, 80))
    ]}
    result = _apply_exit_strategy([candidate], quotes, {
        "exit_strategy": "strategy_exit", "hard_stop_pct": 3, "trailing_stop_pct": 8,
        "take_profit_pct": 15, "slippage_pct": 0, "min_holding_days": 5,
        "max_holding_days": 90,
    }, date(2026, 1, 31))

    assert result[0]["exit_date"] == date(2026, 1, 6)
    assert result[0]["exit_reason"] == "hard_stop"
    assert result[0]["exit_price"] == 93


def test_intraday_low_fills_stop_price_instead_of_daily_close():
    candidate = {
        "symbol": "AAA", "entry_date": date(2026, 1, 1), "entry_price": 100.0,
        "exit_date": date(2026, 1, 20), "exit_price": 100.0,
    }
    quotes = {"AAA": [
        {"session_date": date(2026, 1, 1), "open_price": 100, "high_price": 103, "low_price": 99, "close_price": 100},
        {"session_date": date(2026, 1, 2), "open_price": 101, "high_price": 102, "low_price": 96, "close_price": 90},
    ]}
    result = _apply_exit_strategy([candidate], quotes, {
        "exit_strategy": "strategy_exit", "hard_stop_pct": 2, "trailing_stop_pct": 8,
        "take_profit_pct": 15, "slippage_pct": 0, "min_holding_days": 1,
        "max_holding_days": 90,
    }, date(2026, 1, 31))

    assert result[0]["exit_date"] == date(2026, 1, 2)
    assert result[0]["exit_reason"] == "hard_stop"
    assert result[0]["exit_price"] == 98


def test_same_symbol_cooldown_skips_immediate_reentry():
    trades = [
        {"symbol": "AAA", "sector": "Other", "entry_date": date(2026, 1, 1),
         "entry_price": 100.0, "exit_date": date(2026, 1, 5), "exit_price": 110.0,
         "holding_days": 4, "latest_volume": 100000},
        {"symbol": "AAA", "sector": "Other", "entry_date": date(2026, 1, 8),
         "entry_price": 100.0, "exit_date": date(2026, 1, 12), "exit_price": 110.0,
         "holding_days": 4, "latest_volume": 100000},
    ]
    summary, _ = replay_shared_capital(trades, 100000, {
        "max_stock_pct": 100, "max_sector_pct": 100, "max_positions": 1,
        "cash_reserve_pct": 0, "max_volume_participation_pct": 10,
        "charge_model": "nepse_equity", "investor_type": "individual",
        "apply_cgt": True, "dp_charge": 25, "fee_pct": .4, "fixed_fee": 0,
        "allocation_basis": "current_equity", "quantity_lot_size": 10,
        "symbol_cooldown_days": 10,
    })
    assert summary["accepted_signals"] == 1
    assert summary["rejected_signals"] == 1


def test_rejected_overlap_cannot_close_the_funded_trade():
    trades = [
        {
            "trade_id": 1, "symbol": "NABIL", "sector": "Banking",
            "entry_date": date(2026, 1, 1), "entry_price": 100.0,
            "exit_date": date(2026, 1, 10), "exit_price": 120.0,
            "holding_days": 9, "latest_volume": 100000,
        },
        {
            "trade_id": 2, "symbol": "NABIL", "sector": "Banking",
            "entry_date": date(2026, 1, 2), "entry_price": 105.0,
            "exit_date": date(2026, 1, 5), "exit_price": 90.0,
            "holding_days": 3, "latest_volume": 100000,
        },
    ]
    summary, _ = replay_shared_capital(trades, 100000, {
        "max_positions": 1, "max_stock_pct": 10, "max_sector_pct": 100,
        "cash_reserve_pct": 0, "max_volume_participation_pct": 5,
        "quantity_lot_size": 10, "capture_executions": True,
        "charge_model": "legacy_flat", "fee_pct": 0, "fixed_fee": 0,
        "apply_cgt": False, "dp_charge": 0,
    })

    assert summary["accepted_signals"] == 1
    assert summary["rejected_signals"] == 1
    assert len(summary["executions"]) == 1
    assert summary["executions"][0]["trade_id"] == 1
    assert summary["executions"][0]["exit_date"] == date(2026, 1, 10)
    assert summary["executions"][0]["net_pnl"] == 2000.0


def test_trailing_stop_remembers_high_during_minimum_hold():
    candidate = {
        "symbol": "AAA", "entry_date": date(2026, 1, 1), "entry_price": 100.0,
        "exit_date": date(2026, 1, 20), "exit_price": 100.0,
    }
    quotes = {"AAA": [
        {"session_date": date(2026, 1, day), "close_price": close}
        for day, close in ((1, 100), (2, 120), (3, 118), (4, 112), (5, 109), (6, 108))
    ]}
    result = _apply_exit_strategy([candidate], quotes, {
        "exit_strategy": "trailing_stop", "hard_stop_pct": 20, "trailing_stop_pct": 8,
        "take_profit_pct": 50, "slippage_pct": 0, "min_holding_days": 5,
        "max_holding_days": 90,
    }, date(2026, 1, 31))

    assert result[0]["exit_date"] == date(2026, 1, 6)
    assert result[0]["exit_reason"] == "trailing_stop"


def test_multi_trade_optimizer_selects_only_on_training_period():
    def trades(training_return: float, validation_return: float):
        output = []
        for index in range(10):
            entry = date(2025, 1, 1 + index * 2)
            output.append({
                "symbol": f"T{index}", "sector": "Other",
                "entry_date": entry, "exit_date": date(2025, 1, 2 + index * 2),
                "entry_price": 100.0, "exit_price": 100 * (1 + training_return / 100),
                "holding_days": 1, "latest_volume": 100000,
            })
        for index in range(5):
            entry = date(2025, 10, 1 + index * 2)
            output.append({
                "symbol": f"V{index}", "sector": "Other",
                "entry_date": entry, "exit_date": date(2025, 10, 2 + index * 2),
                "entry_price": 100.0, "exit_price": 100 * (1 + validation_return / 100),
                "holding_days": 1, "latest_volume": 100000,
            })
        return output

    config = _validate_config({
        "initial_capital": 100000, "max_positions": 1, "max_stock_pct": 10,
        "max_sector_pct": 40, "cash_reserve_pct": 5,
    })
    allocation = {
        **config, "charge_model": "legacy_flat", "fee_pct": 0, "fixed_fee": 0,
        "apply_cgt": False, "dp_charge": 0, "quantity_lot_size": 1,
    }
    result = _optimize_multi_trade_portfolio(
        {
            "strategy_exit": trades(10, -10),
            "hard_stop": trades(1, 8),
        },
        config,
        allocation,
        [],
        date(2025, 1, 1),
        date(2025, 12, 31),
    )

    assert result is not None
    assert result["suggested_config"]["exit_strategy"] == "strategy_exit"
    assert result["validation"]["net_return_pct"] < 0
    assert result["paper_ready"] is False
