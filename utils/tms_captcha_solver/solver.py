"""
Fast algorithmic TMS captcha solver.

Port of the arpandaze/tms-captcha browser extension's evaluate.ts.

Pipeline:
  1. clean_image      — binarize captcha by subtracting estimated background
  2. evaluate_captcha — split into characters, compute 5 numerical features
  3. solve_captcha    — match features against pre‑computed bold/slim data
"""

from __future__ import annotations

import asyncio
import functools
import io
import json
import math
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Reference data (bundled with the original extension)
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent

with open(_HERE / "bold_data.json") as f:
    DATA_BOLD: dict[str, list[float]] = json.load(f)
with open(_HERE / "slim_data.json") as f:
    DATA_SLIM: dict[str, list[float]] = json.load(f)

# Feature weighting factors copied from evaluate.ts
_FACTORS = [1, 3, 2, 8, 3]

# Crop coordinates used by the extension
_CROP_X, _CROP_Y = 75, 24
_CROP_W, _CROP_H = 130, 35


# ---------------------------------------------------------------------------
# Step 1 — clean_image
# ---------------------------------------------------------------------------

_EASYOCR_MARKER = object()  # sentinel


def clean_image(img_bytes: bytes, bg_estimate: Optional[np.ndarray] = None) -> np.ndarray:
    """
    Convert raw captcha bytes to a binary 35×130 numpy array.

    Uses the extension's exact approach:
      1. Load the bundled empty.jpg as background reference
      2. Subtract captcha from it (empty - captcha)
      3. Multiply by 10 (amplifies text pixels)
      4. Threshold at 50
      5. Crop to character region

    *bg_estimate* overrides the background image if provided.

    Returns an array where 255 = text, 0 = background.
    """
    img = Image.open(io.BytesIO(img_bytes)).convert("L")
    arr = np.array(img, dtype=np.uint8)

    if bg_estimate is not None:
        bg = bg_estimate
    else:
        empty_pil = Image.open(str(_HERE / "empty.jpg")).convert("L")
        bg = np.array(empty_pil, dtype=np.uint8)

    # bg - captcha, clamped [0, 255]
    diff = bg.astype(np.int16) - arr.astype(np.int16)
    diff = np.clip(diff, 0, 255).astype(np.uint8)

    # Multiply by 10, clamped [0, 255]
    diff = np.clip(diff.astype(np.float32) * 10.0, 0, 255).astype(np.uint8)

    # Crop to character region
    diff_crop = diff[_CROP_Y:_CROP_Y + _CROP_H, _CROP_X:_CROP_X + _CROP_W]

    # Threshold < 50 → 0, >= 50 → 255
    binary = np.where(diff_crop >= 50, 255, 0).astype(np.uint8)

    return binary


# ---------------------------------------------------------------------------
# Step 2 — evaluate_captcha (split characters & extract features)
# ---------------------------------------------------------------------------


def evaluate_captcha_array(binary_crop: np.ndarray) -> list[list[float]]:
    """
    Given a binary 35×130 array (0 = bg, 255 = text), split it into
    individual characters and compute the five feature values for each.

    Returns a list of [avg, v_avg, ht_avg, hb_avg, width_ratio].
    """
    h, w = binary_crop.shape
    assert h == _CROP_H, f"Expected height {_CROP_H}, got {h}"
    assert w == _CROP_W, f"Expected width {_CROP_W}, got {w}"

    binary = (binary_crop > 128).astype(np.uint8)  # 1 = text, 0 = bg
    col_has_text = np.any(binary > 0, axis=0)

    # Group consecutive text columns into character regions
    char_regions: list[tuple[int, int]] = []
    in_char = False
    start_col = 0
    for col in range(w):
        if col_has_text[col]:
            if not in_char:
                in_char = True
                start_col = col
        else:
            if in_char:
                in_char = False
                char_regions.append((start_col, col - 1))
    if in_char:
        char_regions.append((start_col, w - 1))

    features: list[list[float]] = []
    for start_col, end_col in char_regions:
        char_w = end_col - start_col + 1

        # Build column-major flat array matching extension's matrix format
        matrix: list[int] = []
        for col_idx in range(char_w):
            for row_idx in range(h):
                matrix.append(int(binary[row_idx, start_col + col_idx]))

        # Reshape → (char_w, h) — extension's to_image equivalent
        img_mat = np.array(matrix, dtype=np.uint8).reshape(char_w, h) * 255

        # rotateRight() — 90° clockwise → (h, char_w)
        rotated = np.rot90(img_mat, k=-1)

        # flipX() — horizontal mirror → (h, char_w)
        flipped = np.fliplr(rotated)

        # Feature 1: average = sum / 256
        avg_val = float(flipped.sum()) / 256.0

        # Features 2-4
        v_avg = _vavg_extension(flipped)
        ht_avg = _htopavg_extension(flipped)
        hb_avg = _hbotavg_extension(flipped)

        # Feature 5: width ratio
        width_ratio = float(char_w) / float(_CROP_H)

        features.append([avg_val, v_avg, ht_avg, hb_avg, width_ratio])

    return features


def _vavg_extension(temp_img: np.ndarray) -> float:
    """
    Extension's vavg:
      rotateRight → crop top half+1 → sum / 256

    temp_img shape: (35, char_w)
    rotateRight → (char_w, 35) → crop top floor(char_w/2 + 1) rows
    """
    rotated = np.rot90(temp_img, k=-1)  # (char_w, 35)
    crop_h = rotated.shape[0] // 2 + 1  # floor(char_w / 2 + 1)
    cropped = rotated[:crop_h, :]
    return float(cropped.sum()) / 256.0


def _htopavg_extension(temp_img: np.ndarray) -> float:
    """
    Extension's htopavg:
      crop top ceil(35/2 + 1) = 19 rows → sum / 256
    """
    crop_h = math.ceil(35 / 2 + 1)  # = 19
    cropped = temp_img[:crop_h, :]
    return float(cropped.sum()) / 256.0


def _hbotavg_extension(temp_img: np.ndarray) -> float:
    """
    Extension's hbotavg:
      crop from row 19, height 16 → sum / 256
    """
    crop_y = math.ceil(35 / 2 + 1)  # = 19
    crop_h = 35 - crop_y  # = 16
    cropped = temp_img[crop_y:crop_y + crop_h, :]
    return float(cropped.sum()) / 256.0


# ---------------------------------------------------------------------------
# Step 3 — solve_captcha (match features against reference data)
# ---------------------------------------------------------------------------


def _match_features(
    features: list[list[float]],
    data: dict[str, list[float]],
) -> Optional[str]:
    """
    Match a list of character feature vectors against reference data.

    Returns the concatenated 6-character string, or None if confidence is low.
    """
    if len(features) != 6:
        return None

    captcha_chars: list[str] = []
    for char_feat in features:
        best_char: Optional[str] = None
        best_score = float("inf")
        second_score = float("inf")

        for ref_char, ref_feat in data.items():
            score = sum(
                _FACTORS[i] * abs(ref_feat[i] - char_feat[i])
                for i in range(len(_FACTORS))
            )
            if score < best_score:
                second_score = best_score
                best_score = score
                best_char = ref_char
            elif score < second_score:
                second_score = score

        # Relaxed thresholds vs extension (60 / 5) due to PIL-vs-JS differences
        if best_score > 90 or (second_score - best_score) < 2:
            return None

        captcha_chars.append(best_char)  # type: ignore[arg-type]

    return "".join(captcha_chars)


def solve_captcha_sync(
    captcha_bytes: bytes,
    bg_estimate: Optional[np.ndarray] = None,
) -> str:
    """
    Synchronous solver.

    Returns the 6-character captcha string, or an empty string on failure.
    """
    binary = clean_image(captcha_bytes, bg_estimate=bg_estimate)
    features = evaluate_captcha_array(binary)

    for data in (DATA_BOLD, DATA_SLIM):
        result = _match_features(features, data)
        if result is not None:
            return result

    return ""


async def solve_captcha(captcha_bytes: bytes) -> str:
    """
    Async solver — drop-in for the old imgto_txt interface.

    Runs the synchronous algorithm in a thread to avoid blocking the event loop.
    """
    return await asyncio.to_thread(
        functools.partial(solve_captcha_sync, captcha_bytes)
    )


# ---------------------------------------------------------------------------
# Module-level exports
# ---------------------------------------------------------------------------

__all__ = [
    "clean_image",
    "evaluate_captcha_array",
    "solve_captcha",
    "solve_captcha_sync",
]


# ---------------------------------------------------------------------------
# CLI test — run directly with python solver.py <captcha.png>
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python solver.py <captcha.png> [--show]", file=sys.stderr)
        sys.exit(1)

    img_path = Path(sys.argv[1])
    img_bytes = img_path.read_bytes()
    result = solve_captcha_sync(img_bytes)

    if result:
        print(result)
    else:
        print("(could not solve)", file=sys.stderr)
        sys.exit(1)
