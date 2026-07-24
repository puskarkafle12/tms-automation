import json
from datetime import date

from utils.backtesting.result_artifacts import (
    artifact_key,
    load_symbol_artifacts,
    settings_hash,
    store_symbol_artifacts,
    strategy_hash,
)


def _preset(strategy_id: str = "volume-breakout"):
    return {
        "id": strategy_id, "version": "2", "source_hash": "catalog-source-1",
        "condition": "close > sma_20 AND volume > average_volume_20",
        "defaults": {"stop_loss_pct": 5, "take_profit_pct": 12, "max_holding_days": 20},
    }


def _config():
    return {
        "name": "ignored display name", "owner_id": "ignored owner", "start_date": "2018-01-01",
        "end_date": "2026-07-18", "data_source": "merolagani", "initial_capital": 100000,
        "charge_model": "nepse_equity", "investor_type": "individual", "apply_cgt": True,
        "dp_charge": 25, "fee_pct": .4, "slippage_pct": .1, "position_size_pct": 100,
        "min_holding_days": 0, "max_holding_days": None,
    }


def test_artifact_identity_is_owner_neutral_but_data_and_symbol_specific():
    config = _config(); preset = _preset()
    kwargs = dict(preset=preset, config=config, data_session=date(2026, 7, 18), data_hash="bars-a",
                  engine_version="engine-2", indicator_version="indicators-3")
    first = artifact_key(symbol="NABIL", **kwargs)
    renamed = artifact_key(symbol="NABIL", **{**kwargs, "config": {**config, "name": "another user run", "owner_id": "42"}})
    assert first == renamed
    assert first != artifact_key(symbol="API", **kwargs)
    assert first != artifact_key(symbol="NABIL", **{**kwargs, "data_hash": "bars-b"})


def test_strategy_and_execution_changes_invalidate_artifact():
    preset = _preset(); config = _config()
    assert strategy_hash(preset) != strategy_hash({**preset, "condition": "close > sma_50"})
    base = settings_hash(config, preset, engine_version="engine-2", indicator_version="indicators-3")
    assert base != settings_hash({**config, "slippage_pct": .3}, preset, engine_version="engine-2", indicator_version="indicators-3")
    assert base != settings_hash(config, preset, engine_version="engine-3", indicator_version="indicators-3")


class _Result:
    def __init__(self, *, rows=None, scalar_value=None):
        self.rows = rows or []
        self.scalar_value = scalar_value

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.scalar_value


class _Session:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params))
        return self.handler(sql, params)


def test_rejection_ledger_skips_before_market_cache_context_is_available():
    preset = _preset()
    identity = (strategy_hash(preset), settings_hash(
        _config(), preset, engine_version="engine-2", indicator_version="indicators-3",
    ))

    def handler(sql, _params):
        if "FROM backtest_rejected_strategies" in sql:
            return _Result(rows=[{
                "rejection_key": "rejected-1", "strategy_hash": identity[0],
                "settings_hash": identity[1], "total_trades": 8, "win_rate_pct": 75,
            }])
        return _Result()

    payload = load_symbol_artifacts(
        _Session(handler), symbol="NABIL", presets=[preset], config=_config(),
        engine_version="engine-2", indicator_version="indicators-3",
    )
    assert payload["missing"] == []
    assert payload["rejected_hits"] == 1


def test_cached_rejection_is_linked_to_the_current_workspace_without_rerunning():
    preset = _preset("linkage-test")
    identity = (strategy_hash(preset), settings_hash(
        _config(), preset, engine_version="engine-2", indicator_version="indicators-3",
    ))

    def handler(sql, _params):
        if "FROM backtest_rejected_strategies" in sql:
            return _Result(rows=[{
                "rejection_key": "rejected-1", "strategy_hash": identity[0],
                "settings_hash": identity[1], "total_trades": 12, "win_rate_pct": 45,
            }])
        return _Result()

    session = _Session(handler)
    payload = load_symbol_artifacts(
        session, symbol="NABIL", presets=[preset], config=_config(),
        engine_version="engine-2", indicator_version="indicators-3",
        owner_id="owner-1", source_run_id="run-1",
    )
    linkage = next(call for call in session.calls if "source_run_id=COALESCE" in call[0])
    definition = next(call for call in session.calls if "INSERT INTO backtest_strategy_definitions" in call[0])
    assert payload["missing"] == []
    assert linkage[1][0]["owner_id"] == "owner-1"
    assert linkage[1][0]["source_run_id"] == "run-1"
    assert json.loads(definition[1][0]["definition"]) == preset


def test_failed_result_is_saved_with_stock_and_strategy_without_artifact_context():
    preset = _preset("failed-strategy-test")

    def handler(sql, _params):
        if "FROM market_screener_cache" in sql:
            return _Result(scalar_value="Nabil Bank Limited")
        return _Result()

    session = _Session(handler)
    stored = store_symbol_artifacts(
        session,
        output={
            "symbol": "NABIL", "technical_snapshot": {},
            "results": [{"preset_id": preset["id"], "preset_name": "Volume breakout",
                         "total_trades": 8, "win_rate_pct": 75}],
        },
        presets=[preset], config=_config(),
        engine_version="engine-2", indicator_version="indicators-3",
        owner_id="owner-1", source_run_id="run-1",
    )
    rejection_call = next(call for call in session.calls if "INSERT INTO backtest_rejected_strategies" in call[0])
    definition_call = next(call for call in session.calls if "INSERT INTO backtest_strategy_definitions" in call[0])
    saved = rejection_call[1][0]
    assert stored == 0
    assert saved["stock_name"] == "Nabil Bank Limited"
    assert saved["strategy_name"] == "Volume breakout"
    assert saved["rejection_reason"] == "insufficient_trades"
    assert saved["owner_id"] == "owner-1"
    assert saved["source_run_id"] == "run-1"
    assert saved["strategy_definition"] == "{}"
    assert json.loads(definition_call[1][0]["definition"]) == preset
    assert saved["revalidation_state"] == "ineligible"
