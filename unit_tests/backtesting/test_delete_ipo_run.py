from unittest.mock import MagicMock, patch

from utils.backtesting.v2_jobs import delete_ipo_run


def test_delete_ipo_run_rejects_non_ipo_workspaces():
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = {
        "run_id": "run-1", "status": "completed", "run_type": "market_scan",
    }
    with patch("utils.backtesting.v2_jobs._session", return_value=session):
        try:
            delete_ipo_run("run-1", owner_id="owner-1")
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "Only IPO research" in str(exc)
    session.rollback.assert_called()


def test_delete_ipo_run_purges_rejection_cache_and_run_row():
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = {
        "run_id": "ipo-1", "status": "cancelled", "run_type": "ipo_research",
    }
    with patch("utils.backtesting.v2_jobs._session", return_value=session), \
         patch("utils.backtesting.v2_jobs._rebuild_canonical_for_owner") as rebuild, \
         patch("utils.backtesting.v2_jobs.list_runs", return_value={"ipo_items": []}):
        payload = delete_ipo_run("ipo-1", owner_id="owner-1")
    sql_texts = [str(call.args[0]) for call in session.execute.call_args_list if call.args]
    assert any("backtest_rejected_strategies" in text for text in sql_texts)
    assert any("DELETE FROM backtest_runs" in text for text in sql_texts)
    rebuild.assert_called_once()
    session.commit.assert_called_once()
    assert payload["deleted_run_id"] == "ipo-1"
    assert payload["items"] == []
