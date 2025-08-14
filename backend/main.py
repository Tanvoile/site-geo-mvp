# backend/main.py
import os
import re
import json
import math
import zipfile
from typing import Any, Dict, List, Tuple

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
    allow_origins=getattr(CONFIG, "cors_allow_origins", ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Projections ---
_transform_wgs84_to_l93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)

# --- Constantes / défauts (cadastre) ---
WFS_VERSION = "2.0.0"
WFS_BASE = getattr(CONFIG, "cadastre_wfs_base", "https://data.geopf.fr/wfs/ows")
TYPENAME_FEUILLE = getattr(CONFIG, "cadastre_typename", "CADASTRALPARCELS.PARCELLAIRE_EXPRESS:feuille")
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

# -------------------------
#    Helpers HTTP / WFS
# -------------------------
def build_wfs_url(base: str, params: dict) -> str:
    """Ajoute correctement les paramètres que base contienne ou non déjà un '?map='."""
    qp = str(httpx.QueryParams(params))
    return f"{base}&{qp}" if "?" in base else f"{base}?{qp}"

def wfs_shapezip_url(base: str, typename: str, lon: float, lat: float, version: str = WFS_VERSION) -> str:
    """Génère une URL WFS shape-zip avec INTERSECTS (pour GeoServer/IGN) – via build_wfs_url (gère '?map=')."""
    params = {
        "service": "WFS",
        "version": version,
        "request": "GetFeature",
        "typeNames": typename,
        "outputFormat": "shape-zip",
        "srsName": "EPSG:4326",
        "CQL_FILTER": f"INTERSECTS(geom,SRID=4326;POINT({lon} {lat}))",
    }
    return build_wfs_url(base, params)

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# WARM-UP WFS (nouveau)
async def _wfs_warmup(base: str):
    """
    Ping MapServer/GeoServer pour 'réveiller' le WFS.
    On ignore silencieusement les erreurs : best-effort.
    """
    try:
        url = build_wfs_url(base, {"SERVICE": "WFS", "REQUEST": "GetCapabilities"})
        async with httpx.AsyncClient(timeout=10) as client:
            await client.get(url)
    except Exception:
        pass
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

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
    """Renvoie un lien direct DXF-PCI (DGFiP) pour la feuille cadastrale contenant/intersectant le point."""
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

# ---------- PLU (zonage) ----------
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

    def _gpu_build_reglement_urls_from_props(props: dict) -> List[str]:
        urls = []
        for k in ("lien", "url", "urlReglement", "url_reglement"):
            v = props.get(k)
            if isinstance(v, str) and v.startswith("http"):
                urls.append(v)
        partition = props.get("partition") or props.get("Partition")
        gpu_doc_id = props.get("gpu_doc_id") or props.get("gpuDocId") or props.get("gpu_docid")
        nomfic = props.get("nomfic") or props.get("nomFic") or props.get("nom_fic")
        if partition and gpu_doc_id and nomfic:
            suffix = nomfic if nomfic.lower().endswith(".pdf") else f"{nomfic}.pdf"
            urls.append(f"https://data.geopf.fr/annexes/gpu/documents/{partition}/{gpu_doc_id}/{suffix}")
        seen = set(); out = []
        for u in urls:
            if u not in seen:
                out.append(u); seen.add(u)
        return out

    reglement_urls = _gpu_build_reglement_urls_from_props(props)

    return {
        "zone_code": zone_code,
        "libelle_long": props.get("libelong"),
        "nature": props.get("nature"),
        "type": props.get("typeZone") or props.get("typezone"),
        "download_url": str(r.url),
        "atom_links": [],
        "reglement_pdfs": reglement_urls,
        "raw": props
    }

# ---------- RÈGLEMENT GRAPHIQUE (plans de zonage) ----------
GPU_API_BASE = "https://www.geoportail-urbanisme.gouv.fr/api"  # Swagger v5.x (files/details)
APICARTO_GPU_BASE = getattr(CONFIG, "gpu_base", "https://apicarto.ign.fr/api/gpu")

def _looks_like_graphic_plan(title: str, filename: str | None = None) -> bool:
    t = (title or "").lower()
    f = (filename or "").lower()
    hay = f"{t} {f}"
    keys = [
        "règlement graphique", "reglement graphique",
        "plan de zonage", "plans de zonage", "planche",
        "rg_", "rg-", "_rg", "zonage_", "zonage-"
    ]
    return any(k in hay for k in keys)

async def _apicarto_zone_urba_by_point(lon: float, lat: float) -> dict | None:
    url = f"{APICARTO_GPU_BASE}/zone-urba"
    geom = {"type": "Point", "coordinates": [lon, lat]}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, params={"geom": json.dumps(geom)})
        r.raise_for_status()
        data = r.json()
    feats = data.get("features", []); return feats[0] if feats else None

async def _gpu_list_document_files(doc_id: str) -> list[dict]:
    url = f"{GPU_API_BASE}/document/{doc_id}/files"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        return r.json() if isinstance(r.json(), list) else []

def _extract_doc_id_and_zone(props: dict) -> tuple[str | None, str | None, str | None]:
    gpu_doc_id = (
        props.get("gpu_doc_id") or props.get("gpuDocId") or
        props.get("iddocument") or props.get("idDocument") or
        props.get("doc_id") or props.get("document")
    )
    partition = props.get("partition") or props.get("Partition")
    zone_code = props.get("libelle") or props.get("libelleZone") or props.get("LIBELLE")
    return str(gpu_doc_id) if gpu_doc_id else None, str(partition) if partition else None, str(zone_code) if zone_code else None

@app.get("/plu/graphic/by-point")
async def plu_graphic_by_point(
    lon: float = Query(...),
    lat: float = Query(...),
    strict_zone_match: bool = Query(True, description="Filtrer les planches contenant le code de zone dans le titre/fichier")
):
    feat = await _apicarto_zone_urba_by_point(lon, lat)
    if not feat:
        return {"note": "Aucune zone PLU trouvée à ce point.", "items": []}
    props = feat.get("properties", {}) or {}
    gpu_doc_id, partition, zone_code = _extract_doc_id_and_zone(props)
    if not gpu_doc_id:
        raise HTTPException(status_code=500, detail="Impossible d'identifier l'id du document GPU depuis zone-urba.")

    files = await _gpu_list_document_files(gpu_doc_id)
    if not files:
        return {
            "note": "Document trouvé mais aucune pièce listée (files).",
            "gpu_doc_id": gpu_doc_id, "partition": partition, "zone_code": zone_code,
            "items": []
        }

    items = []
    for f in files:
        title = f.get("title") or f.get("nom") or f.get("name") or ""
        url = f.get("url") or f.get("href") or f.get("downloadUrl") or ""
        ftype = (f.get("type") or f.get("category") or "").lower()
        filename = (f.get("fileName") or f.get("filename") or "")
        is_graphic_typed = any(k in ftype for k in ["reglement_graphique", "reglement-graphique", "document_graphique", "graphique"])
        is_graphic_guessed = _looks_like_graphic_plan(title, filename)
        if (is_graphic_typed or is_graphic_guessed) and url.startswith("http"):
            items.append({"title": title, "type": ftype, "url": url, "filename": filename})

    selected = items
    if zone_code and strict_zone_match:
        z = str(zone_code).lower().replace(" ", "")
        def _hit(it):
            blob = f"{(it.get('title') or '')} {(it.get('filename') or '')}".lower().replace(" ", "")
            return z in blob
        narrowed = [it for it in items if _hit(it)]
        if narrowed:
            selected = narrowed

    locating = []
    for f in files:
        title = (f.get("title") or f.get("nom") or "").lower()
        if any(k in title for k in ["repérage", "reperage", "index des planches", "plan d'assemblage", "assemblage des planches"]):
            u = f.get("url") or f.get("href") or ""
            if u.startswith("http"):
                locating.append({"title": f.get("title") or f.get("nom"), "url": u})

    return {
        "gpu_doc_id": gpu_doc_id,
        "partition": partition,
        "zone_code": zone_code,
        "count_all_graphic": len(items),
        "count_selected": len(selected),
        "selected_planches": selected,
        "all_graphic_plans": items,
        "locating_maps": locating
    }

# ---------- Atlas Patrimoines (single-link, compat) ----------
@app.get("/heritage/by-point")
async def heritage_by_point(
    lon: float = Query(...),
    lat: float = Query(...),
    warmup: bool = Query(True)
):
    """
    Renvoie un lien WFS shape-zip (utile si tu veux télécharger la géo).
    NB: utilise build_wfs_url pour gérer les bases avec '?map=...'.
    """
    if not getattr(CONFIG, "atlas_base", None) or not getattr(CONFIG, "atlas_typename", None):
        raise HTTPException(status_code=500, detail="Atlas WFS non configuré (atlas_base/atlas_typename).")
    if warmup:
        await _wfs_warmup(CONFIG.atlas_base)
    url = wfs_shapezip_url(CONFIG.atlas_base, CONFIG.atlas_typename, lon, lat, WFS_VERSION)
    return {"download_url": url}

# ---------- Atlas Patrimoines (résumé multi-couches) ----------
def _bbox_deg_around_point(lon: float, lat: float, radius_m: float = 5.0) -> Tuple[float, float, float, float]:
    """BBox minuscule autour du point (~5 m) en degrés; OK pour MapServer WFS par BBOX."""
    dlat = radius_m / 110_574.0
    dlon = radius_m / (111_320.0 * math.cos(math.radians(lat)) or 1e-6)
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)

async def _atlas_hits_for_point(base: str, typename: str, lon: float, lat: float, geom_field: str = "geom") -> dict:
    """
    MapServer-compatible: on requête par BBOX minuscule (≈ 5 m).
    Tentative 1: WFS 1.0.0 + GeoJSON (TYPENAME/SRS/BBOX)
    Secours    : WFS 2.0.0 + application/json (TYPENAMES/SRSNAME/BBOX)
    """
    minx, miny, maxx, maxy = _bbox_deg_around_point(lon, lat, radius_m=7.5)

    # Essai 1 : WFS 1.0.0 (souvent mieux supporté par MapServer)
    params = {
        "SERVICE": "WFS",
        "VERSION": "1.0.0",
        "REQUEST": "GetFeature",
        "TYPENAME": typename,
        "SRS": "EPSG:4326",
        "OUTPUTFORMAT": "geojson",
        "BBOX": f"{minx},{miny},{maxx},{maxy}",
    }
    url = build_wfs_url(base, params)

    features = []
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url)
        r.raise_for_status()
        data = r.json()
        features = data.get("features", [])
    except Exception:
        # Essai 2 : WFS 2.0.0
        params2 = {
            "SERVICE": "WFS",
            "VERSION": "2.0.0",
            "REQUEST": "GetFeature",
            "TYPENAMES": typename,
            "SRSNAME": "EPSG:4326",
            "OUTPUTFORMAT": "application/json",
            "BBOX": f"{minx},{miny},{maxx},{maxy}",
        }
        url2 = build_wfs_url(base, params2)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r2 = await client.get(url2)
            r2.raise_for_status()
            data2 = r2.json()
            features = data2.get("features", [])
        except Exception:
            features = []

    def best_label(props: Dict[str, Any]) -> str:
        for k in ("nom","Nom","NOM","libelle","LIBELLE","intitule","INTITULE",
                  "appellation","APPELLATION","titre","TITRE","denomination","DENOMINATION"):
            if k in props and props[k]:
                return str(props[k])
        for k, v in props.items():
            if isinstance(v, (str, int, float)) and str(v).strip():
                return f"{k}: {v}"
        return "(sans libellé)"

    out = []
    for f in features:
        props = (f.get("properties") or {})
        out.append({"id": f.get("id"), "label": best_label(props), "properties": props})

    return {"count": len(out), "features": out}

@app.get("/heritage/summary/by-point")
async def heritage_summary_by_point(
    lon: float = Query(...),
    lat: float = Query(...),
    warmup: bool = Query(True, description="Fait un GetCapabilities avant les GetFeature")
):
    """
    Récap pour le front : pour chaque couche Atlas, indique si le point est dedans
    et liste *quelques* libellés/éléments trouvés.
    """
    layers_cfg = getattr(CONFIG, "atlas_layers", None)
    if not layers_cfg:
        # Fallback: on utilise atlas_base/atlas_typename comme unique couche
        if not getattr(CONFIG, "atlas_base", None) or not getattr(CONFIG, "atlas_typename", None):
            raise HTTPException(status_code=500, detail="Aucune couche Atlas configurée (atlas_layers ni atlas_base/atlas_typename).")
        layers_cfg = {
            "atlas_unique": {
                "base": CONFIG.atlas_base,
                "typename": CONFIG.atlas_typename,
                "pretty": "Atlas (couche unique configurée)",
                "geom_field": getattr(CONFIG, "atlas_geom_field", "geom"),
            }
        }

    results = {}
    total_hits = 0
    for key, meta in layers_cfg.items():
        base = meta["base"]
        tname = meta["typename"]
        pretty = meta.get("pretty", key)
        gfield = meta.get("geom_field", getattr(CONFIG, "atlas_geom_field", "geom"))
        try:
            if warmup:
                await _wfs_warmup(base)  # <<< warm-up ici
            res = await _atlas_hits_for_point(base, tname, lon, lat, gfield)
            results[key] = {"pretty": pretty, "count": res["count"], "hits": res["features"][:10]}
            total_hits += res["count"]
        except Exception as e:
            results[key] = {"pretty": pretty, "count": 0, "hits": [], "error": str(e)}

    return {"any_protection": total_hits > 0, "total_hits": total_hits, "layers": results}

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
    Récupère tous les points d'un KML/KMZ.
    - <Point><coordinates>lon,lat[,alt]</coordinates>
    - <LineString>/<Polygon> : prend tous les sommets via <coordinates>
    - <gx:coord> "lon lat alt"
    """
    root = _load_kml_root(path)
    pts = set()

    for el in root.iter():
        if el.tag.endswith("coordinates"):
            text = (el.text or "").strip()
            if not text:
                continue
            for tok in re.split(r"\s+", text):
                if not tok:
                    continue
                parts = tok.split(",")
                if len(parts) >= 2:
                    lon = _float2(parts[0]); lat = _float2(parts[1])
                    if lon is not None and lat is not None:
                        pts.add((lon, lat))

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
    return {
        "status": status,
        "distance_m": round(dmin, 2) if dmin is not None else None,
        "closest_airport_latlon": (closest[1], closest[0]) if closest else None,  # (lat, lon)
        "buffer_m": buffer_m,
    }

# -------------------------
#  Check PLU/RNU/CC/none
# -------------------------

@app.get("/urbanisme/status/by-point")
async def urbanisme_status_by_point(lon: float = Query(...), lat: float = Query(...)):
    base = CONFIG.gpu_base
    if not base:
        raise HTTPException(status_code=500, detail="GPU API non configuré dans config.py")

    geom = {"type": "Point", "coordinates": [lon, lat]}
    async with httpx.AsyncClient(timeout=15) as client:
        # Commune + info RNU
        r_muni = await client.get(f"{base}/municipality", params={"geom": json.dumps(geom)})
        r_muni.raise_for_status()
        muni = (r_muni.json().get("features") or [])
        if not muni:
            return {"status": "Aucune commune trouvée", "details": {}}
        mprops = muni[0].get("properties") or {}
        insee = mprops.get("insee")
        commune = mprops.get("name")
        is_rnu = bool(mprops.get("is_rnu"))

        if is_rnu:
            return {"status": "RNU", "insee": insee, "commune": commune}

        # Type de document d'urbanisme
        r_doc = await client.get(f"{base}/document", params={"geom": json.dumps(geom)})
        r_doc.raise_for_status()
        docs = (r_doc.json().get("features") or [])
        if not docs:
            return {"status": "Aucun document d'urbanisme publié sur GPU", "insee": insee, "commune": commune}

        dprops = docs[0].get("properties") or {}
        du_type = (dprops.get("du_type") or "").upper()
        doc_id = dprops.get("id")
        partition = dprops.get("partition")

        if du_type == "CC":
            return {
                "status": "Carte communale",
                "insee": insee, "commune": commune,
                "du_type": du_type, "partition": partition, "doc_id": doc_id
            }

        # Vérifier si zonage vectorisé disponible
        r_zone = await client.get(f"{base}/zone-urba", params={"geom": json.dumps(geom)})
        r_zone.raise_for_status()
        zones = (r_zone.json().get("features") or [])
        if not zones:
            return {
                "status": "Document trouvé mais zonage indisponible",
                "insee": insee, "commune": commune,
                "du_type": du_type, "partition": partition, "doc_id": doc_id
            }

        return {
            "status": "Zonage disponible",
            "insee": insee, "commune": commune,
            "du_type": du_type, "partition": partition, "doc_id": doc_id
        }
