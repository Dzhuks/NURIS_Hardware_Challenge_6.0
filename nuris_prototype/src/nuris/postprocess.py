from __future__ import annotations
from typing import Dict, List, Tuple, Iterable, Callable
import numpy as np
from shapely.geometry import (
    Polygon, MultiPolygon, LineString, MultiLineString, Point, MultiPoint
)
from shapely.ops import unary_union, linemerge

from . import config as C


def _explode_polys(geom) -> List[Polygon]:
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [g for g in geom.geoms]
    return []


def merge_polygons(per_tile: List[List[Tuple[Polygon, int]]],
                   project_to_metric: Callable[[Polygon], Polygon],
                   rule: C.ClassRule
                   ) -> List[Tuple[Polygon, int, float]]:
    if not per_tile:
        return []

    polys: List[Polygon] = []
    confs: List[int] = []
    for tile_list in per_tile:
        for p, c in tile_list:
            if p.is_valid and not p.is_empty:
                polys.append(p)
                confs.append(c)

    if not polys:
        return []

    dissolved = unary_union(polys)
    pieces = _explode_polys(dissolved)

    from shapely.strtree import STRtree
    tree = STRtree(polys)
    out: List[Tuple[Polygon, int, float]] = []
    for piece in pieces:
        idxs = tree.query(piece)
        best = 0
        for i in idxs:
            if polys[int(i)].intersects(piece):
                best = max(best, confs[int(i)])
        if best < rule.confidence_floor:
            continue

        metric_piece = project_to_metric(piece)
        area_m2 = metric_piece.area
        if area_m2 < rule.min_area_m2 or area_m2 > rule.max_area_m2:
            continue
        peri = metric_piece.length
        compactness = 4.0 * np.pi * area_m2 / (peri * peri + 1e-9) if peri > 0 else 0.0
        if compactness < rule.min_compactness:
            continue

        simp_metric = metric_piece.simplify(rule.simplify_m, preserve_topology=True)
        if simp_metric.is_empty or not simp_metric.is_valid:
            continue

        out.append((piece, int(best), float(area_m2)))
    return out


def merge_lines(per_tile: List[List[Tuple[LineString, int]]],
                project_to_metric: Callable[[LineString], LineString],
                rule: C.ClassRule,
                min_length_m: float = 8.0
                ) -> List[Tuple[LineString, int, float]]:
    if not per_tile:
        return []
    lines: List[LineString] = []
    confs: List[int] = []
    for tile_list in per_tile:
        for ln, c in tile_list:
            if ln.is_valid and not ln.is_empty and ln.length > 0:
                lines.append(ln)
                confs.append(c)
    if not lines:
        return []

    merged = linemerge(unary_union(lines))
    if merged.is_empty:
        return []
    if isinstance(merged, LineString):
        chunks = [merged]
    elif isinstance(merged, MultiLineString):
        chunks = list(merged.geoms)
    else:
        chunks = []

    out: List[Tuple[LineString, int, float]] = []
    for ln in chunks:
        ln_m = project_to_metric(ln)
        length_m = ln_m.length
        if length_m < min_length_m:
            continue
        from shapely.strtree import STRtree
        tree = STRtree(lines)
        idxs = tree.query(ln)
        cs = [confs[int(i)] for i in idxs if lines[int(i)].intersects(ln)]
        c = int(np.median(cs)) if cs else 60
        if c < rule.confidence_floor:
            continue
        out.append((ln, c, float(length_m)))
    return out


def merge_points(per_tile: List[List[Tuple[Point, int]]],
                 project_to_metric: Callable[[Point], Point],
                 cluster_radius_m: float = 2.0
                 ) -> List[Tuple[Point, int]]:
    if not per_tile:
        return []
    pts: List[Point] = []
    confs: List[int] = []
    for tile_list in per_tile:
        for pt, c in tile_list:
            pts.append(pt)
            confs.append(c)
    if not pts:
        return []

    pts_m = [project_to_metric(p) for p in pts]
    buffered = unary_union([p.buffer(cluster_radius_m) for p in pts_m])
    if buffered.is_empty:
        return []
    clusters = _explode_polys(buffered)
    out: List[Tuple[Point, int]] = []
    from shapely.strtree import STRtree
    tree = STRtree(pts_m)
    for cl in clusters:
        idxs = tree.query(cl)
        members = [(pts[int(i)], confs[int(i)]) for i in idxs if pts_m[int(i)].within(cl)]
        if not members:
            continue
        xs = np.mean([m[0].x for m in members])
        ys = np.mean([m[0].y for m in members])
        c = int(np.max([m[1] for m in members]))
        out.append((Point(xs, ys), c))
    return out
