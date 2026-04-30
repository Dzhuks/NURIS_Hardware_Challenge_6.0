from __future__ import annotations
from dataclasses import dataclass
from typing import Iterator
import numpy as np
import rasterio
from rasterio.windows import Window

from .config import TILE_SIZE, TILE_OVERLAP


@dataclass
class Tile:
    window: Window
    rgb: np.ndarray
    valid: np.ndarray
    transform: rasterio.Affine


def iter_windows(width: int, height: int,
                 tile: int = TILE_SIZE, overlap: int = TILE_OVERLAP) -> Iterator[Window]:
    step = tile - overlap
    for row in range(0, height, step):
        for col in range(0, width, step):
            w = min(tile, width - col)
            h = min(tile, height - row)
            if w <= 0 or h <= 0:
                continue
            yield Window(col, row, w, h)


def read_tile(ds: rasterio.io.DatasetReader, win: Window) -> Tile:
    arr = ds.read(window=win)
    if arr.shape[0] >= 4:
        rgb = arr[:3]
        valid = arr[3] > 0
    else:
        rgb = arr[:3]
        valid = (rgb.sum(axis=0) > 0)
    transform = ds.window_transform(win)
    return Tile(window=win, rgb=rgb, valid=valid, transform=transform)
