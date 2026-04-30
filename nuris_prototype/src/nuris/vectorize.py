from __future__ import annotations
from typing import Dict, Iterator, List, Tuple
import numpy as np
import rasterio
from rasterio.features import shapes as rio_shapes
from shapely.geometry import shape, Polygon, MultiPolygon, LineString, Point
from shapely.ops import linemerge
from skimage.morphology import (
    binary_opening, binary_closing, remove_small_objects, skeletonize, disk
)

from .tiling import Tile
from .classify import TileMasks


def _clean_mask(mask: np.ndarray, opening_radius: int = 1, min_pixels: int = 16) -> np.ndarray:
    if not mask.any():
        return mask
    if opening_radius > 0:
        mask = binary_opening(mask, footprint=disk(opening_radius))
        mask = binary_closing(mask, footprint=disk(opening_radius))
    mask = remove_small_objects(mask, min_size=min_pixels, connectivity=2)
    return mask


def _polygonise(mask: np.ndarray, transform: rasterio.Affine) -> Iterator[Polygon]:
    if not mask.any():
        return
    mask_u8 = mask.astype(np.uint8)
    for geom_dict, val in rio_shapes(mask_u8, mask=mask, transform=transform):
        if val != 1:
            continue
        geom = shape(geom_dict)
        if geom.is_empty:
            continue
        if isinstance(geom, MultiPolygon):
            yield from geom.geoms
        elif isinstance(geom, Polygon):
            yield geom


def _confidence_for_polygon(poly: Polygon, conf: np.ndarray,
                            transform: rasterio.Affine) -> int:
    minx, miny, maxx, maxy = poly.bounds
    inv = ~transform
    c0, r0 = inv * (minx, maxy)
    c1, r1 = inv * (maxx, miny)
    c0i, r0i = max(0, int(np.floor(c0))), max(0, int(np.floor(r0)))
    c1i, r1i = min(conf.shape[1], int(np.ceil(c1))), min(conf.shape[0], int(np.ceil(r1)))
    if c1i <= c0i or r1i <= r0i:
        return 0
    sub = conf[r0i:r1i, c0i:c1i]
    nz = sub[sub > 0]
    if nz.size == 0:
        return 0
    return int(nz.mean())


def vectorise_polygons(tile: Tile, tile_masks: TileMasks
                       ) -> Dict[str, List[Tuple[Polygon, int]]]:
    out: Dict[str, List[Tuple[Polygon, int]]] = {}
    for cls, mask in tile_masks.masks.items():
        cleaned = _clean_mask(mask, opening_radius=1, min_pixels=16)
        polys = list(_polygonise(cleaned, tile.transform))
        conf_raster = tile_masks.confidence[cls]
        out[cls] = [(p, _confidence_for_polygon(p, conf_raster, tile.transform))
                    for p in polys]
    return out


def vectorise_roads(tile: Tile, tile_masks: TileMasks,
                    px_to_m: float) -> List[Tuple[LineString, int]]:
    built = tile_masks.masks["built_up"]
    if not built.any():
        return []

    radius_m = 4.0
    radius_px = max(2, int(round(radius_m / px_to_m)))
    wide = binary_opening(built, footprint=disk(radius_px))
    road_mask = built & ~wide
    road_mask = remove_small_objects(road_mask, min_size=200, connectivity=2)
    if not road_mask.any():
        return []

    skel = skeletonize(road_mask)
    lines = _skeleton_to_lines(skel, tile.transform)
    if not lines:
        return []
    return [(ln, 65) for ln in lines if ln.length > 0]


def _skeleton_to_lines(skel: np.ndarray,
                       transform: rasterio.Affine) -> List[LineString]:
    rows, cols = np.where(skel)
    if rows.size == 0:
        return []
    pixset = set(zip(rows.tolist(), cols.tolist()))
    lines = []
    forward = [(-1, 1), (0, 1), (1, 1), (1, 0)]
    for (r, c) in zip(rows.tolist(), cols.tolist()):
        for dr, dc in forward:
            nb = (r + dr, c + dc)
            if nb in pixset:
                x0, y0 = transform * (c + 0.5, r + 0.5)
                x1, y1 = transform * (nb[1] + 0.5, nb[0] + 0.5)
                lines.append(LineString([(x0, y0), (x1, y1)]))

    if not lines:
        return []
    merged = linemerge(lines)
    if merged.is_empty:
        return []
    if merged.geom_type == "LineString":
        return [merged]
    if merged.geom_type == "MultiLineString":
        return [g for g in merged.geoms]
    return []


def vectorise_building_points(built_up_polys: List[Tuple[Polygon, int]],
                              area_fn,
                              min_area_m2: float, max_area_m2: float,
                              min_compactness: float
                              ) -> List[Tuple[Point, int]]:
    out: List[Tuple[Point, int]] = []
    for poly, conf in built_up_polys:
        a = area_fn(poly)
        if a < min_area_m2 or a > max_area_m2:
            continue
        peri = poly.length
        if peri <= 0:
            continue
        compactness = 4.0 * np.pi * a / (peri * peri + 1e-9)
        if compactness < min_compactness:
            continue
        c = int(min(95, conf + 10 * compactness))
        out.append((poly.centroid, c))
    return out
