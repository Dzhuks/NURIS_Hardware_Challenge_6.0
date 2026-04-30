from dataclasses import dataclass
from typing import Dict


TILE_SIZE = 2048
TILE_OVERLAP = 64

VARI_VEG_MIN = 0.05

WATER_BRIGHT_MAX = 110
WATER_BLUE_MIN_RATIO = 1.02
WATER_TEXTURE_MAX = 12

BUILT_BRIGHT_MIN = 110
BUILT_TEXTURE_MIN = 14

BARE_BRIGHT_RANGE = (90, 200)
BARE_TEXTURE_MAX = 12
BARE_RED_OVER_GREEN_MIN = 1.02

SHADOW_BRIGHT_MAX = 50

TEXTURE_WIN = 9


@dataclass
class ClassRule:
    name: str
    geom: str
    min_area_m2: float = 0.0
    max_area_m2: float = float("inf")
    min_compactness: float = 0.0
    simplify_m: float = 0.5
    confidence_floor: int = 50


CLASS_RULES: Dict[str, ClassRule] = {
    "vegetation": ClassRule("vegetation", "Polygon",
                            min_area_m2=4.0, simplify_m=0.4, confidence_floor=55),
    "water":      ClassRule("water", "Polygon",
                            min_area_m2=20.0, simplify_m=0.5, confidence_floor=60),
    "built_up":   ClassRule("built_up", "Polygon",
                            min_area_m2=10.0, simplify_m=0.3, confidence_floor=55),
    "bare_soil":  ClassRule("bare_soil", "Polygon",
                            min_area_m2=8.0, simplify_m=0.4, confidence_floor=50),
    "road":       ClassRule("road", "LineString",
                            min_area_m2=0.0, simplify_m=0.6, confidence_floor=55),
    "building_candidate": ClassRule("building_candidate", "Point",
                            min_area_m2=15.0, max_area_m2=2500.0,
                            min_compactness=0.35, confidence_floor=55),
}

OUTPUT_CRS_GEOJSON = "EPSG:4326"


def utm_epsg_for_lonlat(lon: float, lat: float) -> int:
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone
