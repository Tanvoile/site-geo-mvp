import os
import re
import json
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
_transform_wgs84_to_l93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)

# --- Constantes / défauts ---
WFS_VERSION = "2.0.0"
WFS_BASE = getattr(CONFIG, "cadastre_wfs_base", "https://data.geopf.fr/wfs/ows")
TYPENAME_FEUILLE = getattr(
    CONFIG, "cadastre_typename", "CADASTRALPARCELS.PARCELLAIRE_EXPRESS:feuille"
)
# millésime demandé pour coller au lien cible (peut être "latest")
CADASTRE_MILLESIME = getattr(CONFIG, "cadastre_millesime", "2025-04-01")

# Helper: lecture de props tolérante à la casse / alias
def _pick(props: dict, *keys, default=None):
    """Retourne props[k] en tolérant maj/min et alias, sinon default."""
    for k in keys:
        if k in props:
            return props[k]
        lk, uk = k.lower(), k.upper()
        if lk in props:
            return props[lk]
        if uk in props:
            return props[uk]
    return default

# --- Utilitaire WFS (shape-zip, filtré par point WGS84) ---
# (utilisé par d'autres routes)
def wfs_shapezip_url(base: str, typename: str, lon: float, lat: float, version: str = WFS_VERSION) -> str:
    params = {
        "service": "WFS",
        "version": version,
        "request": "GetFeature",
        "typeNames": typename,
        "outputFormat": "shape-zip",
        "srsName": "EPSG:4326",
        # IMPORTANT: géométrie = geom + SRID explicite
        "CQL_FILTER": f"INTERSECTS(geom,SRID=4326;POINT({lon} {lat}))",
    }
    query = str(httpx.QueryParams(params))
    return f"{base}?{query}"

# -------------------------
#          Routes
# -------------------------

@app.get("/health")
def health():
    return {"status": "ok"}

# ---------- DXF-PCI FEUILLE (DGFiP) ----------
def _feuille_feature_by_point(lon: float, lat: float) -> dict:
    """
    Cherche la feuille qui contient/intersecte le point (lon, lat) en WGS84.
    Stratégie :
      1) INTERSECTS (le plus robuste, y.c. bords)
      2) DWITHIN avec tout petit tampon (0.5 m)
      3) CONTAINS (au cas où)
    """
    base_params = {
        "service": "WFS",
        "version": WFS_VERSION,
        "request": "GetFeature",
        "typeNames": TYPENAME_FEUILLE,
        "srsName": "EPSG:4326",
        "outputFormat": "application/json",
    }

    def _call(params):
        r = httpx.get(WFS_BASE, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        return data.get("features", [])

    # 1) INTERSECTS
    p1 = dict(base_params, CQL_FILTER=f"INTERSECTS(geom,SRID=4326;POINT({lon} {lat}))")
    feats = _call(p1)

    # 2) DWITHIN (mini buffer)
    if not feats:
        p2 = dict(base_params, CQL_FILTER=f"DWITHIN(geom,SRID=4326;POINT({lon} {lat}),0.5,meters)")
        feats = _call(p2)

    # 3) CONTAINS
    if not feats:
        p3 = dict(base_params, CQL_FILTER=f"CONTAINS(geom,SRID=4326;POINT({lon} {lat}))")
        feats = _call(p3)

    if not feats:
        raise HTTPException(status_code=404, detail="Aucune feuille trouvée pour ce point.")
    # on retourne les propriétés de la 1re feature
    return feats[0]["properties"]

def _normalize_section(sec: str) -> str:
    if sec is None:
        return ""
    s = str(sec).strip().upper()
    return s if len(s) != 1 else "0" + s  # ex. "C" -> "0C"

def _dxf_feuille_url(props: dict) -> str:
    """
    Construit l'URL 'cadastre.data.gouv.fr' du DXF-PCI (tar.bz2) de la feuille entière.
    Schéma: /{millesime}/dxf/feuilles/{DEP}/{INSEE}/dxf-{DEP}{COM}{COM_ABS}{SECTION}{FEUILLE}.tar.bz2
    """
    code_dep = str(_pick(props, "CODE_DEP", "code_dep", "dep")).zfill(2)
    code_com = str(_pick(props, "CODE_COM", "code_com", "com")).zfill(3)
    com_abs  = _pick(props, "COM_ABS", "com_abs")
    com_abs  = str(com_abs if com_abs is not None else "000").zfill(3)
    section  = _normalize_section(_pick(props, "SECTION", "section"))
    feuille  = str(_pick(props, "FEUILLE", "feuille")).zfill(2)

    insee = f"{code_dep}{code_com}"
    filecode = f"{code_dep}{code_com}{com_abs}{section}{feuille}"
    return (
        f"https://cadastre.data.gouv.fr/data/dgfip-pci-vecteur/"
        f"{CADASTRE_MILLESIME}/dxf/feuilles/{code_dep}/{insee}/dxf-{filecode}.tar.bz2"
    )

@app.get("/sheet/by-point")
async def sheet_by_point(
    lon: float = Query(...),
    lat: float = Query(...),
    debug: bool = Query(False)
):
    """
    Renvoie un lien direct DXF-PCI (DGFiP) pour la feuille cadastrale
    contenant/intersectant le point (lon, lat).
    """
    props = _feuille_feature_by_point(lon, lat)
    url = _dxf_feuille_url(props)

    sec_for_id = _normalize_section(_pick(props, "SECTION", "section"))
    payload = {
        "download_url": url,
        "id_feuille": (
            f'{_pick(props,"CODE_DEP","code_dep")}'
            f'{_pick(props,"CODE_COM","code_com")}'
            f'{_pick(props,"COM_ABS","com_abs") or "000"}'
            f'{sec_for_id}'
            f'{str(_pick(props,"FEUILLE","feuille")).zfill(2)}'
        ),
        "source": "DGFiP — PCI vecteur DXF (feuille entière)",
    }
    if debug:
        payload["wfs_props"] = props
    return payload

# ---------- PLU ----------
def _gpu_build_reglement_urls_from_props(props: dict) -> list[str]:
    """
    Construit les URL PDF du règlement écrit depuis les propriétés GPU si dispo :
      - 'lien' (URL directe)
      - Ou: /annexes/gpu/documents/{partition}/{gpu_doc_id}/{nomfic}.pdf
    """
    urls = []

    # 1) URL directe éventuelle
    for k in ("lien", "url", "urlReglement", "url_reglement"):
        v = props.get(k)
        if isinstance(v, str) and v.startswith("http"):
            urls.append(v)

    # 2) Construction manuelle
    partition = props.get("partition") or props.get("Partition")
    gpu_doc_id = props.get("gpu_doc_id") or props.get("gpuDocId") or props.get("gpu_docid")
    nomfic = props.get("nomfic") or props.get("nomFic") or props.get("nom_fic")
    if partition and gpu_doc_id and nomfic:
        suffix = nomfic if nomfic.lower().endswith(".pdf") else f"{nomfic}.pdf"
        urls.append(f"https://data.geopf.fr/annexes/gpu/documents/{partition}/{gpu_doc_id}/{suffix}")

    # Uniq en gardant l'ordre
    seen = set(); out = []
    for u in urls:
        if u not in seen:
            out.append(u); seen.add(u)
    return out

@app.get("/plu/by-point")
async def plu_by_point(lon: float = Query(...), lat: float = Query(...)):
    """
    Zonage PLU via API Carto (GPU) + liens du règlement écrit si disponibles.
    """
    if not CONFIG.gpu_base or not CONFIG.gpu_typename:
        raise HTTPException(status_code=500, detail="GPU API non configuré dans config.py")

    api_url = f"{CONFIG.gpu_base}/{CONFIG.gpu_typename}"
    geom_geojson = {"type": "Point", "coordinates": [lon, lat]}
    params = {"geom": json.dumps(geom_geojson)}

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(api_url, params=params)
        if r.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Erreur API GPU: {r.text}")
        data = r.json()

    feats = data.get("features", [])
    if not feats:
        return {
            "note": "Aucune zone PLU trouvée à ce point.",
            "download_url": str(r.url),
            "atom_links": [],
            "reglement_pdfs": []
        }

    props = feats[0].get("properties", {}) or {}
    zone_code = props.get("libelle") or props.get("libelleZone")

    # Construction des liens de règlement écrit
    reglement_urls = _gpu_build_reglement_urls_from_props(props)

    return {
        "zone_code": zone_code,
        "libelle_long": props.get("libelong"),
        "nature": props.get("nature"),
        "type": props.get("typeZone") or props.get("typezone"),
        "download_url": str(r.url),
        "atom_links": [],  # à remplir si besoin
        "reglement_pdfs": reglement_urls,
        "raw": props
    }

# ---------- Atlas Patrimoines ----------
@app.get("/heritage/by-point")
async def heritage_by_point(lon: float = Query(...), lat: float = Query(...)):
    """
    Patch minimal: évite CONFIG.ign_version qui n'existe pas.
    Attention: si atlas_base contient déjà '?map=...', gérer '&' au lieu de '?' si besoin.
    """
    if "RENSEIGNER" in (CONFIG.atlas_base + CONFIG.atlas_typename):
        raise HTTPException(status_code=500, detail="Atlas WFS non configuré (à renseigner dans config.py)")
    url = wfs_shapezip_url(CONFIG.atlas_base, CONFIG.atlas_typename, lon, lat, WFS_VERSION)
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
