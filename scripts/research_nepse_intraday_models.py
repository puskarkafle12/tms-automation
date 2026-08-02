#!/usr/bin/env python3
"""Offline, causal NEPSE-index intraday model comparison.

The MeroLagani chart handler returns irregular index updates. This script
aggregates them into fixed five-minute bars before running expanding-window
tests. It is research-only and does not submit or simulate broker orders.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, roc_auc_score
from sklearn.preprocessing import StandardScaler
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


SEED = 20260726
HORIZON_BARS = 3
SEQUENCE_BARS = 24


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def load_bars(path: Path) -> pd.DataFrame:
    payload = json.loads(path.read_text())
    raw = pd.DataFrame({
        "timestamp": pd.to_datetime(payload["t"], unit="s", utc=True),
        "price": pd.to_numeric(pd.Series(payload["c"]), errors="coerce"),
        "turnover": pd.to_numeric(pd.Series(payload["v"]), errors="coerce").fillna(0).clip(lower=0),
    }).dropna(subset=["timestamp", "price"])
    raw["session"] = raw["timestamp"].dt.date
    raw["bucket"] = raw["timestamp"].dt.floor("5min")
    bars = raw.groupby(["session", "bucket"], observed=True).agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        turnover=("turnover", "sum"),
        updates=("price", "size"),
    ).reset_index()
    bars = bars.sort_values(["session", "bucket"]).reset_index(drop=True)
    return bars


def _session_group_rolling(series: pd.Series, sessions: pd.Series, window: int, fn: str) -> pd.Series:
    grouped = series.groupby(sessions, sort=False)
    if fn == "sum":
        return grouped.transform(lambda value: value.rolling(window, min_periods=window).sum())
    if fn == "std":
        return grouped.transform(lambda value: value.rolling(window, min_periods=window).std())
    if fn == "mean":
        return grouped.transform(lambda value: value.rolling(window, min_periods=window).mean())
    raise ValueError(fn)


def feature_frame(bars: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    frame = bars.copy()
    grouped_close = frame["close"].groupby(frame["session"], sort=False)
    frame["ret_1"] = grouped_close.pct_change()
    for lag in (2, 3, 6, 12, 24):
        frame[f"ret_{lag}"] = grouped_close.pct_change(lag)
    frame["range_pct"] = (frame["high"] - frame["low"]) / frame["close"]
    frame["body_pct"] = (frame["close"] - frame["open"]) / frame["open"]
    frame["log_turnover"] = np.log1p(frame["turnover"])
    frame["log_updates"] = np.log1p(frame["updates"])
    for window in (6, 12, 24):
        frame[f"vol_{window}"] = _session_group_rolling(frame["ret_1"], frame["session"], window, "std")
        turnover_mean = _session_group_rolling(frame["log_turnover"], frame["session"], window, "mean")
        turnover_std = _session_group_rolling(frame["log_turnover"], frame["session"], window, "std")
        frame[f"turnover_z_{window}"] = (frame["log_turnover"] - turnover_mean) / turnover_std.replace(0, np.nan)
        signed = np.sign(frame["ret_1"].fillna(0)) * frame["log_turnover"]
        frame[f"signed_flow_{window}"] = _session_group_rolling(signed, frame["session"], window, "sum")
    minute = frame["bucket"].dt.hour * 60 + frame["bucket"].dt.minute
    phase = 2 * math.pi * (minute - 315) / 240
    frame["time_sin"] = np.sin(phase)
    frame["time_cos"] = np.cos(phase)
    frame["bar_in_session"] = frame.groupby("session", sort=False).cumcount()
    frame["session_open"] = frame.groupby("session", sort=False)["open"].transform("first")
    frame["from_open"] = frame["close"] / frame["session_open"] - 1
    future_close = grouped_close.shift(-HORIZON_BARS)
    frame["forward_return"] = future_close / frame["close"] - 1
    frame["target"] = (frame["forward_return"] > 0).astype(float)
    feature_names = [
        column for column in frame.columns
        if column.startswith(("ret_", "vol_", "turnover_z_", "signed_flow_"))
    ] + [
        "range_pct", "body_pct", "log_turnover", "log_updates",
        "time_sin", "time_cos", "bar_in_session", "from_open",
    ]
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(
        subset=feature_names + ["forward_return", "target"]
    ).reset_index(drop=True)
    frame["target"] = frame["target"].astype(int)
    return frame, feature_names


def chronological_folds(size: int) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    # Three non-overlapping test eras; every fold trains only on earlier bars.
    edges = [int(size * value) for value in (0.55, 0.70, 0.85, 1.0)]
    folds = []
    for index in range(3):
        test_start, test_end = edges[index], edges[index + 1]
        validation_size = max(500, int(test_start * 0.15))
        train_end = test_start - validation_size
        folds.append((
            np.arange(0, train_end - HORIZON_BARS),
            np.arange(train_end, test_start - HORIZON_BARS),
            np.arange(test_start, test_end),
        ))
    return folds


def selective_metrics(
    probabilities: np.ndarray,
    targets: np.ndarray,
    returns: np.ndarray,
    threshold: float,
) -> dict[str, float]:
    selected = np.flatnonzero(probabilities >= threshold)
    # A signal holds for three bars, so overlapping signals are not counted.
    non_overlapping: list[int] = []
    last = -HORIZON_BARS
    for index in selected:
        if index - last >= HORIZON_BARS:
            non_overlapping.append(int(index))
            last = int(index)
    chosen = np.asarray(non_overlapping, dtype=int)
    return {
        "trades": int(len(chosen)),
        "precision": float(targets[chosen].mean()) if len(chosen) else float("nan"),
        "mean_return": float(returns[chosen].mean()) if len(chosen) else float("nan"),
        "coverage": float(len(chosen) / max(1, math.ceil(len(targets) / HORIZON_BARS))),
    }


def score_predictions(name: str, fold_rows: list[dict[str, object]]) -> dict[str, object]:
    targets = np.concatenate([row["targets"] for row in fold_rows])
    probabilities = np.concatenate([row["probabilities"] for row in fold_rows])
    returns = np.concatenate([row["returns"] for row in fold_rows])
    selected = [
        selective_metrics(row["probabilities"], row["targets"], row["returns"], row["threshold"])
        for row in fold_rows
    ]
    total_trades = sum(int(row["trades"]) for row in selected)
    weighted_precision = (
        sum(row["precision"] * row["trades"] for row in selected if row["trades"]) / total_trades
        if total_trades else float("nan")
    )
    weighted_return = (
        sum(row["mean_return"] * row["trades"] for row in selected if row["trades"]) / total_trades
        if total_trades else float("nan")
    )
    return {
        "model": name,
        "accuracy": accuracy_score(targets, probabilities >= 0.5),
        "balanced_accuracy": balanced_accuracy_score(targets, probabilities >= 0.5),
        "auc": roc_auc_score(targets, probabilities),
        "trades": total_trades,
        "selected_precision": weighted_precision,
        "selected_mean_return": weighted_return,
        "folds": selected,
    }


class TemporalConvNet(nn.Module):
    def __init__(self, feature_count: int) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Conv1d(feature_count, 48, kernel_size=3, padding=2, dilation=1),
            nn.GELU(),
            nn.Conv1d(48, 64, kernel_size=3, padding=4, dilation=2),
            nn.GELU(),
            nn.Conv1d(64, 64, kernel_size=3, padding=8, dilation=4),
            nn.GELU(),
        )
        self.head = nn.Sequential(nn.AdaptiveAvgPool1d(1), nn.Flatten(), nn.Linear(64, 1))

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return self.head(self.network(values)[..., : values.shape[-1]]).squeeze(-1)


def sequence_arrays(features: np.ndarray, indices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    valid = indices[indices >= SEQUENCE_BARS - 1]
    sequences = np.stack([features[index - SEQUENCE_BARS + 1:index + 1] for index in valid])
    return sequences.astype(np.float32), valid


def fit_tcn(
    features: np.ndarray,
    targets: np.ndarray,
    train_indices: np.ndarray,
    validation_indices: np.ndarray,
    test_indices: np.ndarray,
    device: torch.device,
) -> tuple[np.ndarray, np.ndarray]:
    train_x, train_rows = sequence_arrays(features, train_indices)
    validation_x, validation_rows = sequence_arrays(features, validation_indices)
    test_x, test_rows = sequence_arrays(features, test_indices)
    train_y = targets[train_rows].astype(np.float32)
    validation_y = targets[validation_rows].astype(np.float32)
    model = TemporalConvNet(features.shape[1]).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=7e-4, weight_decay=2e-4)
    loss_fn = nn.BCEWithLogitsLoss()
    loader = DataLoader(
        TensorDataset(torch.from_numpy(train_x), torch.from_numpy(train_y)),
        batch_size=512, shuffle=True, num_workers=0,
    )
    best_state = None
    best_loss = float("inf")
    patience = 0
    for _ in range(35):
        model.train()
        for batch_x, batch_y in loader:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(batch_x.transpose(1, 2).to(device)), batch_y.to(device))
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            val_logits = model(torch.from_numpy(validation_x).transpose(1, 2).to(device))
            val_loss = float(loss_fn(val_logits, torch.from_numpy(validation_y).to(device)).cpu())
        if val_loss < best_loss - 1e-4:
            best_loss = val_loss
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            patience = 0
        else:
            patience += 1
            if patience >= 5:
                break
    if best_state:
        model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        validation_probability = torch.sigmoid(
            model(torch.from_numpy(validation_x).transpose(1, 2).to(device))
        ).cpu().numpy()
        test_probability = torch.sigmoid(
            model(torch.from_numpy(test_x).transpose(1, 2).to(device))
        ).cpu().numpy()
    return validation_probability, test_probability


@dataclass
class ModelSpec:
    name: str
    build: object


def main() -> None:
    global HORIZON_BARS
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_json", type=Path)
    parser.add_argument("--threads", type=int, default=max(1, os.cpu_count() or 1))
    parser.add_argument("--horizon-bars", type=int, default=HORIZON_BARS)
    args = parser.parse_args()
    HORIZON_BARS = max(1, args.horizon_bars)
    seed_everything()
    bars = load_bars(args.raw_json)
    frame, feature_names = feature_frame(bars)
    x = frame[feature_names].to_numpy(dtype=np.float32)
    y = frame["target"].to_numpy()
    forward_returns = frame["forward_return"].to_numpy()
    folds = chronological_folds(len(frame))
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    print(json.dumps({
        "raw_updates": int(sum(bars["updates"])),
        "five_minute_bars": len(bars),
        "usable_rows": len(frame),
        "sessions": int(frame["session"].nunique()),
        "features": len(feature_names),
        "target": f"next {HORIZON_BARS * 5}-minute NEPSE direction",
        "positive_rate": float(y.mean()),
        "persistence_accuracy": float(accuracy_score(y, frame["ret_1"].to_numpy() > 0)),
        "torch_device": str(device),
        "cpu_threads": args.threads,
    }))

    model_specs = [
        ModelSpec("HistGradientBoosting", lambda: HistGradientBoostingClassifier(
            max_iter=350, learning_rate=0.04, max_leaf_nodes=31,
            l2_regularization=1.0, random_state=SEED,
        )),
        ModelSpec("ExtraTrees", lambda: ExtraTreesClassifier(
            n_estimators=500, min_samples_leaf=12, max_features=0.7,
            class_weight="balanced", n_jobs=args.threads, random_state=SEED,
        )),
    ]
    for spec in model_specs:
        fold_rows = []
        for train_indices, validation_indices, test_indices in folds:
            model = spec.build()
            model.fit(x[train_indices], y[train_indices])
            validation_probability = model.predict_proba(x[validation_indices])[:, 1]
            probability = model.predict_proba(x[test_indices])[:, 1]
            threshold = max(0.5, float(np.quantile(validation_probability, 0.80)))
            fold_rows.append({
                "targets": y[test_indices], "probabilities": probability,
                "returns": forward_returns[test_indices], "threshold": threshold,
            })
        print(json.dumps(score_predictions(spec.name, fold_rows)))

    tcn_rows = []
    for train_indices, validation_indices, test_indices in folds:
        scaler = StandardScaler().fit(x[train_indices])
        scaled = scaler.transform(x).astype(np.float32)
        validation_probability, probability = fit_tcn(
            scaled, y, train_indices, validation_indices, test_indices, device,
        )
        threshold = max(0.5, float(np.quantile(validation_probability, 0.80)))
        test_rows = test_indices[test_indices >= SEQUENCE_BARS - 1]
        tcn_rows.append({
            "targets": y[test_rows], "probabilities": probability,
            "returns": forward_returns[test_rows], "threshold": threshold,
        })
    print(json.dumps(score_predictions("MPS TemporalConvNet", tcn_rows)))


if __name__ == "__main__":
    main()
