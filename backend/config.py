# ──────────────────────────────────────────────────────────────────────────────
# config.py
# ──────────────────────────────────────────────────────────────────────────────
from pydantic import BaseModel

class Settings(BaseModel):
    # =========================================================================
    # 1) Feuille cadastrale (IGN – Parcellaire Express, WFS public)
    #    -> déjà OK chez toi ; je laisse la même base standard data.geopf.fr
    # =========================================================================
    cadastre_wfs_base: str = "https://data.geopf.fr/wfs/ows"
    cadastre_typename: str = "CADASTRALPARCELS.PARCELLAIRE_EXPRESS:feuille"

    # =========================================================================
    # 2) GPU (Géoportail de l’Urbanisme) — RECOMMANDÉ: API Carto (REST)
    #    Avantage : endpoint stable, et on interroge directement la ressource
    #    “zone-urba” par point/BBOX sans se battre avec 36 WFS hétérogènes.
    #    Si ton code construit déjà une URL WFS brute, vois l’alternative WFS
    #    plus bas (section « Option WFS brute (non conseillée) »).
    # =========================================================================
    # [LIGNE À MODIF SI BESOIN] (vers ~22)
    gpu_base: str = "https://apicarto.ign.fr/api/gpu"
    # Ressource cible (ton backend peut utiliser ça pour composer l’URL finale)
    gpu_typename: str = "zone-urba"

    # Exemple d’appel que ton backend peut construire côté serveur :
    #   GET {gpu_base}/{gpu_typename}?geom=POINT({lon} {lat})&srid=4326
    # ou avec bbox:
    #   GET {gpu_base}/{gpu_typename}?bbox={minx},{miny},{maxx},{maxy}&srid=4326

    # ── Option WFS brute (non conseillée) ─────────────────────────────────────
    # Le GPU n’expose pas un unique WFS "national" de zonage homogène ;
    # chaque DU a son flux, souvent via ATOM/WFS producteur. Si tu tiens
    # absolument à WFS, laisse gpu_base vide et gère au cas par cas.
    # gpu_base_wfs: str = ""
    # gpu_typename_wfs: str = "PLU:ZONE_URBA"  # schéma CNIG générique (indicatif)

    # =========================================================================
    # 3) Atlas des Patrimoines (Ministère Culture) — WFS MapServer
    #    Attention : l’Atlas publie des couches « par jeu » (pas un unique WFS).
    #    Ci‑dessous, je te mets une couche **SPR (sites patrimoniaux remarquables)**
    #    FR‑métropole via leur MapServer (couche agrégée). Si tu veux d’autres
    #    couches (ZPPAUP historiques, périmètres MH, etc.), change `atlas_typename`
    #    et éventuellement l’URL (certaines couches sont par région/département).
    # =========================================================================
    # [LIGNE À MODIF SI BESOIN] (vers ~46)
    atlas_base: str = (
        "http://atlas.patrimoines.culture.fr/cgi-bin/mapserv"
        "?map=/home/atlas-mapserver/production/var/data/MD_865/MD_865.map"
    )
    atlas_typename: str = "MD_865"  # SPR (ex couche agrégée). À adapter si besoin.

    # Exemple d’appel WFS que ton backend peut construire :
    #   {atlas_base}&SERVICE=WFS&VERSION=1.0.0&REQUEST=GetFeature
    #   &TYPENAME={atlas_typename}&SRS=EPSG:4326
    #   &BBOX={miny},{minx},{maxy},{maxx}   # (attention ordre selon version)

    # =========================================================================
    # 4) Aéroports (anti‑proximité) — chemin KML dans l’image déployée
    # =========================================================================
    # [LIGNE À MODIF SI BESOIN] (vers ~62)
    aerodromes_kml: str = "backend/data/aerodromes_fr.kmz"

    # =========================================================================
    # 5) Divers
    # =========================================================================
    cors_allow_origins: list[str] = ["*"]  # front sur Render : OK

CONFIG = Settings()
