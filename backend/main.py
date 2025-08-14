import os
import re
import zipfile
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import httpx
from pyproj import Transformer
from xml.etree import ElementTree as ET

from .config import CONFIG

load_dotenv()
app = FastAPI(title="Site GEO — MVP sans base")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Projections ---
_transform_wgs84_to_l93 = Transformer.from_crs(
    "EPSG:4326", "EPSG:2154", always_xy=True
)

# --- Utilitaire WFS (shape-zip, filtré par point WGS84) ---
def wfs_shapezip_url(base: str, typename: str, lon: float, lat: float, version: str = "2.0.0") -> str:
    params = {
        "service": "WFS",
        "version": version,
        "request": "GetFeature",
        "typeNames": typename,
        "outputFormat": "shape-zip",
        "CQL_FILTER": f"INTERSECTS(geom,SRID=4326;POINT({lon} {lat}))",
    }
    query = "&".join(f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params.items())
    return f"{base}?{query}"

# -------------------------
#          Routes
# -------------------------

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/sheet/by-point")
async def sheet_by_point(lon: float = Query(...), lat: float = Query(...)):
    if not CONFIG.ign_base or not CONFIG.ign_feuille_typename:
        raise HTTPException(status_code=500, detail="IGN WFS non configuré")
    url = wfs_shapezip_url(CONFIG.ign_base, CONFIG.ign_feuille_typename, lon, lat, CONFIG.ign_version)
    return {"download_url": url, "source": "IGN — Parcellaire Express (feuille)"}

@app.get("/plu/by-point")
async def plu_by_point(lon: float = Query(...), lat: float = Query(...)):
    if "RENSEIGNER" in (CONFIG.gpu_base + CONFIG.gpu_typename):
        raise HTTPException(status_code=500, detail="GPU WFS non configuré (à renseigner dans config.py)")
    url = wfs_shapezip_url(CONFIG.gpu_base, CONFIG.gpu_typename, lon, lat, CONFIG.ign_version)
    return {"download_url": url, "atom_links": [], "note": "Brancher la liste ATOM selon la commune/INSEE."}

@app.get("/heritage/by-point")
async def heritage_by_point(lon: float = Query(...), lat: float = Query(...)):
    if "RENSEIGNER" in (CONFIG.atlas_base + CONFIG.atlas_typename):
        raise HTTPException(status_code=500, detail="Atlas WFS non configuré (à renseigner dans config.py)")
    url = wfs_shapezip_url(CONFIG.atlas_base, CONFIG.atlas_typename, lon, lat, CONFIG.ign_version)
    return {"download_url": url}

# -------------------------
#    KMZ/KML: parsing
# -------------------------

def _resolve_path(p: str) -> str:
    """Essaie p tel quel puis relatif à ce fichier (backend/...)."""
    if os.path.isabs(p) and os.path.exists(p):
        return p
    if os.path.exists(p):
        return p
    here = os.path.dirname(__file__)
    cand = os.path.join(here, p)
    if os.path.exists(cand):
        return cand
    raise FileNotFoundError(p)

def _load_kml_root(path: str):
    """Charge un .kml ou le .kml contenu dans un .kmz, renvoie l'Element root."""
    path = _resolve_path(path)
    if path.lower().endswith(".kmz"):
        with zipfile.ZipFile(path, "r") as zf:
            name = "doc.kml" if "doc.kml" in zf.namelist() else next(
                (n for n in zf.namelist() if n.lower().endswith(".kml")), None
            )
            if not name:
                raise ValueError("KMZ sans fichier .kml interne")
            data = zf.read(name)
            return ET.fromstring(data)
    # .kml
    return ET.parse(path).getroot()

def _float2(s: str):
    try:
        return float(s.replace(",", "."))
    except Exception:
        return None

def parse_kml_points(path: str):
    """
    Récupère tous les points d'un KML/KMZ, en gérant :
      - <Point><coordinates>lon,lat[,alt]</coordinates>
      - coordonnées multiples (séparées par espaces / retours à la ligne), alt ignorée
      - géométries diverses (<LineString>/<Polygon> -> on prend tous les sommets via <coordinates>)
      - <gx:coord> "lon lat alt"
    Retourne une liste [(lon, lat), ...] sans doublons exacts.
    """
    root = _load_kml_root(path)
    pts = set()

    # 1) Tout ce qui finit par 'coordinates' (quel que soit le namespace)
    for el in root.iter():
        if el.tag.endswith("coordinates"):
            text = (el.text or "").strip()
            if not text:
                continue
            # tokens "lon,lat[,alt]" séparés par espaces/retours
            for tok in re.split(r"\s+", text):
                if not tok:
                    continue
                parts = tok.split(",")
                if len(parts) >= 2:
                    lon = _float2(parts[0]); lat = _float2(parts[1])
                    if lon is not None and lat is not None:
                        pts.add((lon, lat))

    # 2) <gx:coord> : "lon lat alt"
    for el in root.iter():
        if el.tag.endswith("coord"):
            text = (el.text or "").strip()
            if not text:
                continue
            parts = re.split(r"\s+", text)
            if len(parts) >= 2:
                lon = _float2(parts[0]); lat = _float2(parts[1])
                if lon is not None and lat is not None:
                    pts.add((lon, lat))

    return list(pts)

# -------------------------
#  Géométrie & endpoint
# -------------------------

def distance_meters_wgs84(lon1, lat1, lon2, lat2):
    x1, y1 = _transform_wgs84_to_l93.transform(lon1, lat1)
    x2, y2 = _transform_wgs84_to_l93.transform(lon2, lat2)
    dx, dy = (x2 - x1), (y2 - y1)
    return (dx * dx + dy * dy) ** 0.5

@app.get("/airport/check")
async def airport_check(
    lon: float = Query(...),
    lat: float = Query(...),
    buffer_m: float = Query(1000, ge=0),
):
    try:
        pts = parse_kml_points(CONFIG.aerodromes_kml)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"Fichier KML/KMZ introuvable: {CONFIG.aerodromes_kml}")
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not pts:
        raise HTTPException(status_code=500, detail="Aucun point détecté (tags <coordinates> ou <gx:coord>).")

    dmin = None
    closest = None
    for (alon, alat) in pts:
        d = distance_meters_wgs84(lon, lat, alon, alat)
        if dmin is None or d < dmin:
            dmin = d
            closest = (alon, alat)

    status = "KO" if (dmin is not None and dmin < buffer_m) else "OK"
    # >>> Renvoi en LAT / LON comme demandé <<<
    return {
        "status": status,
        "distance_m": round(dmin, 2) if dmin is not None else None,
        "closest_airport_latlon": (closest[1], closest[0]) if closest else None,  # (lat, lon)
        "buffer_m": buffer_m,
    }
