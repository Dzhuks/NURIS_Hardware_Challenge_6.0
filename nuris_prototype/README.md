# NURIS prototype — feature extraction from RGB GeoTIFFs

A small, dependency-light prototype that takes RGB GeoTIFFs (Almaty / Astana
ortho­photos at ~7.5 cm/px, EPSG:4326) and produces ready-for-GIS vector
layers describing land cover and infrastructure.

The pipeline is **rule-based** (no model training): it uses visible-band
spectral indices and texture statistics. This was chosen because the supplied
imagery has only RGB + alpha (no NIR) and no labelled training set, so a
classical, interpretable approach is the most defensible baseline.

See [`report.md`](report.md) for the technical report (data, approach,
metrics, limitations).

## Pipeline

```
GeoTIFF
  │
  ▼  rasterio.windows  (2048-px tiles, 64-px overlap)
per-tile RGB + alpha
  │
  ▼  classify.py        (VARI, blue-ratio, brightness, local stddev → 4 masks)
per-class binary masks + per-pixel confidence
  │
  ▼  vectorize.py       (rasterio.features.shapes → polygons;
  │                      skimage.skeletonize → road centrelines;
  │                      compactness gate → building-candidate centroids)
per-tile features in source CRS
  │
  ▼  postprocess.py     (unary_union to dedupe overlap → explode →
  │                      area / compactness / length filters → simplify)
clean features
  │
  ▼  export.py          (build GeoDataFrame with TZ schema;
                         write GeoJSON in EPSG:4326 + GeoPackage in source CRS)
outputs/<scene>.geojson, outputs/<scene>.gpkg, outputs/summary.csv
```

## Output schema (per TZ §5)

| field        | type    | notes |
|--------------|---------|-------|
| `id`         | string  | UUID4 short, unique per feature |
| `class`      | string  | one of: vegetation, water, built_up, bare_soil, road, building_candidate |
| `confidence` | int     | 0–100, mean evidence over the feature |
| `source`     | string  | scene id (filename stem) |
| `area_m2`    | float?  | polygons only, computed in scene UTM |
| `length_m`   | float?  | lines only, computed in scene UTM |
| geometry     | Polygon \| LineString \| Point | EPSG:4326 in GeoJSON; source CRS in GPKG |

## Install

```bash
python3 -m pip install -r requirements.txt
```

Tested with Python 3.12, rasterio 1.4, geopandas 1.1, shapely 2.1,
scikit-image 0.24, scipy 1.x, NumPy 1.26.

## Run

```bash
# single scene
python run.py --inputs ../Astana/Astana_1.tif --out outputs/

# whole folder
python run.py --inputs ../Astana --out outputs/

# fast smoke test (only first 4 tiles per scene)
python run.py --inputs ../Astana/Astana_1.tif --out outputs/ --max-tiles 4
```

Expected outputs:

```
outputs/
  <scene>.geojson      # mandatory deliverable, EPSG:4326
  <scene>.gpkg         # GeoPackage, source CRS, layered by geom type
  summary.csv          # per-scene, per-class counts/areas/density
```

Open `<scene>.geojson` in QGIS over an OSM background to verify alignment.

## Project layout

```
nuris_prototype/
├── README.md            # this file
├── report.md            # technical report
├── requirements.txt
├── run.py               # CLI entry-point
├── src/nuris/
│   ├── config.py        # thresholds, class rules, tile size
│   ├── tiling.py        # rasterio.windows + alpha-aware tile reader
│   ├── classify.py      # spectral / texture rules → per-class masks
│   ├── vectorize.py     # mask → polygon / road skeleton / point
│   ├── postprocess.py   # dissolve, dedupe, filter, simplify
│   ├── export.py        # GeoDataFrame + GeoJSON / GeoPackage writer
│   ├── stats.py         # per-AOI counts / area / density CSV
│   └── pipeline.py      # ties everything together for one scene
└── outputs/             # produced by `run.py`
```

## Reproducing the demo deliverables

```bash
python run.py --inputs ../Almaty/Almaty_10.tif ../Astana/Astana_7.tif --out outputs/
```

This produces the two demo territories required by TZ §9.3 (≥2 scenes) plus
the per-zone summary CSV.

## Notes on coordinate systems

- Inputs are EPSG:4326. We process in source CRS, but compute every area /
  length / simplification tolerance in a **scene-local UTM zone** auto-picked
  per scene (Almaty → EPSG:32643, Astana → EPSG:32642). This keeps metric
  thresholds stable across latitudes.
- GeoJSON outputs are reprojected back to EPSG:4326 (RFC 7946 default).
- GeoPackage outputs keep the source CRS for highest geometric fidelity.
