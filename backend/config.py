# ──────────────────────────────────────────────────────────────────────────────
# config.py
# ──────────────────────────────────────────────────────────────────────────────
from pydantic import BaseModel

class Settings(BaseModel):
    # =========================================================================
    # 1) IGN — Parcellaire Express (Feuilles cadastrales, WFS public)
    # =========================================================================
    ign_base: str = "https://data.geopf.fr/wfs/ows"
    ign_feuille_typename: str = "CADASTRALPARCELS.PARCELLAIRE_EXPRESS:feuille"
    ign_version: str = "2.0.0"

    # Aliases "legacy" (compat avec backend/main.py)
    cadastre_wfs_base: str = ign_base
    cadastre_typename: str = ign_feuille_typename

    # =========================================================================
    # 2) GPU (Géoportail de l’Urbanisme) — API Carto (REST)
    # =========================================================================
    gpu_base: str = "https://apicarto.ign.fr/api/gpu"
    gpu_typename: str = "zone-urba"

    gpu_filters: dict = {
        "AC1_codes": ["AC1"],   # Abords MH
        "AC2_codes": ["AC2"],   # Sites classés / inscrits
        "AC4_codes": ["AC4"],   # SPR
        "PPR_prefix": "PPR",
        "EBC_codes": ["01"],
        "paysage_keywords": ["paysage", "élément", "remarquable", "patrimoine végétal"],
    }

    # =========================================================================
    # 3) INPN (WFS publics) — Natura 2000, ZNIEFF, ZICO
    # =========================================================================
    inpn_layers_wfs: dict = {}

    # =========================================================================
    # 4) Atlas des Patrimoines — couches WFS
    # =========================================================================
    atlas_layers: dict = {
        "SPR": {
            "base": "https://data.culture.gouv.fr/wfs/atlas_patrimoines",
            "typename": "mh:site_patrimonial_remarquable",
            "pretty": "Sites patrimoniaux remarquables",
            "source": "Atlas des Patrimoines WFS"
        },
        "ZPPAUP_AVAP": {
            "base": "https://data.culture.gouv.fr/wfs/atlas_patrimoines",
            "typename": "mh:zppaup_avap",
            "pretty": "ZPPAUP / AVAP",
            "source": "Atlas des Patrimoines WFS"
        },
        "MH_classes": {
            "base": "https://data.culture.gouv.fr/wfs/atlas_patrimoines",
            "typename": "mh:monument_historique_classe",
            "pretty": "Monuments historiques classés",
            "source": "Atlas des Patrimoines WFS"
        },
        "MH_inscrits": {
            "base": "https://data.culture.gouv.fr/wfs/atlas_patrimoines",
            "typename": "mh:monument_historique_inscrit",
            "pretty": "Monuments historiques inscrits",
            "source": "Atlas des Patrimoines WFS"
        },
        "Abords_MH": {
            "base": "https://data.culture.gouv.fr/wfs/atlas_patrimoines",
            "typename": "mh:abords_monument_historique",
            "pretty": "Abords MH (500 m ou périmètre délimité)",
            "source": "Atlas des Patrimoines WFS"
        },
        "Sites_classes": {
            "base": "https://data.culture.gouv.fr/wfs/atlas_patrimoines",
            "typename": "mh:site_classe",
            "pretty": "Sites classés",
            "source": "Atlas des Patrimoines WFS"
        },
        "Sites_inscrits": {
            "base": "https://data.culture.gouv.fr/wfs/atlas_patrimoines",
            "typename": "mh:site_inscrit",
            "pretty": "Sites inscrits",
            "source": "Atlas des Patrimoines WFS"
        }
    }

    atlas_geom_field: str = "geom"

    # =========================================================================
    # 5) Aéroports — fichier KML/KMZ
    # =========================================================================
    aerodromes_kml: str = "backend/data/aerodromes_fr.kmz"

    # =========================================================================
    # 6) CORS
    # =========================================================================
    cors_allow_origins: list[str] = ["*"]

CONFIG = Settings()
