
import os
import math
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
# En production, remplace ['*'] par la liste de tes domaines front autorisés (ex: 'https://tonfront.onrender.com').
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Projections
_transform_wgs84_to_l93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)

def wfs_shapezip_url(base: str, typename: str, lon: float, lat: float, version: str = "2.0.0") -> str:
    """Construit une URL WFS GetFeature (shape-zip) filtrée par INTERSECTS(POINT lon lat, srid=4326)."""
    params = {
        "service": "WFS",
        "version": version,
        "request": "GetFeature",
        "typeNames": typename,
        "outputFormat": "shape-zip",
        "CQL_FILTER": f"INTERSECTS(geom,SRID=4326;POINT({lon} {lat}))",
    }
    query = "&".join(f"{k}={httpx.QueryParams({k:v})[k]}" for k,v in params.items())
    return f"{base}?{query}"

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

def parse_kml_points(path: str):
    """Extraction simple des Points KML (lon,lat)."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    tree = ET.parse(path)
    root = tree.getroot()
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    coords = []
    for el in root.findall(".//kml:Point/kml:coordinates", ns):
        text = (el.text or "").strip()
        if not text:
            continue
        parts = text.split(",")
        try:
            lon = float(parts[0]); lat = float(parts[1])
            coords.append((lon, lat))
        except Exception:
            continue
    return coords

def distance_meters_wgs84(lon1, lat1, lon2, lat2):
    x1, y1 = _transform_wgs84_to_l93.transform(lon1, lat1)
    x2, y2 = _transform_wgs84_to_l93.transform(lon2, lat2)
    dx, dy = (x2 - x1), (y2 - y1)
    return (dx*dx + dy*dy) ** 0.5

@app.get("/airport/check")
async def airport_check(lon: float = Query(...), lat: float = Query(...), buffer_m: float = Query(1000, ge=0)):
    try:
        pts = parse_kml_points(CONFIG.aerodromes_kml)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"Fichier KML introuvable: {CONFIG.aerodromes_kml}")
    if not pts:
        raise HTTPException(status_code=500, detail="Aucun Point KML détecté (vérifie le format).")
    dmin = None; closest = None
    for (alon, alat) in pts:
        d = distance_meters_wgs84(lon, lat, alon, alat)
        if dmin is None or d < dmin:
            dmin = d; closest = (alon, alat)
    status = "KO" if (dmin is not None and dmin < buffer_m) else "OK"
    return {
        "status": status,
        "distance_m": round(dmin, 2) if dmin is not None else None,
        "closest_airport_lonlat": closest,
        "buffer_m": buffer_m,
    }
