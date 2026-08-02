#!/usr/bin/env python3
"""Offline, causal NEPSE market-proxy forecasting experiment.

The database currently has no official capitalization-weighted NEPSE index
history. This script therefore builds a daily equal-weight proxy from adjusted
constituent returns. It is intentionally disconnected from every order API.
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    brier_score_loss,
    precision_score,
    roc_auc_score,
)
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text
from xgboost import XGBClassifier, XGBRegressor

from database import SessionLocal


SEED = 42
FEATURES = (
    "return_1", "return_2", "return_3", "return_5", "return_10", "return_20",
    "return_60", "volatility_5", "volatility_10", "volatility_20",
    "volatility_60", "trend_vol_5", "trend_vol_20", "trend_vol_60",
    "distance_sma_10", "distance_sma_20", "distance_sma_60", "rsi_14",
    "drawdown_60", "advance_ratio", "breadth_5", "breadth_20",
    "dispersion", "dispersion_20", "volume_change_5", "constituent_change_20",
)
MODEL_NAMES = (
    "always_up",
    "time_series_momentum",
    "elastic_net",
    "random_forest",
    "hist_gradient_boosting",
    "xgboost",
    "xgboost_return",
    "regime_filtered_xgboost",
    "shallow_mlp",
    "lstm_deep_momentum",
)


@dataclass
class Split:
    train: np.ndarray
    validation: np.ndarray
    test: np.ndarray


def _load_proxy() -> pd.DataFrame:
    session = SessionLocal()
    try:
        rows = session.execute(text("""
            WITH prices AS (
                SELECT symbol, session_date, close_price, volume,
                       LAG(close_price) OVER (
                           PARTITION BY symbol ORDER BY session_date
                       ) AS prior_close
                FROM market_ohlcv_daily
                WHERE adjusted=TRUE AND close_price>0
            ), valid AS (
                SELECT symbol, session_date, volume,
                       close_price/NULLIF(prior_close,0)-1 AS stock_return
                FROM prices
                WHERE prior_close IS NOT NULL
            )
            SELECT session_date,
                   AVG(stock_return) FILTER (
                       WHERE stock_return BETWEEN -0.20 AND 0.20
                   ) AS market_return,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (
                       ORDER BY stock_return
                   ) FILTER (
                       WHERE stock_return BETWEEN -0.20 AND 0.20
                   ) AS median_return,
                   AVG(CASE WHEN stock_return>0 THEN 1.0 ELSE 0.0 END)
                       FILTER (WHERE stock_return BETWEEN -0.20 AND 0.20)
                       AS advance_ratio,
                   STDDEV_POP(stock_return)
                       FILTER (WHERE stock_return BETWEEN -0.20 AND 0.20)
                       AS dispersion,
                   SUM(volume) FILTER (WHERE volume>0) AS total_volume,
                   COUNT(*) FILTER (
                       WHERE stock_return BETWEEN -0.20 AND 0.20
                   ) AS constituents
            FROM valid
            GROUP BY session_date
            HAVING COUNT(*) FILTER (
                WHERE stock_return BETWEEN -0.20 AND 0.20
            ) >= 20
            ORDER BY session_date
        """)).mappings().all()
    finally:
        session.close()
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError("No constituent history was available for the NEPSE proxy.")
    frame["session_date"] = pd.to_datetime(frame["session_date"])
    for column in frame.columns:
        if column != "session_date":
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def _features(
    raw: pd.DataFrame, horizon: int, keep_unlabeled: bool = False,
) -> pd.DataFrame:
    data = raw.copy()
    data["index_level"] = 1000 * (1 + data["market_return"].fillna(0)).cumprod()
    log_return = np.log(data["index_level"]).diff()
    for window in (1, 2, 3, 5, 10, 20, 60):
        data[f"return_{window}"] = data["index_level"].pct_change(window)
    for window in (5, 10, 20, 60):
        data[f"volatility_{window}"] = log_return.rolling(window).std()
    for window in (5, 20, 60):
        data[f"trend_vol_{window}"] = (
            data[f"return_{window}"] / data[f"volatility_{window}"].replace(0, np.nan)
        )
    for window in (10, 20, 60):
        data[f"distance_sma_{window}"] = (
            data["index_level"] / data["index_level"].rolling(window).mean() - 1
        )
    data["rsi_14"] = _rsi(data["index_level"])
    data["drawdown_60"] = (
        data["index_level"] / data["index_level"].rolling(60).max() - 1
    )
    data["breadth_5"] = data["advance_ratio"].rolling(5).mean()
    data["breadth_20"] = data["advance_ratio"].rolling(20).mean()
    data["dispersion_20"] = data["dispersion"].rolling(20).mean()
    data["volume_change_5"] = data["total_volume"].pct_change(5)
    data["constituent_change_20"] = data["constituents"].pct_change(20)
    # A signal calculated after close t is conservatively entered at close t+1.
    data["future_return"] = (
        data["index_level"].shift(-(horizon + 1))
        / data["index_level"].shift(-1) - 1
    )
    data["target"] = np.where(
        data["future_return"].notna(),
        (data["future_return"] > 0).astype(int),
        np.nan,
    )
    required = list(FEATURES)
    if not keep_unlabeled:
        required.append("future_return")
    return data.replace([np.inf, -np.inf], np.nan).dropna(
        subset=required
    ).reset_index(drop=True)


def _splits(length: int, folds: int, test_size: int, validation_size: int, embargo: int) -> Iterable[Split]:
    for offset in range(folds, 0, -1):
        test_end = length - test_size * (offset - 1)
        test_start = test_end - test_size
        validation_end = test_start - embargo
        validation_start = validation_end - validation_size
        train_end = validation_start - embargo
        if train_end < 750:
            continue
        yield Split(
            train=np.arange(0, train_end),
            validation=np.arange(validation_start, validation_end),
            test=np.arange(test_start, test_end),
        )


def _model(name: str):
    if name == "elastic_net":
        return make_pipeline(
            SimpleImputer(strategy="median"), StandardScaler(),
            LogisticRegression(
                penalty="elasticnet", solver="saga", l1_ratio=0.2, C=0.08,
                class_weight="balanced", max_iter=500, random_state=SEED,
            ),
        )
    if name == "random_forest":
        return make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(
                n_estimators=300, max_depth=5, min_samples_leaf=35,
                max_features=0.65, class_weight="balanced_subsample",
                n_jobs=2, random_state=SEED,
            ),
        )
    if name == "hist_gradient_boosting":
        return make_pipeline(
            SimpleImputer(strategy="median"),
            HistGradientBoostingClassifier(
                learning_rate=0.025, max_leaf_nodes=9, min_samples_leaf=40,
                l2_regularization=8, max_iter=220, random_state=SEED,
            ),
        )
    if name in ("xgboost", "regime_filtered_xgboost"):
        return make_pipeline(
            SimpleImputer(strategy="median"),
            XGBClassifier(
                n_estimators=260, max_depth=2, learning_rate=0.02,
                min_child_weight=35, subsample=0.8, colsample_bytree=0.7,
                reg_alpha=2, reg_lambda=15, objective="binary:logistic",
                eval_metric="logloss", n_jobs=2, tree_method="hist",
                random_state=SEED,
            ),
        )
    if name == "xgboost_return":
        return make_pipeline(
            SimpleImputer(strategy="median"),
            XGBRegressor(
                n_estimators=260, max_depth=2, learning_rate=0.02,
                min_child_weight=35, subsample=0.8, colsample_bytree=0.7,
                reg_alpha=2, reg_lambda=15, objective="reg:squarederror",
                n_jobs=2, tree_method="hist", random_state=SEED,
            ),
        )
    return make_pipeline(
        SimpleImputer(strategy="median"), StandardScaler(),
        MLPClassifier(
            hidden_layer_sizes=(32, 12), activation="tanh", alpha=0.03,
            batch_size=128, learning_rate_init=0.0007, max_iter=160,
            early_stopping=True, validation_fraction=0.15,
            n_iter_no_change=12, random_state=SEED,
        ),
    )


def _rule_score(name: str, data: pd.DataFrame) -> np.ndarray:
    if name == "always_up":
        return np.full(len(data), 0.5001)
    trend = data["trend_vol_20"].clip(-8, 8).to_numpy()
    return 1 / (1 + np.exp(-trend))


def _lstm_scores(
    frame: pd.DataFrame, split: Split, sequence: int = 60,
) -> Tuple[np.ndarray, np.ndarray]:
    try:
        import torch
        from torch import nn
    except ImportError as exc:
        raise RuntimeError(
            "PyTorch is required only for the offline LSTM comparison."
        ) from exc
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    scaler = StandardScaler().fit(frame.loc[split.train, FEATURES])
    matrix = scaler.transform(frame[list(FEATURES)]).astype("float32")
    target = frame["target"].to_numpy(dtype="float32")

    def sequences(indices: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        usable = indices[indices >= sequence - 1]
        x = np.stack([matrix[index - sequence + 1:index + 1] for index in usable])
        return x, target[usable]

    x_train, y_train = sequences(split.train)
    x_validation, y_validation = sequences(split.validation)
    x_test, _ = sequences(split.test)

    class DirectionLstm(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.lstm = nn.LSTM(len(FEATURES), 24, batch_first=True)
            self.head = nn.Sequential(nn.Linear(24, 12), nn.Tanh(), nn.Linear(12, 1))

        def forward(self, value):
            encoded, _ = self.lstm(value)
            return self.head(encoded[:, -1]).squeeze(-1)

    network = DirectionLstm()
    positives = max(1.0, float(y_train.sum()))
    negative = max(1.0, float(len(y_train) - y_train.sum()))
    loss_function = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor(negative / positives, dtype=torch.float32)
    )
    optimizer = torch.optim.AdamW(network.parameters(), lr=0.001, weight_decay=0.02)
    train_x = torch.tensor(x_train)
    train_y = torch.tensor(y_train)
    validation_x = torch.tensor(x_validation)
    validation_y = torch.tensor(y_validation)
    best_loss = math.inf
    best_state = None
    stale = 0
    for _ in range(45):
        network.train()
        order = torch.randperm(len(train_x))
        for start in range(0, len(order), 128):
            batch = order[start:start + 128]
            optimizer.zero_grad()
            loss = loss_function(network(train_x[batch]), train_y[batch])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(network.parameters(), 1.0)
            optimizer.step()
        network.eval()
        with torch.no_grad():
            validation_loss = float(
                loss_function(network(validation_x), validation_y).item()
            )
        if validation_loss < best_loss - 1e-4:
            best_loss = validation_loss
            best_state = {
                key: value.detach().clone() for key, value in network.state_dict().items()
            }
            stale = 0
        else:
            stale += 1
            if stale >= 7:
                break
    if best_state:
        network.load_state_dict(best_state)
    network.eval()
    with torch.no_grad():
        validation_scores = torch.sigmoid(network(validation_x)).numpy()
        test_scores = torch.sigmoid(network(torch.tensor(x_test))).numpy()
    return validation_scores, test_scores


def _trading_metrics(
    frame: pd.DataFrame,
    indices: np.ndarray,
    scores: np.ndarray,
    threshold: float,
    horizon: int,
    cost: float,
) -> Dict[str, float | int]:
    positions = scores >= threshold
    sampled = np.arange(0, len(indices), horizon)
    selected = sampled[positions[sampled]]
    returns = frame.loc[indices[selected], "future_return"].to_numpy() - cost
    equity = np.cumprod(1 + returns) if len(returns) else np.array([1.0])
    peaks = np.maximum.accumulate(equity)
    drawdown = equity / peaks - 1
    return {
        "trades": int(len(returns)),
        "strategy_return_pct": round(100 * float(equity[-1] - 1), 3),
        "average_trade_pct": round(100 * float(returns.mean()), 3) if len(returns) else 0.0,
        "trade_win_rate_pct": round(100 * float((returns > 0).mean()), 2) if len(returns) else 0.0,
        "maximum_drawdown_pct": round(100 * abs(float(drawdown.min())), 3),
        "exposure_pct": round(100 * float(positions.mean()), 2),
    }


def _threshold(
    frame: pd.DataFrame,
    indices: np.ndarray,
    scores: np.ndarray,
    horizon: int,
    cost: float,
) -> float:
    best = (float("-inf"), 0.55)
    for threshold in np.arange(0.50, 0.701, 0.025):
        metrics = _trading_metrics(frame, indices, scores, threshold, horizon, cost)
        if metrics["trades"] < 3:
            continue
        objective = (
            float(metrics["strategy_return_pct"])
            - 0.5 * float(metrics["maximum_drawdown_pct"])
        )
        if objective > best[0]:
            best = (objective, float(threshold))
    return best[1]


def _classification(target: np.ndarray, scores: np.ndarray) -> Dict[str, float]:
    predicted = scores >= 0.5
    return {
        "accuracy_pct": round(100 * accuracy_score(target, predicted), 2),
        "balanced_accuracy_pct": round(
            100 * balanced_accuracy_score(target, predicted), 2
        ),
        "precision_pct": round(
            100 * precision_score(target, predicted, zero_division=0), 2
        ),
        "auc": round(float(roc_auc_score(target, scores)), 4),
        "brier": round(float(brier_score_loss(target, scores)), 4),
        "up_rate_pct": round(100 * float(target.mean()), 2),
    }


def run(folds: int, test_size: int, validation_size: int, cost_pct: float) -> Dict[str, Any]:
    raw = _load_proxy()
    results = []
    try:
        import torch  # noqa: F401
        torch_available = True
    except ImportError:
        torch_available = False
    for horizon in (1, 5, 10, 20):
        frame = _features(raw, horizon)
        for name in MODEL_NAMES:
            if name == "lstm_deep_momentum" and not torch_available:
                continue
            fold_results = []
            for split in _splits(
                len(frame), folds, test_size, validation_size, embargo=horizon + 2
            ):
                if name in ("always_up", "time_series_momentum"):
                    validation_scores = _rule_score(name, frame.loc[split.validation])
                    test_scores = _rule_score(name, frame.loc[split.test])
                elif name == "lstm_deep_momentum":
                    validation_scores, test_scores = _lstm_scores(frame, split)
                else:
                    model = _model(name)
                    training_target = (
                        frame.loc[split.train, "future_return"]
                        if name == "xgboost_return"
                        else frame.loc[split.train, "target"]
                    )
                    model.fit(frame.loc[split.train, FEATURES], training_target)
                    if name == "xgboost_return":
                        scale = max(
                            1e-5,
                            float(frame.loc[split.train, "future_return"].std()),
                        )
                        validation_prediction = model.predict(
                            frame.loc[split.validation, FEATURES]
                        )
                        test_prediction = model.predict(frame.loc[split.test, FEATURES])
                        validation_scores = 1 / (1 + np.exp(-validation_prediction / scale))
                        test_scores = 1 / (1 + np.exp(-test_prediction / scale))
                    else:
                        validation_scores = model.predict_proba(
                            frame.loc[split.validation, FEATURES]
                        )[:, 1]
                        test_scores = model.predict_proba(
                            frame.loc[split.test, FEATURES]
                        )[:, 1]
                    if name == "regime_filtered_xgboost":
                        validation_regime = (
                            (frame.loc[split.validation, "return_20"].to_numpy() > 0)
                            & (frame.loc[split.validation, "breadth_5"].to_numpy() >= 0.5)
                        )
                        test_regime = (
                            (frame.loc[split.test, "return_20"].to_numpy() > 0)
                            & (frame.loc[split.test, "breadth_5"].to_numpy() >= 0.5)
                        )
                        validation_scores = np.where(
                            validation_regime, validation_scores, 0.0
                        )
                        test_scores = np.where(test_regime, test_scores, 0.0)
                threshold = _threshold(
                    frame, split.validation, validation_scores, horizon, cost_pct / 100
                )
                fold_results.append({
                    "test_start": frame.loc[split.test[0], "session_date"].date().isoformat(),
                    "test_end": frame.loc[split.test[-1], "session_date"].date().isoformat(),
                    "threshold": round(threshold, 3),
                    **_classification(
                        frame.loc[split.test, "target"].to_numpy(), test_scores
                    ),
                    **_trading_metrics(
                        frame, split.test, test_scores, threshold,
                        horizon, cost_pct / 100,
                    ),
                })
            positive = sum(
                float(item["strategy_return_pct"]) > 0 for item in fold_results
            )
            mean = lambda key: round(
                float(np.mean([float(item[key]) for item in fold_results])), 3
            )
            results.append({
                "model": name,
                "horizon_sessions": horizon,
                "folds": fold_results,
                "aggregate": {
                    "positive_folds": positive,
                    "fold_count": len(fold_results),
                    "accuracy_pct": mean("accuracy_pct"),
                    "balanced_accuracy_pct": mean("balanced_accuracy_pct"),
                    "precision_pct": mean("precision_pct"),
                    "auc": mean("auc"),
                    "brier": mean("brier"),
                    "strategy_return_pct": mean("strategy_return_pct"),
                    "trade_win_rate_pct": mean("trade_win_rate_pct"),
                    "maximum_drawdown_pct": mean("maximum_drawdown_pct"),
                    "trades": int(sum(int(item["trades"]) for item in fold_results)),
                },
            })
    results.sort(
        key=lambda item: (
            item["aggregate"]["positive_folds"],
            item["aggregate"]["strategy_return_pct"],
            item["aggregate"]["balanced_accuracy_pct"],
        ),
        reverse=True,
    )
    development_folds = max(1, folds - 1)
    development_ranking = sorted(
        results,
        key=lambda item: (
            sum(float(fold["strategy_return_pct"]) > 0 for fold in item["folds"][:development_folds]),
            float(np.mean([
                float(fold["strategy_return_pct"])
                for fold in item["folds"][:development_folds]
            ])),
        ),
        reverse=True,
    )
    selected = development_ranking[0]
    final_holdout = selected["folds"][-1]
    confirmed = (
        float(final_holdout["strategy_return_pct"]) > 0
        and float(final_holdout["balanced_accuracy_pct"]) >= 52
        and int(final_holdout["trades"]) >= 5
    )
    return {
        "series": {
            "name": "Causal NEPSE listed-share equal-weight proxy",
            "official_index": False,
            "start": raw.session_date.min().date().isoformat(),
            "end": raw.session_date.max().date().isoformat(),
            "sessions": int(len(raw)),
            "method": (
                "Daily mean adjusted constituent return using only same-date available "
                "stocks; returns outside ±20% are excluded as likely data/corporate-action "
                "artifacts. Includes causal breadth, dispersion and volume."
            ),
        },
        "evaluation": {
            "folds": folds,
            "test_sessions_per_fold": test_size,
            "validation_sessions_per_fold": validation_size,
            "round_trip_cost_pct": cost_pct,
            "execution": "Signal after close t; proxy entry at close t+1.",
            "lstm_included": torch_available,
        },
        "leaderboard": results,
        "development_selected": {
            "model": selected["model"],
            "horizon_sessions": selected["horizon_sessions"],
            "final_holdout": final_holdout,
            "confirmed": confirmed,
        },
        "decision": "candidate_for_forward_paper_test" if confirmed else "no_model_confirmed",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--test-size", type=int, default=126)
    parser.add_argument("--validation-size", type=int, default=252)
    parser.add_argument("--cost-pct", type=float, default=1.1)
    parser.add_argument("--output")
    args = parser.parse_args()
    warnings.filterwarnings("ignore", category=UserWarning)
    result = run(args.folds, args.test_size, args.validation_size, args.cost_pct)
    rendered = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)
    print(rendered)


if __name__ == "__main__":
    main()
