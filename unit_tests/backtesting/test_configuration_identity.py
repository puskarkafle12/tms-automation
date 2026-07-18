from unittest.mock import MagicMock, patch

from utils.backtesting.v2_jobs import _result_configuration_hash
from utils.backtesting.v2_jobs import set_run_control


def _row(**overrides):
    assumptions = {
        "preset_source_hash": "source-a",
        "preset_version": "v1",
        "strategy_query": "WHEN rsi < 30",
        "sell_strategy_query": "WHEN profit_percent >= 15",
        "min_holding_days": 5,
        "max_holding_days": 90,
        "stop_loss_pct": 6,
        "take_profit_pct": 15,
        "charge_model": "nepse_equity_v2024_05_14",
        "position_size_pct": 100,
        "period": {"start": "2006-01-01", "end": "2026-07-18"},
        "data_source": "merolagani",
    }
    assumptions.update(overrides.pop("assumptions", {}))
    return {"preset_id": "rsi-reversal", "evaluation_split": "full", "assumptions": assumptions, **overrides}


def test_identity_deduplicates_only_complete_equivalent_simulations():
    base = _result_configuration_hash("NABIL", _row())
    assert base == _result_configuration_hash("NABIL", _row())
    assert base != _result_configuration_hash("NABIL", _row(assumptions={"min_holding_days": 8}))
    assert base != _result_configuration_hash("NABIL", _row(assumptions={"max_holding_days": 60}))
    assert base != _result_configuration_hash("NABIL", _row(assumptions={"strategy_query": "WHEN rsi < 25"}))
    assert base != _result_configuration_hash("NABIL", _row(assumptions={"charge_model": "legacy_flat"}))
    assert base != _result_configuration_hash("API", _row())


def test_identity_advances_without_duplicating_the_same_daily_configuration():
    older = _row()
    newer = _row()
    newer["assumptions"]["period"] = {"start": "2006-01-01", "end": "2026-07-19"}
    assert _result_configuration_hash("NABIL", older) == _result_configuration_hash("NABIL", newer)


@patch("utils.backtesting.v2_jobs.get_run")
@patch("utils.backtesting.v2_jobs._session")
def test_pause_is_confirmed_in_database_immediately(mock_session_factory, mock_get_run):
    session = MagicMock()
    session.execute.return_value.rowcount = 1
    mock_session_factory.return_value = session
    mock_get_run.return_value = {"run_id": "run-1", "status": "paused", "pause_requested": True}

    result = set_run_control("run-1", "pause", owner_id="owner-1")

    statement = str(session.execute.call_args.args[0])
    assert "status='paused'" in statement
    assert "pause_requested=TRUE" in statement
    session.commit.assert_called_once()
    assert result["status"] == "paused"


@patch("utils.backtesting.v2_jobs.get_run")
@patch("utils.backtesting.v2_jobs._session")
def test_cancel_is_confirmed_and_preserves_completed_results(mock_session_factory, mock_get_run):
    session = MagicMock()
    session.execute.return_value.rowcount = 1
    mock_session_factory.return_value = session
    mock_get_run.return_value = {"run_id": "run-1", "status": "cancelled", "cancel_requested": True}

    result = set_run_control("run-1", "cancel", owner_id="owner-1")

    statement = str(session.execute.call_args.args[0])
    assert "status='cancelled'" in statement
    assert "cancel_requested=TRUE" in statement
    assert "DELETE" not in statement.upper()
    session.commit.assert_called_once()
    assert result["status"] == "cancelled"
