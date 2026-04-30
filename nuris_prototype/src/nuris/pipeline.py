from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import math
import numpy as np
import rasterio
from rasterio.windows import Window
from shapely.geometry import box, mapping, shape, Polygon, LineString, Point
from shapely.ops import transform as shp_transform
import pyproj
from tqdm import tqdm

from . import config as C
from .tiling import iter_windows, read_tile
from .classify import classify_tile
from .vectorize import (
    vectorise_polygons, vectorise_roads, vectorise_building_points,
)
from .postprocess import merge_polygons, merge_lines, merge_points
from .export import build_dataframe


def _approx_meters_per_pixel(ds: rasterio.io.DatasetReader) -> float:
    if ds.crs is None:
        return float(abs(ds.transform.a))
    if ds.crs.is_geographic:
        lat = (ds.bounds.bottom + ds.bounds.top) / 2.0
        deg_per_px = abs(ds.transform.a)
        m_per_deg = 111_320.0 * math.cos(math.radians(lat))
        return deg_per_px * m_per_deg
    return abs(ds.transform.a)


def _make_metric_projector(source_crs: str, scene_lon: float, scene_lat: float):
    target_epsg = C.utm_epsg_for_lonlat(scene_lon, scene_lat)
    target_crs = f"EPSG:{target_epsg}"
    fwd = pyproj.Transformer.from_crs(source_crs, target_crs, always_xy=True).transform

    def project(geom):
        return shp_transform(fwd, geom)

    return project, target_crs


def process_scene(scene_path: Path,
                  scene_id: Optional[str] = None,
                  aoi_geom_lonlat=None,
                  max_tiles: Optional[int] = None,
                  ) -> Tuple["gpd.GeoDataFrame", str]:  # noqa
    scene_path = Path(scene_path)
    scene_id = scene_id or scene_path.stem

    with rasterio.open(scene_path) as ds:
        source_crs = str(ds.crs) if ds.crs is not None else "EPSG:4326"
        scene_cx = (ds.bounds.left + ds.bounds.right) / 2
        scene_cy = (ds.bounds.bottom + ds.bounds.top) / 2
        m_per_px = _approx_meters_per_pixel(ds)

        project_to_metric, metric_crs = _make_metric_projector(
            source_crs, scene_cx, scene_cy)

        windows: List[Window] = list(iter_windows(ds.width, ds.height))
        if max_tiles is not None:
            windows = windows[:max_tiles]

        per_tile_polys: Dict[str, List[List[Tuple[Polygon, int]]]] = {
            cls: [] for cls in ("vegetation", "water", "built_up", "bare_soil")
        }
        per_tile_lines: List[List[Tuple[LineString, int]]] = []
        per_tile_built_for_pts: List[List[Tuple[Polygon, int]]] = []

        for win in tqdm(windows, desc=f"tiles[{scene_id}]"):
            tile = read_tile(ds, win)
            if tile.valid.mean() < 0.05:
                continue
            tm = classify_tile(tile)
            polys = vectorise_polygons(tile, tm)

            for cls in per_tile_polys:
                per_tile_polys[cls].append(polys.get(cls, []))

            roads = vectorise_roads(tile, tm, px_to_m=m_per_px)
            per_tile_lines.append(roads)

            per_tile_built_for_pts.append(polys.get("built_up", []))

    merged_polys: Dict[str, List[Tuple[Polygon, int, float]]] = {}
    for cls, lst in per_tile_polys.items():
        merged_polys[cls] = merge_polygons(lst, project_to_metric, C.CLASS_RULES[cls])

    merged_lines = merge_lines(per_tile_lines, project_to_metric,
                               C.CLASS_RULES["road"], min_length_m=10.0)

    rule_pts = C.CLASS_RULES["building_candidate"]
    def metric_area(poly):
        return project_to_metric(poly).area
    bup_for_points = [(p, c) for (p, c, _a) in merged_polys.get("built_up", [])]
    bup_pts_per_tile = [vectorise_building_points(
        bup_for_points, area_fn=metric_area,
        min_area_m2=rule_pts.min_area_m2, max_area_m2=rule_pts.max_area_m2,
        min_compactness=rule_pts.min_compactness)]
    merged_points = merge_points(bup_pts_per_tile, project_to_metric,
                                 cluster_radius_m=2.0)

    gdf = build_dataframe(scene_id=scene_id,
                          polys=merged_polys,
                          lines=merged_lines,
                          points=merged_points,
                          source_crs=source_crs)
    return gdf, metric_crs
