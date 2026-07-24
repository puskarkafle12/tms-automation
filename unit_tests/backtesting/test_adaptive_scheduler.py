from unittest.mock import MagicMock, patch

from utils.backtesting import v2_jobs


def test_claim_next_run_uses_separate_queue_and_round_robin_heartbeat_order():
    session = MagicMock()
    session.execute.return_value.scalar.return_value = "run-1"
    with patch.object(v2_jobs, "_session", return_value=session):
        assert v2_jobs._claim_next_run(refresh_only=False) == "run-1"

    claim_sql = str(session.execute.call_args_list[0].args[0])
    assert "incremental_refresh_active')::boolean,FALSE)=FALSE" in claim_sql
    assert "COALESCE(heartbeat_at,created_at),created_at" in claim_sql
    session.commit.assert_called_once()


def test_monthly_revalidation_refreshes_recent_signals_without_full_backtest():
    row = {
        "rejection_key": "reject-1",
        "source_run_id": "run-1",
        "owner_id": "owner-1",
        "symbol": "NABIL",
        "strategy_id": "strategy-1",
        "total_trades": 12,
        "win_rate_pct": 45,
        "recheck_count": 2,
    }
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = {
        "configuration": {
            "start_date": "2020-01-01",
            "data_source": "merolagani",
        },
    }
    signal = {
        "preset_id": "strategy-1",
        "current_signal_status": "buy",
        "current_signal_date": "2026-07-24",
        "current_evidence": {},
    }
    with (
        patch.object(v2_jobs, "_claim_due_revalidation", return_value=row),
        patch.object(v2_jobs, "_revalidation_preset", return_value={"id": "strategy-1"}),
        patch.object(v2_jobs, "_session", return_value=session),
        patch.object(v2_jobs, "_refresh_symbol_signals_task", return_value={
            "results": [signal],
            "error": None,
        }) as refresh,
        patch.object(v2_jobs, "_run_symbol_task") as full_backtest,
        patch.object(v2_jobs, "_finish_revalidation") as finish,
        patch("utils.backtesting.service.fetch_historical_bars"),
    ):
        assert v2_jobs._run_one_due_revalidation()

    assert refresh.call_args.args[0]["refresh_window_sessions"] == 65
    full_backtest.assert_not_called()
    assert finish.call_args.kwargs["signal"] == signal

