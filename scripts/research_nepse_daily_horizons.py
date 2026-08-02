#!/usr/bin/env python3
"""Research-only NEPSE daily direction models across training lookbacks.

Input is the JSON returned by MeroLagani's advanced chart handler for the
official NEPSE index at 1D resolution. Evaluation is purged, expanding
walk-forward and never touches an order API.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from functools import partial
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
    VotingClassifier,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, roc_auc_score
from sklearn.feature_selection import SelectKBest, mutual_info_classif
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


SEED = 20260726
TEST_SIZE = 126
TEST_FOLDS = 8
VALIDATION_SIZE = 126
LOOKBACKS = {
    "1_year": 252,
    "2_years": 504,
    "4_years": 1008,
    "8_years": 2016,
    "full_history": None,
}
VOLUME_FEATURE_MARKERS = (
    "volume", "turnover", "mfi", "obv", "accumulation_distribution",
    "cmf", "force_index", "vwap",
)


def load_daily(path: Path) -> pd.DataFrame:
    payload = json.loads(path.read_text())
    frame = pd.DataFrame({
        "date": pd.to_datetime(payload["t"], unit="s", utc=True),
        "open": pd.to_numeric(pd.Series(payload["o"]), errors="coerce"),
        "high": pd.to_numeric(pd.Series(payload["h"]), errors="coerce"),
        "low": pd.to_numeric(pd.Series(payload["l"]), errors="coerce"),
        "close": pd.to_numeric(pd.Series(payload["c"]), errors="coerce"),
        "volume": pd.to_numeric(pd.Series(payload["v"]), errors="coerce"),
    }).sort_values("date").drop_duplicates("date", keep="last")
    return frame.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    change = series.diff()
    gain = change.clip(lower=0).rolling(window).mean()
    loss = (-change.clip(upper=0)).rolling(window).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def make_features(raw: pd.DataFrame, horizon: int) -> tuple[pd.DataFrame, list[str]]:
    frame = raw.copy()
    frame["volume_missing"] = frame["volume"].isna() | frame["volume"].le(0)
    frame["volume"] = frame["volume"].fillna(0).clip(lower=0)
    frame["return_1"] = frame["close"].pct_change()
    for window in (2, 3, 5, 10, 20, 60):
        frame[f"return_{window}"] = frame["close"].pct_change(window)
    frame["gap"] = frame["open"] / frame["close"].shift(1) - 1
    frame["body"] = frame["close"] / frame["open"] - 1
    frame["range"] = (frame["high"] - frame["low"]) / frame["close"]
    frame["close_location"] = (
        (frame["close"] - frame["low"])
        / (frame["high"] - frame["low"]).replace(0, np.nan)
    )
    log_return = np.log(frame["close"]).diff()
    for window in (5, 10, 20, 60):
        frame[f"volatility_{window}"] = log_return.rolling(window).std()
        frame[f"distance_sma_{window}"] = frame["close"] / frame["close"].rolling(window).mean() - 1
    frame["rsi_14"] = rsi(frame["close"])
    frame["drawdown_60"] = frame["close"] / frame["close"].rolling(60).max() - 1

    frame["log_volume"] = np.log1p(frame["volume"])
    for window in (1, 5, 20):
        # Log differences remain finite across old sessions where the source
        # reports zero/missing turnover; the explicit flag preserves that fact.
        frame[f"volume_change_{window}"] = frame["log_volume"].diff(window)
    for window in (20, 60):
        mean = frame["log_volume"].rolling(window).mean()
        std = frame["log_volume"].rolling(window).std()
        frame[f"volume_z_{window}"] = (frame["log_volume"] - mean) / std.replace(0, np.nan)
        frame[f"price_volume_corr_{window}"] = (
            frame["return_1"].rolling(window).corr(frame["log_volume"].diff())
        )
    signed_volume = np.sign(frame["return_1"].fillna(0)) * frame["log_volume"]
    frame["signed_volume_5"] = signed_volume.rolling(5).sum()
    frame["signed_volume_20"] = signed_volume.rolling(20).sum()
    frame["future_return"] = frame["close"].shift(-horizon) / frame["close"] - 1
    frame["target"] = (frame["future_return"] > 0).astype(int)

    features = [
        column for column in frame.columns
        if column.startswith((
            "return_", "volatility_", "distance_sma_", "volume_change_",
            "volume_z_", "price_volume_corr_", "signed_volume_",
        ))
    ] + [
        "gap", "body", "range", "close_location", "rsi_14", "drawdown_60",
        "log_volume", "volume_missing",
    ]
    features.extend(column for column in frame.columns if column.startswith("xs_"))
    # Old index sessions legitimately lack volume. Keep them for long-history
    # evaluation and fit every imputer on its training fold only.
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["future_return"]
    ).reset_index(drop=True)
    return frame, features


def model_factories(threads: int) -> dict[str, Callable[[], object]]:
    factories: dict[str, Callable[[], object]] = {
        "logistic": lambda: make_pipeline(
            SimpleImputer(strategy="median"), StandardScaler(),
            LogisticRegression(
                C=0.08, class_weight="balanced", max_iter=1000, random_state=SEED,
            ),
        ),
        "hist_gradient_boosting": lambda: make_pipeline(
            SimpleImputer(strategy="median"),
            HistGradientBoostingClassifier(
                max_iter=300, learning_rate=0.035, max_leaf_nodes=15,
                min_samples_leaf=30, l2_regularization=6, random_state=SEED,
            ),
        ),
        "extra_trees": lambda: make_pipeline(
            SimpleImputer(strategy="median"),
            ExtraTreesClassifier(
                n_estimators=600, max_depth=8, min_samples_leaf=18,
                max_features=0.7, class_weight="balanced", n_jobs=threads,
                random_state=SEED,
            ),
        ),
        "random_forest": lambda: make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(
                n_estimators=600, max_depth=8, min_samples_leaf=18,
                max_features=0.7, class_weight="balanced_subsample",
                n_jobs=threads, random_state=SEED,
            ),
        ),
    }
    try:
        from catboost import CatBoostClassifier
        factories["catboost"] = lambda: CatBoostClassifier(
            iterations=350, depth=5, learning_rate=0.025, l2_leaf_reg=8,
            loss_function="Logloss", verbose=False, thread_count=threads,
            random_seed=SEED, allow_writing_files=False,
        )
        factories["soft_voting"] = lambda: VotingClassifier(
            estimators=[
                ("extra_trees", make_pipeline(
                    SimpleImputer(strategy="median"),
                    ExtraTreesClassifier(
                        n_estimators=600, max_depth=8, min_samples_leaf=18,
                        max_features=0.7, class_weight="balanced", n_jobs=threads,
                        random_state=SEED,
                    ),
                )),
                ("catboost", CatBoostClassifier(
                    iterations=350, depth=5, learning_rate=0.025, l2_leaf_reg=8,
                    loss_function="Logloss", verbose=False, thread_count=threads,
                    random_seed=SEED, allow_writing_files=False,
                )),
            ],
            voting="soft",
        )
    except Exception:
        pass
    try:
        from xgboost import XGBClassifier
        def xgboost_model():
            return XGBClassifier(
                n_estimators=400, max_depth=3, learning_rate=0.025,
                min_child_weight=20, subsample=0.8, colsample_bytree=0.75,
                reg_alpha=2, reg_lambda=12, objective="binary:logistic",
                eval_metric="logloss", tree_method="hist", n_jobs=threads,
                random_state=SEED,
            )
        factories["xgboost"] = xgboost_model
        for feature_count in (24, 48, 96):
            factories[f"xgboost_mi_{feature_count}"] = (
                lambda count=feature_count: make_pipeline(
                    SimpleImputer(strategy="median"),
                    SelectKBest(
                        score_func=partial(mutual_info_classif, random_state=SEED),
                        k=count,
                    ),
                    xgboost_model(),
                )
            )
    except Exception:
        pass
    try:
        from lightgbm import LGBMClassifier
        factories["lightgbm"] = lambda: LGBMClassifier(
            n_estimators=500, num_leaves=15, learning_rate=0.02,
            min_child_samples=35, subsample=0.8, colsample_bytree=0.75,
            reg_alpha=2, reg_lambda=12, class_weight="balanced",
            n_jobs=threads, random_state=SEED, verbosity=-1,
        )
    except Exception:
        pass
    return factories


def splits(size: int, horizon: int, lookback: int | None):
    first_test = size - TEST_SIZE * TEST_FOLDS
    for fold in range(TEST_FOLDS):
        test_start = first_test + fold * TEST_SIZE
        test_end = test_start + TEST_SIZE
        validation_end = test_start - horizon
        validation_start = validation_end - VALIDATION_SIZE
        train_end = validation_start - horizon
        train_start = 0 if lookback is None else max(0, train_end - lookback)
        if train_end - train_start < 240:
            continue
        yield (
            np.arange(train_start, train_end),
            np.arange(validation_start, validation_end),
            np.arange(test_start, test_end),
        )


def selected_metrics(
    probabilities: np.ndarray,
    targets: np.ndarray,
    returns: np.ndarray,
    threshold: float,
    horizon: int,
) -> dict[str, float | int]:
    candidates = np.flatnonzero(probabilities >= threshold)
    selected: list[int] = []
    prior = -horizon
    for index in candidates:
        if index - prior >= horizon:
            selected.append(int(index))
            prior = int(index)
    chosen = np.asarray(selected, dtype=int)
    return {
        "signals": len(chosen),
        "precision": float(targets[chosen].mean()) if len(chosen) else math.nan,
        "average_move": float(returns[chosen].mean()) if len(chosen) else math.nan,
    }


def evaluate(
    frame: pd.DataFrame,
    features: list[str],
    horizon: int,
    lookback_name: str,
    lookback: int | None,
    model_name: str,
    factory: Callable[[], object],
) -> dict[str, object]:
    fold_results = []
    all_targets = []
    all_probabilities = []
    for train, validation, test in splits(len(frame), horizon, lookback):
        model = factory()
        model.fit(frame.loc[train, features], frame.loc[train, "target"])
        validation_probability = model.predict_proba(frame.loc[validation, features])[:, 1]
        probability = model.predict_proba(frame.loc[test, features])[:, 1]
        threshold = max(0.5, float(np.quantile(validation_probability, 0.80)))
        metrics = selected_metrics(
            probability,
            frame.loc[test, "target"].to_numpy(),
            frame.loc[test, "future_return"].to_numpy(),
            threshold,
            horizon,
        )
        fold_results.append({
            "start": frame.loc[test[0], "date"].date().isoformat(),
            "end": frame.loc[test[-1], "date"].date().isoformat(),
            "accuracy": float(accuracy_score(frame.loc[test, "target"], probability >= 0.5)),
            "balanced_accuracy": float(
                balanced_accuracy_score(frame.loc[test, "target"], probability >= 0.5)
            ),
            "auc": float(roc_auc_score(frame.loc[test, "target"], probability)),
            **metrics,
        })
        all_targets.append(frame.loc[test, "target"].to_numpy())
        all_probabilities.append(probability)
    targets = np.concatenate(all_targets)
    probabilities = np.concatenate(all_probabilities)
    signals = sum(int(item["signals"]) for item in fold_results)
    precision = (
        sum(float(item["precision"]) * int(item["signals"]) for item in fold_results if item["signals"])
        / signals if signals else math.nan
    )
    average_move = (
        sum(float(item["average_move"]) * int(item["signals"]) for item in fold_results if item["signals"])
        / signals if signals else math.nan
    )
    return {
        "model": model_name,
        "lookback": lookback_name,
        "horizon_sessions": horizon,
        "accuracy": float(accuracy_score(targets, probabilities >= 0.5)),
        "balanced_accuracy": float(balanced_accuracy_score(targets, probabilities >= 0.5)),
        "auc": float(roc_auc_score(targets, probabilities)),
        "signals": signals,
        "selected_precision": precision,
        "selected_average_move": average_move,
        "positive_signal_folds": sum(
            bool(item["signals"]) and float(item["average_move"]) > 0 for item in fold_results
        ),
        "folds": fold_results,
    }


def main() -> None:
    global TEST_FOLDS
    parser = argparse.ArgumentParser()
    parser.add_argument("daily_json", type=Path)
    parser.add_argument("--threads", type=int, default=max(1, os.cpu_count() or 1))
    parser.add_argument("--models", default="")
    parser.add_argument("--exclude-volume", action="store_true")
    parser.add_argument("--test-folds", type=int, default=TEST_FOLDS)
    parser.add_argument("--lookbacks", default="")
    parser.add_argument("--horizons", default="1,5")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--feature-matrix", type=Path)
    args = parser.parse_args()
    TEST_FOLDS = max(1, args.test_folds)
    raw = load_daily(args.daily_json)
    if args.feature_matrix:
        extra = pd.read_csv(args.feature_matrix)
        raw["_session_date"] = raw["date"].dt.date
        extra["_session_date"] = pd.to_datetime(
            extra.pop("session_date")
        ).dt.date
        raw = raw.merge(extra, on="_session_date", how="left").drop(
            columns=["_session_date"]
        )
    factories = model_factories(args.threads)
    requested = {item.strip() for item in args.models.split(",") if item.strip()}
    if requested:
        factories = {name: value for name, value in factories.items() if name in requested}
    requested_lookbacks = {
        item.strip() for item in args.lookbacks.split(",") if item.strip()
    }
    lookbacks = {
        name: value for name, value in LOOKBACKS.items()
        if not requested_lookbacks or name in requested_lookbacks
    }
    horizons = tuple(
        int(item.strip()) for item in args.horizons.split(",") if item.strip()
    )
    results = []
    for horizon in horizons:
        frame, features = make_features(raw, horizon)
        if args.exclude_volume:
            features = [
                feature for feature in features
                if not any(marker in feature for marker in VOLUME_FEATURE_MARKERS)
            ]
        for lookback_name, lookback in lookbacks.items():
            for model_name, factory in factories.items():
                result = evaluate(
                    frame, features, horizon, lookback_name, lookback, model_name, factory,
                )
                results.append(result)
                print(json.dumps({key: value for key, value in result.items() if key != "folds"}), flush=True)
    payload = {
        "data": {
            "symbol": "NEPSE",
            "official_index": True,
            "start": raw["date"].min().date().isoformat(),
            "end": raw["date"].max().date().isoformat(),
            "sessions": len(raw),
            "volume_sessions": int(raw["volume"].fillna(0).gt(0).sum()),
        },
        "evaluation": {
            "test_folds": TEST_FOLDS,
            "sessions_per_fold": TEST_SIZE,
            "validation_sessions": VALIDATION_SIZE,
            "selection": "top 20% validation probability, at least 0.50",
            "costs": "not applied because the NEPSE index is not directly tradable",
        },
        "results": sorted(
            results,
            key=lambda row: (
                row["positive_signal_folds"],
                row["selected_precision"],
                row["balanced_accuracy"],
            ),
            reverse=True,
        ),
    }
    if args.output:
        args.output.write_text(json.dumps(payload, indent=2))
    print("BEST")
    for horizon in horizons:
        candidates = [row for row in payload["results"] if row["horizon_sessions"] == horizon]
        print(json.dumps({key: value for key, value in candidates[0].items() if key != "folds"}))


if __name__ == "__main__":
    main()
