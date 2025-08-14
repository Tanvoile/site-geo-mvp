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
    #    → servitudes (SUP), zonage, prescriptions/informations PLU
    # =========================================================================
    gpu_base: str = "https://apicarto.ign.fr/api/gpu"
    gpu_typename: str = "zone-urba"  # utilisé par /plu/by-point déjà présent

    # Filtrages métiers pour /gpu/summary/by-point
    # - SUP AC1 / AC2 / AC4 (patrimoine) + PPR* (risques)
    # - EBC (code CNIG souvent "01") + éléments de paysage (codes variables)
    gpu_filters: dict = {
        # Patrimoine (SUP)
        "AC1_codes": ["AC1"],   # Abords MH (périmètres délimités / rayon 500 m)
        "AC2_codes": ["AC2"],   # Sites classés / inscrits
        "AC4_codes": ["AC4"],   # SPR (ex ZPPAUP/AVAP)
        # Risques (SUP) — selon les publications: PPRN, PPRI, PPRT, PPRM...
        # On matche par préfixe "PPR" dans 'sup_code' ou 'categorie_code'
        "PPR_prefix": "PPR",

        # PLU — prescriptions/informations (codes CNIG)
        # EBC est standardisé en code "01" dans beaucoup de documents CNIG,
        # mais certaines collectivités utilisent d'autres codifications.
        "EBC_codes": ["01"],

        # Éléments de paysage à préserver: pas de code national unique
        # → on filtre par libellé si dispo (ex: "paysage", "élément remarquable")
        "paysage_keywords": ["paysage", "élément", "remarquable", "patrimoine végétal"],
    }

    # =========================================================================
    # 3) INPN (WFS publics) — Natura 2000, ZNIEFF, ZICO, etc.
    #    Renseigne ici les endpoints WFS **publics** que tu utilises.
    #    Le backend consommera ces couches via /inpn/summary/by-point.
    #    Exemple d’entrées (à adapter avec tes vraies URL/typenames).
    # =========================================================================
    inpn_layers_wfs: dict = {
        # --- NATURA 2000 (exemples à compléter) ---
        # "natura2000_zps": {
        #     "base": "https://<WFS_INPN>/wfs?SERVICE=WFS",
        #     "typename": "inpn:natura2000_zps",
        #     "pretty": "Natura 2000 — ZPS",
        #     "source": "INPN WFS"
        # },
        # "natura2000_zsc": {
        #     "base": "https://<WFS_INPN>/wfs?SERVICE=WFS",
        #     "typename": "inpn:natura2000_zsc",
        #     "pretty": "Natura 2000 — ZSC/SIC",
        #     "source": "INPN WFS"
        # },

        # --- ZNIEFF (exemples à compléter) ---
        # "znieff_type1": {
        #     "base": "https://<WFS_INPN>/wfs?SERVICE=WFS",
        #     "typename": "inpn:znieff_type1",
        #     "pretty": "ZNIEFF Type I",
        #     "source": "INPN WFS"
        # },
        # "znieff_type2": {
        #     "base": "https://<WFS_INPN>/wfs?SERVICE=WFS",
        #     "typename": "inpn:znieff_type2",
        #     "pretty": "ZNIEFF Type II",
        #     "source": "INPN WFS"
        # },

        # --- ZICO (exemple à compléter) ---
        # "zico": {
        #     "base": "https://<WFS_INPN>/wfs?SERVICE=WFS",
        #     "typename": "inpn:zico",
        #     "pretty": "ZICO",
        #     "source": "INPN WFS"
        # },
    }

    # =========================================================================
    # 4) (Ancien) Atlas des Patrimoines — laissé ici pour compat,
    #    mais les chemins "map=/home/atlas..." ne sont plus publics.
    #    Garde vide ou supprime si tu veux éviter toute requête obsolète.
    # =========================================================================
    atlas_layers: dict = {}

    atlas_geom_field: str = "geom"  # champ géométrique (pour les WFS MapServer/GeoServer)

    # =========================================================================
    # 5) Aéroports — chemin du fichier (KML ou KMZ)
    # =========================================================================
    aerodromes_kml: str = "backend/data/aerodromes_fr.kmz"

    # =========================================================================
    # 6) CORS
    # =========================================================================
    cors_allow_origins: list[str] = ["*"]

CONFIG = Settings()
