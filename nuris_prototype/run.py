#!/usr/bin/env python3
from __future__ import annotations
import argparse
import sys
from pathlib import Path
import logging

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from nuris.pipeline import process_scene
from nuris.export import write_outputs
from nuris.stats import summarise, write_summary_csv


def collect_inputs(inputs):
    paths = []
    for p in inputs:
        p = Path(p)
        if p.is_dir():
            paths.extend(sorted(p.glob("*.tif")) + sorted(p.glob("*.tiff")))
        elif p.is_file():
            paths.append(p)
    return paths


def main():
    ap = argparse.ArgumentParser(description="NURIS GIS feature extraction prototype")
    ap.add_argument("--inputs", nargs="+", required=True,
                    help="GeoTIFF files or folders containing them")
    ap.add_argument("--out", required=True, help="Output directory")
    ap.add_argument("--max-tiles", type=int, default=None,
                    help="(Debug) limit number of tiles per scene")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    inputs = collect_inputs(args.inputs)
    if not inputs:
        print("No GeoTIFF inputs found.", file=sys.stderr)
        sys.exit(2)

    out_dir = Path(args.out)
    all_summary_rows = []

    for scene in inputs:
        print(f"\n=== Processing {scene} ===")
        gdf, metric_crs = process_scene(scene, max_tiles=args.max_tiles)
        if gdf.empty:
            print(f"  no features found")
            continue
        scene_id = scene.stem
        out = write_outputs(gdf, out_dir, scene_id)
        print(f"  wrote: {out}")

        from shapely.geometry import box as shp_box
        from shapely.ops import transform as shp_transform
        import pyproj
        scene_box_src = shp_box(*gdf.total_bounds)
        fwd = pyproj.Transformer.from_crs(gdf.crs, metric_crs, always_xy=True).transform
        scene_box_metric = shp_transform(fwd, scene_box_src)

        rows = summarise(gdf, scene_id=scene_id,
                         aoi_geom_metric=scene_box_metric,
                         metric_crs=metric_crs)
        all_summary_rows.extend(rows)

    if all_summary_rows:
        csv_path = out_dir / "summary.csv"
        write_summary_csv(all_summary_rows, csv_path)
        print(f"\nWrote summary: {csv_path}")


if __name__ == "__main__":
    main()
