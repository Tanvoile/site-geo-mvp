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
# Nouveau : couche parcelle
TYPENAME_PARCELLE = "CADASTRALPARCELS.PARCELLAIRE_EXPRESS:parcelle"
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

# Petit warm-up best-effort (utilisé pour WFS publics si besoin)
async def _wfs_warmup(base: str):
    try:
        url = build_wfs_url(base, {"SERVICE": "WFS", "REQUEST": "GetCapabilities"})
        async with httpx.AsyncClient(timeout=10) as client:
            await client.get(url)
    except Exception:
        pass

# -------------------------
#          Routes
# -------------------------

@app.get("/health")
def health():
    return {"status": "ok"}

# ---------- DXF-PCI FEUILLE (DGFiP) ----------
def _feuille_feature_by_point(lon: float, lat: float) -> dict:
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

# ---------- (NOUVEAU) LIEN GPU "parcel-info" ----------
def _parcelle_feature_by_point(lon: float, lat: float) -> dict:
    """
    Récupère la parcelle intersectant le point.
    """
    base_params = {
        "service": "WFS",
        "version": WFS_VERSION,
        "request": "GetFeature",
        "typeNames": TYPENAME_PARCELLE,
        "srsName": "EPSG:4326",
        "outputFormat": "application/json",
    }

    def _call(params):
        r = httpx.get(WFS_BASE, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        return data.get("features", [])

    # Essais : INTERSECTS puis petit buffer
    p1 = dict(base_params, CQL_FILTER=f"INTERSECTS(geom,SRID=4326;POINT({lon} {lat}))")
    feats = _call(p1)

    if not feats:
        p2 = dict(base_params, CQL_FILTER=f"DWITHIN(geom,SRID=4326;POINT({lon} {lat}),0.5,meters)")
        feats = _call(p2)

    if not feats:
        raise HTTPException(status_code=404, detail="Aucune parcelle trouvée pour ce point.")
    return feats[0]["properties"]

def _normalize_prefixe(val) -> str:
    """
    Dans PCI, 'PREFIXE' est souvent '000'. On force 3 chiffres.
    """
    if val is None or val == "":
        return "000"
    return str(val).zfill(3)

def _normalize_numero(val) -> str:
    """
    Numéro de parcelle sur 4 chiffres.
    """
    return str(val).zfill(4)

@app.get("/gpu/parcel-link/by-point")
async def gpu_parcel_link_by_point(
    lon: float = Query(...),
    lat: float = Query(...),
    debug: bool = Query(False)
):
    """
    Construit l'URL Géoportail Urbanisme 'parcel-info' pour la parcelle au point.
    Format attendu : /map/parcel-info/{dep}_{com}_{com_abs}_{prefixe}_{section}_{numero}/
    Exemple fourni : .../map/parcel-info/34_032_000_000_LX_0209/
    """
    props = _parcelle_feature_by_point(lon, lat)

    code_dep = str(_pick(props, "CODE_DEP", "code_dep", "dep")).zfill(2)
    code_com = str(_pick(props, "CODE_COM", "code_com", "com")).zfill(3)
    com_abs  = _pick(props, "COM_ABS", "com_abs")
    com_abs  = str(com_abs if com_abs is not None else "000").zfill(3)

    prefixe  = _normalize_prefixe(_pick(props, "PREFIXE", "prefixe"))
    section  = _normalize_section(_pick(props, "SECTION", "section"))
    numero   = _normalize_numero(_pick(props, "NUMERO", "numero", "PARCELLE", "parcelle"))

    gpu_url = (
        "https://www.geoportail-urbanisme.gouv.fr/map/parcel-info/"
        f"{code_dep}_{code_com}_{com_abs}_{prefixe}_{section}_{numero}/"
    )

    out = {
        "code_dep": code_dep,
        "code_com": code_com,
        "com_abs": com_abs,
        "prefixe": prefixe,
        "section": section,
        "numero": numero,
        "gpu_url": gpu_url,
        "source": "Géoportail de l’Urbanisme (parcel-info)",
    }
    if debug:
        out["wfs_props"] = props
    return out

# ---------- PLU (zonage) ----------
@app.get("/plu/by-point")
async def plu_by_point(lon: float = Query(...), lat: float = Query(...)):
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
            suffix = nomfic if str(nomfic).lower().endswith(".pdf") else f"{nomfic}.pdf"
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

# ---------- WFS generic (réutilisé pour INPN & ex-Atlas) ----------
def _bbox_deg_around_point(lon: float, lat: float, radius_m: float = 7.5) -> Tuple[float, float, float, float]:
    dlat = radius_m / 110_574.0
    dlon = radius_m / (111_320.0 * math.cos(math.radians(lat)) or 1e-6)
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)

async def _wfs_hits_by_bbox(base: str, typename: str, lon: float, lat: float) -> dict:
    minx, miny, maxx, maxy = _bbox_deg_around_point(lon, lat, radius_m=7.5)

    # Essai 1 : WFS 1.0.0
    params1 = {
        "SERVICE": "WFS", "VERSION": "1.0.0", "REQUEST": "GetFeature",
        "TYPENAME": typename, "SRS": "EPSG:4326", "OUTPUTFORMAT": "geojson",
        "BBOX": f"{minx},{miny},{maxx},{maxy}",
    }
    url1 = build_wfs_url(base, params1)

    features = []
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r1 = await client.get(url1)
        r1.raise_for_status()
        data = r1.json()
        features = data.get("features", [])
    except Exception:
        # Essai 2 : WFS 2.0.0
        params2 = {
            "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
            "TYPENAMES": typename, "SRSNAME": "EPSG:4326",
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

# ---------- INPN (WFS) : Natura 2000, ZNIEFF, ZICO ----------
@app.get("/inpn/summary/by-point")
async def inpn_summary_by_point(
    lon: float = Query(...),
    lat: float = Query(...),
    warmup: bool = Query(True, description="GetCapabilities avant GetFeature (best-effort)")
):
    layers_cfg = getattr(CONFIG, "inpn_layers_wfs", {}) or {}
    if not layers_cfg:
        return {
            "note": "Aucune couche INPN WFS configurée (config.inpn_layers_wfs).",
            "layers": {}
        }

    results = {}; total_hits = 0
    for key, meta in layers_cfg.items():
        base = meta["base"]; tname = meta["typename"]
        pretty = meta.get("pretty", key); source = meta.get("source", "INPN WFS")
        try:
            if warmup:
                await _wfs_warmup(base)
            res = await _wfs_hits_by_bbox(base, tname, lon, lat)
            results[key] = {"pretty": pretty, "source": source, "count": res["count"], "hits": res["features"][:10]}
            total_hits += res["count"]
        except Exception as e:
            results[key] = {"pretty": pretty, "source": source, "count": 0, "hits": [], "error": str(e)}

    return {"any_hit": total_hits > 0, "total_hits": total_hits, "layers": results}

# ---------- GPU (REST) : SUP & PLU (EBC/paysage) ----------
async def _gpu_get(path: str, geom_point: dict) -> dict:
    url = f"{APICARTO_GPU_BASE}/{path}"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, params={"geom": json.dumps(geom_point)})
        r.raise_for_status()
        return r.json()

def _norm(s):
    return (str(s or "")).strip()

def _has_paysage(words: list[str], *vals: str) -> bool:
    blob = " ".join(_norm(v).lower() for v in vals)
    return any(w.lower() in blob for w in words)

# --- NOUVEAU: petit disque WGS84 pour bufferiser le point (25 m par défaut) ---
def _point_buffer_polygon_wgs84(lon: float, lat: float, radius_m: float = 25.0, n: int = 24) -> dict:
    """
    Disque approx. autour du point en WGS84 pour interroger l'API GPU par polygon.
    """
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    coords = []
    for i in range(n):
        a = 2 * math.pi * i / n
        coords.append([lon + dlon * math.cos(a), lat + dlat * math.sin(a)])
    coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}

@app.get("/gpu/summary/by-point")
async def gpu_summary_by_point(
    lon: float = Query(...),
    lat: float = Query(...),
):
    # Utilise un POLYGON (buffer 25 m) pour éviter les faux négatifs sur limites
    geom_point = _point_buffer_polygon_wgs84(lon, lat, radius_m=25.0)
    F = CONFIG.gpu_filters

    # 1) SUP — assiettes (S/L/P)
    sup_paths = ["assiette-sup-s", "assiette-sup-l", "assiette-sup-p"]
    sup_features: list[dict] = []
    for p in sup_paths:
        try:
            data = await _gpu_get(p, geom_point)
            sup_features.extend(data.get("features") or [])
        except Exception:
            # on continue: toutes les communes n'ont pas toutes les assiettes
            pass

    def prop(f, *keys):
        return _pick((f.get("properties") or {}), *keys)

    sup_buckets = {
        "AC1": {"pretty": "Abords MH (AC1)", "source": "API Carto GPU", "items": []},
        "AC2": {"pretty": "Sites classés/inscrits (AC2)", "source": "API Carto GPU", "items": []},
        "AC4": {"pretty": "Site patrimonial remarquable (AC4)", "source": "API Carto GPU", "items": []},
        "PPR": {"pretty": "Plans de prévention des risques (PPR*)", "source": "API Carto GPU", "items": []},
    }

    for f in sup_features:
        code = prop(f, "sup_code", "categorie_code", "code", "CODE", "categorie")
        label = prop(f, "libelle", "LIBELLE", "nom", "NOM", "intitule", "INTITULE") or "(sans libellé)"
        rec = {"id": f.get("id"), "label": str(label), "properties": f.get("properties") or {}}

        scode = str(code or "").upper().strip()
        if scode in set(map(str.upper, F["AC1_codes"])):
            sup_buckets["AC1"]["items"].append(rec)
        elif scode in set(map(str.upper, F["AC2_codes"])):
            sup_buckets["AC2"]["items"].append(rec)
        elif scode in set(map(str.upper, F["AC4_codes"])):
            sup_buckets["AC4"]["items"].append(rec)
        elif scode.startswith(str(F["PPR_prefix"]).upper()):
            sup_buckets["PPR"]["items"].append(rec)

    # 2) PLU — prescriptions / informations → EBC & éléments de paysage
    pres_paths = ["prescription-s", "prescription-l", "prescription-p"]
    info_paths = ["information-s", "information-l", "information-p"]
    pres_features: list[dict] = []; info_features: list[dict] = []

    for p in pres_paths:
        try:
            data = await _gpu_get(p, geom_point)
            pres_features.extend(data.get("features") or [])
        except Exception:
            pass

    for p in info_paths:
        try:
            data = await _gpu_get(p, geom_point)
            info_features.extend(data.get("features") or [])
        except Exception:
            pass

    buckets_plu = {
        "EBC": {"pretty": "Espaces boisés classés (EBC)", "source": "API Carto GPU", "items": []},
        "PAYSAGE": {"pretty": "Éléments/paysage à préserver", "source": "API Carto GPU", "items": []},
    }

    # EBC par code (p.ex. "01") sur prescriptions
    for f in pres_features:
        code = prop(f, "code", "CODE", "type_code", "typeCode")
        label = prop(f, "libelle", "LIBELLE", "nom", "NOM", "intitule", "INTITULE") or "(sans libellé)"
        rec = {"id": f.get("id"), "label": str(label), "properties": f.get("properties") or {}}
        if str(code or "").strip() in F.get("EBC_codes", []):
            buckets_plu["EBC"]["items"].append(rec)
        elif _has_paysage(F.get("paysage_keywords", []), label, code):
            buckets_plu["PAYSAGE"]["items"].append(rec)

    # Informations : on cherche des indices de paysage/éléments remarquables
    for f in info_features:
        code = prop(f, "code", "CODE", "type_code", "typeCode")
        label = prop(f, "libelle", "LIBELLE", "nom", "NOM", "intitule", "INTITULE") or "(sans libellé)"
        rec = {"id": f.get("id"), "label": str(label), "properties": f.get("properties") or {}}
        if _has_paysage(F.get("paysage_keywords", []), label, code):
            buckets_plu["PAYSAGE"]["items"].append(rec)

    # Compose la réponse homogène
    out_sup = {}
    total_sup = 0
    for k, bucket in sup_buckets.items():
        cnt = len(bucket["items"]); total_sup += cnt
        out_sup[k] = {
            "pretty": bucket["pretty"],
            "source": bucket["source"],
            "count": cnt,
            "hits": bucket["items"][:10]
        }

    out_plu = {}
    total_plu = 0
    for k, bucket in buckets_plu.items():
        cnt = len(bucket["items"]); total_plu += cnt
        out_plu[k] = {
            "pretty": bucket["pretty"],
            "source": bucket["source"],
            "count": cnt,
            "hits": bucket["items"][:10]
        }

    return {
        "sup": {"total_hits": total_sup, "layers": out_sup},
        "plu": {"total_hits": total_plu, "layers": out_plu},
        "any_hit": (total_sup + total_plu) > 0
    }

# ---------- (Compat) Atlas Patrimoines single-link ----------
@app.get("/heritage/by-point")
async def heritage_by_point(lon: float = Query(...), lat: float = Query(...)):
    if not getattr(CONFIG, "atlas_layers", None):
        raise HTTPException(status_code=500, detail="Atlas WFS non configuré (atlas_layers vide).")
    # On prend arbitrairement la première couche (compat historique)
    first_key = next(iter(CONFIG.atlas_layers))
    meta = CONFIG.atlas_layers[first_key]
    url = wfs_shapezip_url(meta["base"], meta["typename"], lon, lat, WFS_VERSION)
    return {"download_url": url}

# ---------- (NOUVEAU) "Heritage summary" basé GPU uniquement ----------
@app.get("/heritage/summary/by-point")
async def heritage_summary_by_point(
    lon: float = Query(...),
    lat: float = Query(...),
):
    """
    Résumé des protections 'patrimoniales' basé UNIQUEMENT sur l’API Carto GPU:
      - SPR  (AC4)
      - ZPPAUP/AVAP  → alias de SPR (héritage : remplacées par les SPR)
      - Abords MH  (AC1)
      - Sites classés / Sites inscrits  (AC2, séparés par mots-clés dans le libellé)
      - MH classés / MH inscrits  → non disponibles via GPU (objets MH ≠ SUP)
    """
    geom_point = {"type": "Point", "coordinates": [lon, lat]}

    # 1) Récupération des assiettes SUP (S/L/P)
    sup_paths = ["assiette-sup-s", "assiette-sup-l", "assiette-sup-p"]
    sup_features: list[dict] = []
    for p in sup_paths:
        try:
            data = await _gpu_get(p, geom_point)
            sup_features.extend(data.get("features") or [])
        except Exception:
            pass  # tolérance: toutes les communes n'ont pas toutes les assiettes

    def _best_label(props: Dict[str, Any]) -> str:
        for k in ("libelle","LIBELLE","nom","NOM","intitule","INTITULE","appellation","APPELLATION","titre","TITRE","denomination","DENOMINATION"):
            if props.get(k):
                return str(props[k])
        for k, v in (props or {}).items():
            if isinstance(v, (str, int, float)) and str(v).strip():
                return f"{k}: {v}"
        return "(sans libellé)"

    # Buckets
    hits_spr: list[dict] = []            # AC4
    hits_abords: list[dict] = []         # AC1
    ac2_all: list[dict] = []             # AC2 (à séparer en classés/inscrits)

    for f in sup_features:
        props = (f.get("properties") or {})
        scode = str(_pick(props, "sup_code", "categorie_code", "code", "CODE", "categorie") or "").upper().strip()
        label = _best_label(props)
        rec = {"id": f.get("id"), "label": label, "properties": props}

        if scode == "AC4":
            hits_spr.append(rec)
        elif scode == "AC1":
            hits_abords.append(rec)
        elif scode == "AC2":
            ac2_all.append(rec)

    # Séparer AC2 en "Sites classés" vs "Sites inscrits" par mots-clés du libellé
    import re as _re
    def _match_any(s: str, words: list[str]) -> bool:
        s = (s or "")
        return any(_re.search(rf"\b{w}\w*", s, flags=_re.IGNORECASE) for w in words)

    sites_classes = [r for r in ac2_all if _match_any(r["label"], ["classé","classée","classés","classées"])]
    sites_inscrits = [r for r in ac2_all if _match_any(r["label"], ["inscrit","inscrite","inscrits","inscrites"])]

    # MH classés / inscrits → non fournis par l’API GPU (seuls les abords AC1 existent côté SUP)
    mh_classes = []
    mh_inscrits = []

    layers = {
        "SPR": {
            "pretty": "Sites patrimoniaux remarquables (SPR)",
            "source": "API Carto GPU — SUP AC4",
            "count": len(hits_spr),
            "hits": hits_spr[:10],
        },
        "ZPPAUP_AVAP": {
            "pretty": "ZPPAUP / AVAP (→ SPR)",
            "source": "API Carto GPU — alias SUP AC4",
            "count": len(hits_spr),
            "hits": hits_spr[:10],
            "note": "Les ZPPAUP/AVAP ont été remplacées par les SPR (AC4).",
        },
        "MH_classes": {
            "pretty": "Monuments historiques classés",
            "source": "API Carto GPU",
            "count": len(mh_classes),
            "hits": mh_classes,
            "available": False,
            "note": "Non disponible via GPU (les objets MH ne sont pas des SUP).",
        },
        "MH_inscrits": {
            "pretty": "Monuments historiques inscrits",
            "source": "API Carto GPU",
            "count": len(mh_inscrits),
            "hits": mh_inscrits,
            "available": False,
            "note": "Non disponible via GPU (les objets MH ne sont pas des SUP).",
        },
        "Abords_MH": {
            "pretty": "Abords MH (périmètre délimité ou rayon 500 m)",
            "source": "API Carto GPU — SUP AC1",
            "count": len(hits_abords),
            "hits": hits_abords[:10],
        },
        "Sites_classes": {
            "pretty": "Sites classés",
            "source": "API Carto GPU — SUP AC2",
            "count": len(sites_classes),
            "hits": sites_classes[:10],
        },
        "Sites_inscrits": {
            "pretty": "Sites inscrits",
            "source": "API Carto GPU — SUP AC2",
            "count": len(sites_inscrits),
            "hits": sites_inscrits[:10],
        },
    }

    total = sum(layers[k]["count"] for k in layers)
    return {"any_protection": total > 0, "total_hits": total, "layers": layers}

# -------------------------
#    KMZ/KML: parsing
# -------------------------

def _resolve_path(p: str) -> str:
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
    return ET.parse(path).getroot()

def _float2(s: str):
    try:
        return float(s.replace(",", "."))
    except Exception:
        return None

def parse_kml_points(path: str):
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
