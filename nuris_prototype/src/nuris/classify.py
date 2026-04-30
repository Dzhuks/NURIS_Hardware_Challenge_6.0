from __future__ import annotations
from dataclasses import dataclass
from typing import Dict
import numpy as np
from scipy.ndimage import uniform_filter

from . import config as C
from .tiling import Tile


EPS = 1e-6


def _to_float(rgb_u8: np.ndarray) -> np.ndarray:
    return rgb_u8.astype(np.float32, copy=False)


def compute_features(rgb: np.ndarray) -> Dict[str, np.ndarray]:
    f = _to_float(rgb)
    r, g, b = f[0], f[1], f[2]

    bright = (r + g + b) / 3.0
    vari = (g - r) / (g + r - b + EPS)
    blue_ratio = b / (np.maximum(r, g) + EPS)
    red_over_green = r / (g + EPS)

    win = C.TEXTURE_WIN
    mean = uniform_filter(bright, size=win, mode="reflect")
    sq = uniform_filter(bright * bright, size=win, mode="reflect")
    var = np.maximum(sq - mean * mean, 0.0)
    texture = np.sqrt(var)

    return {
        "bright": bright,
        "vari": vari,
        "blue_ratio": blue_ratio,
        "red_over_green": red_over_green,
        "texture": texture,
    }


@dataclass
class TileMasks:
    masks: Dict[str, np.ndarray]
    confidence: Dict[str, np.ndarray]


def classify_tile(tile: Tile) -> TileMasks:
    feats = compute_features(tile.rgb)
    valid = tile.valid

    bright = feats["bright"]
    vari = feats["vari"]
    blue_ratio = feats["blue_ratio"]
    rog = feats["red_over_green"]
    tex = feats["texture"]

    shadow = (bright <= C.SHADOW_BRIGHT_MAX) & valid

    water = (
        valid
        & ~shadow
        & (bright <= C.WATER_BRIGHT_MAX)
        & (blue_ratio >= C.WATER_BLUE_MIN_RATIO)
        & (tex <= C.WATER_TEXTURE_MAX)
    )

    vegetation = valid & ~shadow & ~water & (vari >= C.VARI_VEG_MIN)

    built_up = (
        valid
        & ~shadow & ~water & ~vegetation
        & (bright >= C.BUILT_BRIGHT_MIN)
        & (tex >= C.BUILT_TEXTURE_MIN)
    )

    bare_soil = (
        valid
        & ~shadow & ~water & ~vegetation & ~built_up
        & (bright >= C.BARE_BRIGHT_RANGE[0]) & (bright <= C.BARE_BRIGHT_RANGE[1])
        & (tex <= C.BARE_TEXTURE_MAX)
        & (rog >= C.BARE_RED_OVER_GREEN_MIN)
    )

    masks = {
        "vegetation": vegetation,
        "water": water,
        "built_up": built_up,
        "bare_soil": bare_soil,
    }

    conf: Dict[str, np.ndarray] = {}

    veg_score = np.clip((vari - C.VARI_VEG_MIN) / 0.25, 0.0, 1.0)
    conf["vegetation"] = (veg_score * 100).astype(np.uint8)

    water_score = (
        np.clip((C.WATER_BRIGHT_MAX - bright) / 80.0, 0.0, 1.0) * 0.4
        + np.clip((blue_ratio - C.WATER_BLUE_MIN_RATIO) / 0.10, 0.0, 1.0) * 0.4
        + np.clip((C.WATER_TEXTURE_MAX - tex) / 8.0, 0.0, 1.0) * 0.2
    )
    conf["water"] = (water_score * 100).astype(np.uint8)

    built_score = (
        np.clip((bright - C.BUILT_BRIGHT_MIN) / 80.0, 0.0, 1.0) * 0.5
        + np.clip((tex - C.BUILT_TEXTURE_MIN) / 30.0, 0.0, 1.0) * 0.5
    )
    conf["built_up"] = (built_score * 100).astype(np.uint8)

    bare_score = (
        np.clip((rog - C.BARE_RED_OVER_GREEN_MIN) / 0.10, 0.0, 1.0) * 0.6
        + np.clip((C.BARE_TEXTURE_MAX - tex) / 8.0, 0.0, 1.0) * 0.4
    )
    conf["bare_soil"] = (bare_score * 100).astype(np.uint8)

    for k in list(conf.keys()):
        conf[k] = np.where(masks[k], conf[k], 0).astype(np.uint8)

    return TileMasks(masks=masks, confidence=conf)
