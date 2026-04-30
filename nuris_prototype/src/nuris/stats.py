from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional
import csv
import geopandas as gpd
from shapely.geometry import box


def summarise(gdf: gpd.GeoDataFrame,
              scene_id: str,
              aoi_geom_metric=None,
              metric_crs: Optional[str] = None
              ) -> List[Dict]:
    rows = []
    if gdf.empty:
        return rows

    if metric_crs is None:
        gdf_m = gdf
    else:
        gdf_m = gdf.to_crs(metric_crs)

    if aoi_geom_metric is None:
        aoi_area_km2 = (gdf_m.total_bounds[2] - gdf_m.total_bounds[0]) * \
                       (gdf_m.total_bounds[3] - gdf_m.total_bounds[1]) / 1e6
    else:
        aoi_area_km2 = aoi_geom_metric.area / 1e6

    for cls, group in gdf_m.groupby("class"):
        n = len(group)
        polys = group[group.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
        lines = group[group.geometry.geom_type.isin(["LineString", "MultiLineString"])]
        total_area_m2 = float(polys.geometry.area.sum()) if not polys.empty else 0.0
        total_length_m = float(lines.geometry.length.sum()) if not lines.empty else 0.0
        rows.append(dict(
            scene=scene_id,
            **{"class": cls},
            count=n,
            total_area_m2=round(total_area_m2, 1),
            total_length_m=round(total_length_m, 1),
            density_per_km2=round(n / aoi_area_km2, 2) if aoi_area_km2 > 0 else None,
            aoi_area_km2=round(aoi_area_km2, 4),
        ))
    return rows


def write_summary_csv(rows: List[Dict], path: Path) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["scene", "class", "count", "total_area_m2",
              "total_length_m", "density_per_km2", "aoi_area_km2"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
