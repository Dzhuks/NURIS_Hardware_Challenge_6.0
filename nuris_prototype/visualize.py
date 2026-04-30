#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import rasterio
from rasterio.windows import Window
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


CLASS_COLORS = {
    "vegetation":         "#3fb24f",
    "water":              "#2f7fc7",
    "built_up":           "#cc4444",
    "bare_soil":          "#c8a060",
    "road":               "#404040",
    "building_candidate": "#ffd000",
}


def render(tif_path: Path, geojson_path: Path, out_path: Path,
           max_size: int = 3000) -> None:
    with rasterio.open(tif_path) as ds:
        sx = max(1, ds.width // max_size)
        sy = max(1, ds.height // max_size)
        w = ds.width // sx
        h = ds.height // sy
        rgb = ds.read([1, 2, 3], out_shape=(3, h, w))
        left, bottom, right, top = ds.bounds
        rgb = np.transpose(rgb, (1, 2, 0))

    gdf = gpd.read_file(geojson_path)
    if str(gdf.crs) != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")

    fig, ax = plt.subplots(figsize=(12, 12 * (top - bottom) / (right - left)))
    ax.imshow(rgb, extent=(left, right, bottom, top), origin="upper")

    for cls, color in CLASS_COLORS.items():
        sub = gdf[gdf["class"] == cls]
        if sub.empty:
            continue
        if cls == "building_candidate":
            sub.plot(ax=ax, color=color, markersize=14, marker="o",
                     edgecolor="black", linewidth=0.4, alpha=0.9, zorder=3)
        elif cls == "road":
            sub.plot(ax=ax, color=color, linewidth=1.2, alpha=0.85, zorder=2)
        else:
            sub.plot(ax=ax, facecolor=color, edgecolor=color,
                     linewidth=0.3, alpha=0.45, zorder=1)

    handles = [mpatches.Patch(color=c, label=k) for k, c in CLASS_COLORS.items()]
    ax.legend(handles=handles, loc="lower right", fontsize=9, framealpha=0.85)
    ax.set_xlabel("longitude (deg E)")
    ax.set_ylabel("latitude (deg N)")
    ax.set_title(f"{tif_path.name} - extracted features (EPSG:4326)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tif", required=True)
    ap.add_argument("--geojson", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    render(Path(args.tif), Path(args.geojson), Path(args.out))
