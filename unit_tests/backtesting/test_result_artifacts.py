from datetime import date

from utils.backtesting.result_artifacts import artifact_key, settings_hash, strategy_hash


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
