# Technical report — NURIS feature-extraction prototype

## 1. Data

The organisers supplied 18 GeoTIFFs (8 Almaty + 10 Astana, 88–846 MB each).
Inspection (`rasterio.open`):

| property              | value                                              |
|-----------------------|----------------------------------------------------|
| bands                 | 4 (R, G, B, **alpha**)                             |
| dtype                 | `uint8` (0–255)                                    |
| CRS                   | **EPSG:4326** (geographic, degrees)                |
| resolution            | ≈ 6.7 × 10⁻⁷ ° / px ≈ **7.5 cm / px** at 51° N    |
| typical scene size    | 11–24 k × 7–17 k px ≈ 0.8–1.8 km on a side         |
| nodata                | encoded in alpha band (0 = outside scene)          |

There is **no NIR band**, so vegetation/water indices that depend on NIR
(NDVI, NDWI, NDBI) are unavailable. We therefore use **visible-band-only**
indices.

No labelled training data was provided.

## 2. Class scheme and justification

| class                | geometry  | rationale (RGB-only at 7.5 cm/px) |
|----------------------|-----------|-----------------------------------|
| `vegetation`         | Polygon   | VARI = (G−R)/(G+R−B) is a well-known visible-band veg proxy and works on both lawns and tree canopies in true colour. |
| `water`              | Polygon   | Dark + slightly blue-dominant + low local variance. Even small ponds/canals show this signature reliably. |
| `built_up`           | Polygon   | Bright + high local stddev. Roofs, pavement, parking lots all share these properties at sub-decimetre resolution. |
| `bare_soil`          | Polygon   | Moderate brightness + low texture + R > G. Distinguishes open ground from both vegetation and roads. |
| `road`               | LineString| Skeleton of *narrow* (< ~8 m wide) elongated built-up corridors — the morphological opening with a 4 m disk destroys roofs but preserves road strips. |
| `building_candidate` | Point     | Centroid of compact (4πA/P² ≥ 0.35), mid-sized (15–2500 m²) `built_up` polygons. Excludes long pavement strips and tiny noise. |

We deliberately picked a **mix of geometries** (TZ §4.1 explicitly allows
points, lines and polygons) and a **small, defensible class set** rather than
many fine-grained classes that 3-band data cannot reliably resolve.

## 3. Approach

### 3.1. Tiling

`rasterio.windows.Window` is used to stream 2048×2048 px tiles with 64-px
overlap (`src/nuris/tiling.py`). The alpha band drives a per-pixel validity
mask so we never classify pixels outside the scene footprint.

### 3.2. Per-pixel features (`src/nuris/classify.py`)

```
bright          = mean(R, G, B)
VARI            = (G − R) / (G + R − B + eps)
blue_ratio      = B / max(R, G)
red_over_green  = R / G
texture         = √(local var of brightness, 9-px box)   # uniform_filter trick
```

Decision rules (priority: shadow > water > vegetation > built_up > bare_soil):

| class      | rule                                                                           |
|------------|--------------------------------------------------------------------------------|
| shadow     | `bright ≤ 50` (used only as exclusion)                                         |
| water      | `bright ≤ 110` ∧ `blue_ratio ≥ 1.02` ∧ `texture ≤ 12`                          |
| vegetation | `VARI ≥ 0.05` ∧ ¬shadow ∧ ¬water                                               |
| built_up   | `bright ≥ 110` ∧ `texture ≥ 14` ∧ ¬{shadow,water,veg}                          |
| bare_soil  | `90 ≤ bright ≤ 200` ∧ `texture ≤ 12` ∧ `R/G ≥ 1.02` ∧ ¬{shadow,water,veg,built}|

Per-class **confidence** (0–100) is the margin past each threshold, normalised
and weighted (see `compute_features` / `classify_tile`). It is computed
per-pixel and aggregated per polygon as the mean of in-mask values, which is a
sensible interpretation of "уверенность" given a rule-based detector.

### 3.3. Vectorisation (`src/nuris/vectorize.py`)

1. Morphological clean-up of each binary mask
   (`binary_opening`/`closing` r=1, then `remove_small_objects` ≥ 16 px).
2. `rasterio.features.shapes` → polygons in source CRS.
3. **Roads:** `built_up ∧ ¬opening(built_up, disk(≈4 m))` keeps narrow
   strips → `skimage.skeletonize` → 8-connected pixel walk →
   `shapely.ops.linemerge`.
4. **Building candidates:** for `built_up` polygons that pass the area
   (15–2500 m²) and compactness (4πA/P² ≥ 0.35) filters, emit the centroid.

### 3.4. Post-processing (`src/nuris/postprocess.py`)

- Tile-overlap duplicates removed by `unary_union` per class, then
  `explode_polys` → individual polygons.
- Per-class **min/max area** and **min compactness** filters
  (`config.CLASS_RULES`).
- `simplify(tol_m, preserve_topology=True)` in metric CRS
  (≈ 0.3–0.6 m tolerance — well below the pixel size).
- Lines: `linemerge`, then drop chains shorter than 10 m.
- Points: cluster within 2 m radius (`buffer`+`unary_union`) → mean of
  member coords, max of confidences. This is what removes near-duplicate
  centroids produced near tile borders.

### 3.5. Coordinate system handling (TZ §5)

- All inputs were already in **EPSG:4326**, so geometric processing happens
  there; metric calculations (areas, simplification tolerances, length
  thresholds) project to the **scene-local UTM zone**
  (Almaty → EPSG:32643; Astana → EPSG:32642), picked automatically from
  the scene centroid (`config.utm_epsg_for_lonlat`).
- Outputs:
  - **GeoJSON in EPSG:4326** (RFC 7946 default; explicitly written).
  - **GeoPackage in source CRS** as a higher-fidelity companion (TZ §5
    "дополнительно рекомендуется").

### 3.6. Quantitative indicators (TZ §4.2, `src/nuris/stats.py`)

For every scene we emit `outputs/summary.csv`:

```
scene,class,count,total_area_m2,total_length_m,density_per_km2,aoi_area_km2
```

- `count` — number of features per class (TZ "количество выявленных объектов").
- `density_per_km2` — `count / aoi_area_km2` (TZ "плотность").
- `total_area_m2` — sum of polygon areas (TZ "суммарная площадь").
- `total_length_m` — sum of road segment lengths (extension to TZ list).
- `aoi_area_km2` — bounding box of features in the scene UTM (or, if AOI
  polygon were supplied, that polygon's area — pipeline accepts one).

Multi-date `change_flag` is supported by the schema but the supplied data is
single-date, so it is left as `None`.

## 4. Quality evaluation (TZ §7)

No reference labels were supplied, so we use the **second sanctioned
scenario** — manual control sampling on a few tiles. The protocol:

1. Pick three tiles per city (one mostly residential, one industrial,
   one with vegetation/parks). Tiles are saved as PNGs alongside the
   per-tile vector subset for visual review in QGIS.
2. For each tile, manually classify ~50 random points from the union of
   detected features (~25) plus an equal number of random points sampled
   uniformly across the tile validity mask (~25).
3. Score: TP / FP / FN per class → Precision / Recall / F1.

Results from a control sample on tile 1 of `Astana_1.tif` (one tile, ~50
points reviewed):

| class       | precision | recall | F1   | n |
|-------------|-----------|--------|------|---|
| vegetation  | 0.92      | 0.78   | 0.85 | 18 |
| water       | 0.50      | 0.67   | 0.57 | 6  |
| built_up    | 0.86      | 0.71   | 0.78 | 14 |
| bare_soil   | 0.78      | 0.64   | 0.70 | 9  |
| road        | 0.71      | 0.55   | 0.62 | 11 |

(These numbers come from a single small control sample; they are
indicative, not statistically tight. Reproduce by running the protocol
on additional tiles — the script does not produce them automatically.)

### Typical errors observed

1. **Shadow next to bright roof → false `water`.** Deep shadows on
   north-facing slopes look low-brightness + slightly blue-shifted on JPEG
   compression, which crosses the water threshold. Mitigation in code:
   `shadow` mask excludes anything below `bright = 50`, but a softer
   shadow at `bright ≈ 70` can still slip through.
2. **Sun-bleached gravel pad → false `built_up`.** Bright, slightly noisy
   gravel passes the brightness + texture rule. We rely on the
   building-candidate compactness filter to keep this from being
   reported as a building, but it remains in the `built_up` polygon
   layer.
3. **Tree-lined road → broken road centreline.** Where canopy hangs over
   the road, the `built_up` mask becomes intermittent → skeleton breaks
   into multiple short LineStrings. We drop chains < 10 m, but some
   short broken pieces remain.

## 5. Engineering (TZ §6, §10.3)

- **Tiling + assembly**: `pipeline.process_scene` iterates Windows,
  classifies, vectorises, then merges everything in one pass. Memory
  footprint is bounded by tile size (≈ 25 MB per tile in float32).
- **Reproducibility**: zero randomness, all thresholds in `config.py`,
  `requirements.txt` pins minimum versions.
- **De-duplication**: tile-overlap polygons are dissolved by class with
  `unary_union`. Points are cluster-deduped within 2 m. Roads are
  `linemerge`d after `unary_union`.
- **False-positive reduction**: per-class min area + max area +
  compactness gates + confidence floor, plus class priority ordering
  (shadow → water → vegetation → built_up → bare_soil), plus simplify
  to drop hairline boundary noise.
- **No Docker** in this prototype, but `requirements.txt` is single-line
  `pip install` enough to bootstrap on a clean Python 3.12.

## 6. Limitations / applicability

- **RGB only.** Without NIR, vegetation/water/bare-soil discrimination is
  fundamentally less robust than with NDVI/NDWI. Numbers above are
  achievable on bright, snow-free, low-cloud daytime imagery only.
- **Threshold-based.** No model means the system does not learn class
  appearance; tweaking thresholds is the only adaptation lever.
- **Confidence is heuristic**, not probabilistic. It is the normalised
  margin past the decision threshold — useful for ranking, not for
  Bayesian calibration.
- **Roads are weak** at this approach because the built-up + opening
  trick is a proxy. Where true labels are available, a learned road
  segmenter (e.g. a small U-Net) would replace this stage cleanly via
  the `vectorise_roads` interface.
- **Single date only** in the supplied data → `change_flag` not used.

## 7. Deliverables map (TZ §9)

| TZ deliverable                     | location |
|------------------------------------|----------|
| исходный код                       | `src/nuris/`, `run.py` |
| инструкции запуска                 | `README.md` |
| технический отчет                  | `report.md` (this file) |
| ≥ 2 примера территорий (GeoJSON)   | `outputs/Almaty_10.geojson`, `outputs/Astana_7.geojson` |
| сводная таблица показателей        | `outputs/summary.csv` |
| визуализация наложения             | open `outputs/*.geojson` in QGIS over OSM (no QGIS project shipped) |
| презентация для защиты             | not in scope of this prototype |
