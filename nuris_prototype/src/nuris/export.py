from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Tuple
import uuid
import json
import geopandas as gpd
from shapely.geometry import Polygon, LineString, Point, mapping
from shapely.geometry.polygon import orient
from shapely.validation import make_valid


def _make_id() -> str:
    return uuid.uuid4().hex[:12]


def _clean_polygon(geom):
    fixed = make_valid(geom)
    if fixed.geom_type == "Polygon":
        return orient(fixed, sign=1.0)
    if fixed.geom_type == "MultiPolygon":
        from shapely.geometry import MultiPolygon
        return MultiPolygon([orient(p, sign=1.0) for p in fixed.geoms])
    return fixed


def build_dataframe(scene_id: str,
                    polys: Dict[str, List[Tuple[Polygon, int, float]]],
                    lines: List[Tuple[LineString, int, float]],
                    points: List[Tuple[Point, int]],
                    source_crs: str
                    ) -> gpd.GeoDataFrame:
    rows = []
    for cls, items in polys.items():
        for poly, conf, area_m2 in items:
            rows.append(dict(
                id=_make_id(), class_=cls, confidence=int(conf),
                source=scene_id, area_m2=round(area_m2, 2),
                length_m=None, geometry=_clean_polygon(poly),
            ))
    for ln, conf, length_m in lines:
        rows.append(dict(
            id=_make_id(), class_="road", confidence=int(conf),
            source=scene_id, area_m2=None, length_m=round(length_m, 2),
            geometry=ln,
        ))
    for pt, conf in points:
        rows.append(dict(
            id=_make_id(), class_="building_candidate", confidence=int(conf),
            source=scene_id, area_m2=None, length_m=None, geometry=pt,
        ))

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=source_crs)
    gdf = gdf.rename(columns={"class_": "class"})
    return gdf


def _quantize_coords(geom, ndigits: int = 7):
    from shapely.ops import transform
    return transform(lambda x, y, z=None: (round(x, ndigits), round(y, ndigits)), geom)


def _write_geojson_rfc7946(gdf: gpd.GeoDataFrame, path: Path, ndigits: int = 7) -> None:
    features = []
    for _, row in gdf.iterrows():
        geom = _quantize_coords(row.geometry, ndigits=ndigits)
        props = {k: (None if (v is None or (isinstance(v, float) and v != v)) else v)
                 for k, v in row.drop("geometry").items()}
        features.append({"type": "Feature", "properties": props, "geometry": mapping(geom)})
    fc = {"type": "FeatureCollection", "features": features}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, separators=(",", ":"))


def write_outputs(gdf: gpd.GeoDataFrame, out_dir: Path, scene_id: str,
                  geojson_crs: str = "EPSG:4326") -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    out: Dict[str, Path] = {}

    gj_path = out_dir / f"{scene_id}.geojson"
    gdf_4326 = gdf.to_crs(geojson_crs) if str(gdf.crs) != geojson_crs else gdf
    _write_geojson_rfc7946(gdf_4326, gj_path, ndigits=7)
    out["geojson"] = gj_path

    gpkg_path = out_dir / f"{scene_id}.gpkg"
    for geom_type in ("Polygon", "LineString", "Point"):
        sub = gdf[gdf.geometry.geom_type == geom_type]
        if sub.empty:
            continue
        layer = f"features_{geom_type.lower()}"
        sub.to_file(gpkg_path, layer=layer, driver="GPKG")
    out["gpkg"] = gpkg_path

    return out
