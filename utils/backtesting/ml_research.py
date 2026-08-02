"""Paper-inspired, causal model comparison for NEPSE daily OHLCV data.

This module is a research gate, not an order generator. Models are compared on
purged chronological folds and a non-overlapping, cost-adjusted one-position
portfolio. Nothing here can submit or unlock an order.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text
from xgboost import XGBClassifier


FEATURE_COLUMNS = (
    "return_1", "return_5", "return_10", "return_20", "return_60",
    "momentum_120_skip_20", "distance_sma_5", "distance_sma_20",
    "distance_sma_60", "volatility_20", "volatility_60", "volume_ratio_20",
    "log_dollar_volume", "range_pct", "gap_pct", "rsi_14", "drawdown_60",
    "return_5_rank", "return_20_rank", "return_60_rank",
    "momentum_120_skip_20_rank", "volatility_20_rank", "liquidity_rank",
    "market_return_20",
)

LEARNED_MODELS = (
    "elastic_net",
    "random_forest",
    "hist_gradient_boosting",
    "xgboost",
    "shallow_neural_network",
)

PAPER_RULES = (
    "cross_sectional_momentum",
    "volatility_scaled_trend",
    "short_term_reversal",
    "momentum_liquidity_low_vol",
)

MODEL_LABELS = {
    "elastic_net": "Elastic-net return classifier",
    "random_forest": "Shallow random forest",
    "hist_gradient_boosting": "Histogram gradient boosting",
    "xgboost": "Regularized XGBoost",
    "shallow_neural_network": "Shallow neural network",
    "cross_sectional_momentum": "Cross-sectional momentum",
    "volatility_scaled_trend": "Volatility-scaled time-series momentum",
    "short_term_reversal": "Short-term reversal inside positive trend",
    "momentum_liquidity_low_vol": "Momentum + liquidity + low-volatility ensemble",
}

MODEL_SOURCES = {
    "elastic_net": "Gu, Kelly & Xiu (2020) regularized linear benchmark",
    "random_forest": "Gu, Kelly & Xiu (2020) nonlinear tree benchmark",
    "hist_gradient_boosting": "Gu, Kelly & Xiu (2020) boosted-tree family",
    "xgboost": "Chen & Guestrin (2016) regularized boosted trees",
    "shallow_neural_network": "Gu, Kelly & Xiu (2020) shallow neural-network family",
    "cross_sectional_momentum": "Jegadeesh & Titman (1993) relative-strength momentum",
    "volatility_scaled_trend": "Moskowitz, Ooi & Pedersen (2012) time-series momentum",
    "short_term_reversal": "Short-horizon return-reversal literature",
    "momentum_liquidity_low_vol": "Gu, Kelly & Xiu (2020) dominant signal families",
}


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _number_list(value: Any, default: Sequence[int]) -> List[int]:
    raw = value if isinstance(value, (list, tuple)) else default
    return sorted({max(3, min(60, int(item))) for item in raw})[:6]


def _validate(raw: Dict[str, Any]) -> Dict[str, Any]:
    config = dict(raw or {})
    horizons = _number_list(config.get("horizons"), (5, 10, 20, 30))
    return {
        "history_days": max(730, min(3650, int(config.get("history_days") or 1825))),
        "training_days": max(365, min(1460, int(config.get("training_days") or 730))),
        "test_days": max(45, min(240, int(config.get("test_days") or 90))),
        "folds": max(3, min(6, int(config.get("folds") or 3))),
        "horizons": horizons,
        "minimum_volume": max(0.0, float(config.get("minimum_volume") or 5000)),
        "round_trip_cost_pct": max(
            0.1, min(10.0, float(config.get("round_trip_cost_pct") or 1.1))
        ),
        "top_fraction": max(0.01, min(0.25, float(config.get("top_fraction") or 0.1))),
        "initial_capital": max(
            1000.0, min(100_000_000.0, float(config.get("initial_capital") or 100000))
        ),
        "target_returns": {
            int(horizon): float(
                (config.get("target_returns") or {}).get(str(horizon))
                or (config.get("target_returns") or {}).get(horizon)
                or {5: 2.0, 10: 3.0, 20: 5.0, 30: 7.0}.get(horizon, max(1.0, horizon * 0.22))
            )
            for horizon in horizons
        },
    }


def _base_features(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.sort_values(["symbol", "session_date"]).copy()
    group = data.groupby("symbol", group_keys=False)
    close = data["close_price"]
    for window in (1, 5, 10, 20, 60):
        data[f"return_{window}"] = group["close_price"].pct_change(window)
    data["momentum_120_skip_20"] = group["close_price"].shift(20) / group["close_price"].shift(120) - 1
    for window in (5, 20, 60):
        average = group["close_price"].transform(lambda values, w=window: values.rolling(w).mean())
        data[f"distance_sma_{window}"] = close / average - 1
    daily_return = group["close_price"].pct_change()
    for window in (20, 60):
        data[f"volatility_{window}"] = daily_return.groupby(data["symbol"]).transform(
            lambda values, w=window: values.rolling(w).std()
        )
    volume_average = group["volume"].transform(lambda values: values.rolling(20).mean())
    data["volume_ratio_20"] = data["volume"] / volume_average.replace(0, np.nan)
    data["log_dollar_volume"] = np.log1p(data["close_price"] * data["volume"])
    data["range_pct"] = (data["high_price"] - data["low_price"]) / close.replace(0, np.nan)
    data["gap_pct"] = data["open_price"] / group["close_price"].shift(1) - 1
    delta = group["close_price"].diff()
    gain = delta.clip(lower=0).groupby(data["symbol"]).transform(
        lambda values: values.rolling(14).mean()
    )
    loss = (-delta.clip(upper=0)).groupby(data["symbol"]).transform(
        lambda values: values.rolling(14).mean()
    )
    data["rsi_14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    rolling_high = group["close_price"].transform(lambda values: values.rolling(60).max())
    data["drawdown_60"] = close / rolling_high - 1
    for column in ("return_5", "return_20", "return_60", "momentum_120_skip_20"):
        data[f"{column}_rank"] = data.groupby("session_date")[column].rank(pct=True)
    data["volatility_20_rank"] = data.groupby("session_date")["volatility_20"].rank(pct=True)
    data["liquidity_rank"] = data.groupby("session_date")["log_dollar_volume"].rank(pct=True)
    data["market_return_20"] = data.groupby("session_date")["return_20"].transform("mean")
    return data.replace([np.inf, -np.inf], np.nan)


def _add_target(data: pd.DataFrame, horizon: int, target_return_pct: float) -> pd.DataFrame:
    result = data.copy()
    future_close = result.groupby("symbol")["close_price"].shift(-horizon)
    result["future_return_pct"] = 100 * (future_close / result["close_price"] - 1)
    result["target"] = (result["future_return_pct"] >= target_return_pct).astype(int)
    return result.dropna(subset=[*FEATURE_COLUMNS, "future_return_pct"])


def _make_model(model_name: str):
    if model_name == "elastic_net":
        return make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(
                penalty="elasticnet", solver="saga", l1_ratio=0.25, C=0.08,
                class_weight="balanced", max_iter=250, n_jobs=1, random_state=42,
            ),
        )
    if model_name == "random_forest":
        return make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(
                n_estimators=140, max_depth=7, min_samples_leaf=80,
                max_features=0.65, class_weight="balanced_subsample",
                n_jobs=2, random_state=42,
            ),
        )
    if model_name == "hist_gradient_boosting":
        return make_pipeline(
            SimpleImputer(strategy="median"),
            HistGradientBoostingClassifier(
                learning_rate=0.04, max_leaf_nodes=15, min_samples_leaf=100,
                l2_regularization=4.0, max_iter=140, random_state=42,
            ),
        )
    if model_name == "xgboost":
        return make_pipeline(
            SimpleImputer(strategy="median"),
            XGBClassifier(
                n_estimators=180, max_depth=3, learning_rate=0.03,
                min_child_weight=70, subsample=0.8, colsample_bytree=0.75,
                reg_alpha=1.0, reg_lambda=12.0, objective="binary:logistic",
                eval_metric="logloss", n_jobs=2, tree_method="hist", random_state=42,
            ),
        )
    return make_pipeline(
        SimpleImputer(strategy="median"),
        StandardScaler(),
        MLPClassifier(
            hidden_layer_sizes=(24, 8), alpha=0.02, batch_size=512,
            learning_rate_init=0.001, max_iter=45, early_stopping=True,
            validation_fraction=0.15, n_iter_no_change=5, random_state=42,
        ),
    )


def _paper_score(model_name: str, data: pd.DataFrame) -> pd.Series:
    if model_name == "cross_sectional_momentum":
        return 0.45 * data["return_60_rank"] + 0.55 * data["momentum_120_skip_20_rank"]
    if model_name == "volatility_scaled_trend":
        raw = data["return_60"] / data["volatility_60"].replace(0, np.nan)
        return raw.where((data["return_60"] > 0) & (data["market_return_20"] > 0))
    if model_name == "short_term_reversal":
        raw = 1 - data["return_5_rank"]
        return raw.where(
            (data["return_5"] < 0) & (data["return_20"] > 0)
            & (data["volume_ratio_20"] >= 1)
        )
    return (
        0.35 * data["return_60_rank"]
        + 0.25 * data["momentum_120_skip_20_rank"]
        + 0.20 * data["liquidity_rank"]
        + 0.20 * (1 - data["volatility_20_rank"])
    )


def _portfolio_metrics(scored: pd.DataFrame, config: Dict[str, Any], horizon: int) -> Dict[str, Any]:
    candidates = scored.dropna(subset=["score"]).copy()
    if candidates.empty:
        return {
            "picks": 0, "precision_pct": 0.0, "average_net_return_pct": 0.0,
            "portfolio_return_pct": 0.0, "final_equity": config["initial_capital"],
            "maximum_drawdown_pct": 0.0,
        }
    candidates["daily_rank"] = candidates.groupby("session_date")["score"].rank(
        pct=True, method="first"
    )
    candidates = candidates[candidates["daily_rank"] >= 1 - config["top_fraction"]]
    available_dates = sorted(candidates["session_date"].unique())
    rebalance_dates = available_dates[::horizon]
    picks = (
        candidates[candidates["session_date"].isin(rebalance_dates)]
        .sort_values(["session_date", "score"], ascending=[True, False])
        .groupby("session_date", as_index=False)
        .head(1)
    )
    if picks.empty:
        return {
            "picks": 0, "precision_pct": 0.0, "average_net_return_pct": 0.0,
            "portfolio_return_pct": 0.0, "final_equity": config["initial_capital"],
            "maximum_drawdown_pct": 0.0,
        }
    net_returns = (picks["future_return_pct"] - config["round_trip_cost_pct"]) / 100
    equity = config["initial_capital"] * (1 + net_returns).cumprod()
    running_high = equity.cummax()
    drawdown = (equity / running_high - 1) * 100
    return {
        "picks": int(len(picks)),
        "precision_pct": round(100 * float(picks["target"].mean()), 2),
        "average_net_return_pct": round(100 * float(net_returns.mean()), 4),
        "portfolio_return_pct": round(100 * float(equity.iloc[-1] / config["initial_capital"] - 1), 4),
        "final_equity": round(float(equity.iloc[-1]), 2),
        "maximum_drawdown_pct": round(abs(float(drawdown.min())), 4),
    }


def _evaluate_model(
    model_name: str,
    data: pd.DataFrame,
    config: Dict[str, Any],
    end_date: date,
    horizon: int,
) -> Dict[str, Any]:
    test_span = timedelta(days=config["test_days"])
    purge_span = timedelta(days=horizon * 3)
    folds: List[Dict[str, Any]] = []
    for offset in range(config["folds"], 0, -1):
        test_end = end_date - test_span * (offset - 1)
        test_start = test_end - test_span
        train_end = test_start - purge_span
        train_start = train_end - timedelta(days=config["training_days"])
        train = data[(data.session_date >= train_start) & (data.session_date < train_end)]
        test = data[(data.session_date >= test_start) & (data.session_date < test_end)]
        if len(train) < 1000 or len(test) < 100 or test.target.nunique() < 2:
            continue
        scored = test[["session_date", "symbol", "target", "future_return_pct"]].copy()
        if model_name in PAPER_RULES:
            scored["score"] = _paper_score(model_name, test)
        else:
            if train.target.nunique() < 2:
                continue
            model = _make_model(model_name)
            model.fit(train[list(FEATURE_COLUMNS)], train.target)
            scored["score"] = model.predict_proba(test[list(FEATURE_COLUMNS)])[:, 1]
        valid = scored.dropna(subset=["score"])
        auc = (
            float(roc_auc_score(valid.target, valid.score))
            if len(valid) >= 2 and valid.target.nunique() > 1 else 0.5
        )
        folds.append({
            "train_start": train_start.isoformat(), "train_end": train_end.isoformat(),
            "test_start": test_start.isoformat(), "test_end": test_end.isoformat(),
            "auc": round(auc, 4),
            "baseline_precision_pct": round(100 * float(test.target.mean()), 2),
            **_portfolio_metrics(scored, config, horizon),
        })
    positive = [fold for fold in folds if float(fold["portfolio_return_pct"]) > 0]
    picks = sum(int(fold["picks"]) for fold in folds)
    weighted = lambda key: (
        sum(float(fold[key]) * int(fold["picks"]) for fold in folds) / picks if picks else 0.0
    )
    average_auc = sum(float(fold["auc"]) for fold in folds) / len(folds) if folds else 0.0
    average_baseline = (
        sum(float(fold["baseline_precision_pct"]) for fold in folds) / len(folds)
        if folds else 0.0
    )
    compounded_growth = np.prod(
        [1 + float(fold["portfolio_return_pct"]) / 100 for fold in folds]
    ) - 1 if folds else 0.0
    final_equity = config["initial_capital"] * (1 + compounded_growth)
    worst_fold = min((float(fold["portfolio_return_pct"]) for fold in folds), default=0.0)
    precision = weighted("precision_pct")
    paper_ready = (
        len(folds) >= 3 and picks >= 12 and len(positive) == len(folds)
        and compounded_growth > 0 and worst_fold > -2
        and precision >= average_baseline + 5 and average_auc >= 0.53
    )
    return {
        "id": model_name,
        "label": MODEL_LABELS[model_name],
        "source": MODEL_SOURCES[model_name],
        "horizon_days": horizon,
        "folds": folds,
        "aggregate": {
            "folds": len(folds), "positive_folds": len(positive), "picks": picks,
            "precision_pct": round(precision, 2),
            "baseline_precision_pct": round(average_baseline, 2),
            "average_net_return_pct": round(weighted("average_net_return_pct"), 4),
            "portfolio_return_pct": round(100 * compounded_growth, 4),
            "final_equity": round(float(final_equity), 2),
            "maximum_drawdown_pct": round(
                max((float(fold["maximum_drawdown_pct"]) for fold in folds), default=0.0), 4
            ),
            "worst_fold_return_pct": round(worst_fold, 4),
            "auc": round(average_auc, 4),
        },
        "paper_ready": paper_ready,
    }


def run_ml_research(session, raw_config: Dict[str, Any]) -> Dict[str, Any]:
    """Compare paper-inspired rules and frozen models over several horizons."""
    config = _validate(raw_config)
    latest = session.execute(text("""
        SELECT MAX(session_date) FROM market_ohlcv_daily
        WHERE adjusted=TRUE AND session_date<=CURRENT_DATE
    """)).scalar()
    if not latest:
        raise ValueError("No completed market session is available.")
    end_date = min(
        _as_date(raw_config.get("end_date")) if raw_config.get("end_date") else latest,
        latest,
    )
    maximum_horizon = max(config["horizons"])
    start_date = end_date - timedelta(days=config["history_days"] + maximum_horizon * 3 + 150)
    rows = session.execute(text("""
        SELECT symbol,session_date,open_price,high_price,low_price,close_price,volume
        FROM market_ohlcv_daily
        WHERE adjusted=TRUE AND close_price>0 AND volume>=:minimum_volume
          AND session_date BETWEEN :start_date AND :end_date
        ORDER BY symbol,session_date
    """), {
        "start_date": start_date, "end_date": end_date,
        "minimum_volume": config["minimum_volume"],
    }).mappings().all()
    if not rows:
        raise ValueError("No OHLCV rows matched the ML research liquidity filter.")
    base = _base_features(pd.DataFrame(rows))
    horizon_results = []
    leaderboard = []
    for horizon in config["horizons"]:
        target_return = config["target_returns"][horizon]
        data = _add_target(base, horizon, target_return)
        models = [
            _evaluate_model(name, data, config, end_date, horizon)
            for name in (*PAPER_RULES, *LEARNED_MODELS)
        ]
        horizon_results.append({
            "horizon_days": horizon,
            "target_return_pct": target_return,
            "samples": int(len(data)),
            "models": models,
        })
        leaderboard.extend(models)
    leaderboard.sort(
        key=lambda result: (
            bool(result["paper_ready"]),
            int(result["aggregate"]["positive_folds"]),
            float(result["aggregate"]["portfolio_return_pct"]),
            float(result["aggregate"]["auc"]),
        ),
        reverse=True,
    )
    eligible = [result for result in leaderboard if result["paper_ready"]]
    best = eligible[0] if eligible else None
    return {
        "config": config,
        "data_start": start_date.isoformat(),
        "data_end": end_date.isoformat(),
        "samples": max((item["samples"] for item in horizon_results), default=0),
        "symbols": int(base.symbol.nunique()),
        "models": horizon_results[0]["models"] if horizon_results else [],
        "horizon_results": horizon_results,
        "leaderboard": leaderboard,
        "best_candidate": best,
        "decision": "paper_candidate" if best else "stay_in_cash",
        "feature_columns": list(FEATURE_COLUMNS),
        "research_sources": sorted(set(MODEL_SOURCES.values())),
        "note": (
            "Paper-inspired rules and open-source models are evaluated only on later, purged "
            "chronological folds. Each fold uses non-overlapping one-stock rebalances, compounds "
            "NPR 100,000 after the configured round-trip cost, and never submits an order. "
            "A candidate must be positive in every fold and clear precision, AUC, sample-size, "
            "drawdown and worst-fold gates."
        ),
    }
