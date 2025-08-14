# ──────────────────────────────────────────────────────────────────────────────
# config.py
# ──────────────────────────────────────────────────────────────────────────────
from pydantic import BaseModel

class Settings(BaseModel):
    # =========================================================================
    # 1) IGN — Parcellaire Express (Feuilles cadastrales, WFS public)
    #    (noms alignés avec main.py : ign_base / ign_feuille_typename / ign_version)
    # =========================================================================
    ign_base: str = "https://data.geopf.fr/wfs/ows"
    ign_feuille_typename: str = "CADASTRALPARCELS.PARCELLAIRE_EXPRESS:feuille"
    ign_version: str = "2.0.0"

    # Aliases "legacy" (si du code ailleurs les utilise encore)
    cadastre_wfs_base: str = ign_base
    cadastre_typename: str = ign_feuille_typename

    # =========================================================================
    # 2) GPU (Géoportail de l’Urbanisme) — API Carto (REST) recommandée
    # =========================================================================
    gpu_base: str = "https://apicarto.ign.fr/api/gpu"
    gpu_typename: str = "zone-urba"
    # Exemples côté serveur (à titre indicatif) :
    #   GET {gpu_base}/{gpu_typename}?geom=POINT({lon} {lat})&srid=4326
    #   GET {gpu_base}/{gpu_typename}?bbox=minx,miny,maxx,maxy&srid=4326

    # Option WFS brute (non conseillée, laissé vide volontairement)
    # gpu_base_wfs: str = ""
    # gpu_typename_wfs: str = "PLU:ZONE_URBA"

    # =========================================================================
    # 3) Atlas des Patrimoines — couches MapServer WFS par jeu de données
    #    On centralise ici les couches utiles pour ton récap protections.
    #    Si une couche retourne 0 alors que tu es sûr d’être dedans, on ajustera
    #    le typename ou le map=… (certains jeux sont régionaux).
    # =========================================================================
    atlas_layers: dict = {
        # Sites patrimoniaux remarquables (SPR)
        "spr": {
            "base": (
                "http://atlas.patrimoines.culture.fr/cgi-bin/mapserv"
                "?map=/home/atlas-mapserver/production/var/data/MD_865/MD_865.map"
            ),
            "typename": "MD_865",
            "pretty": "Site patrimonial remarquable (SPR)",
        },
        # Ex-ZPPAUP / AVAP (anciennes ZPPA)
        "zppaup_avap": {
            "base": (
                "http://atlas.patrimoines.culture.fr/cgi-bin/mapserv"
                "?map=/home/atlas-mapserver/production/var/data/MD_616/MD_616.map"
            ),
            "typename": "MD_616",
            "pretty": "ZPPAUP / AVAP (historique)",
        },
        # Monuments historiques classés
        "mh_classes": {
            "base": (
                "http://atlas.patrimoines.culture.fr/cgi-bin/mapserv"
                "?map=/home/atlas-mapserver/production/var/data/MD_001/MD_001.map"
            ),
            "typename": "MD_001",
            "pretty": "Monument historique classé",
        },
        # Monuments historiques inscrits
        "mh_inscrits": {
            "base": (
                "http://atlas.patrimoines.culture.fr/cgi-bin/mapserv"
                "?map=/home/atlas-mapserver/production/var/data/MD_002/MD_002.map"
            ),
            "typename": "MD_002",
            "pretty": "Monument historique inscrit",
        },
        # Protection au titre des abords (rayon 500 m ou périmètre délimité)
        "abords_mh": {
            "base": (
                "http://atlas.patrimoines.culture.fr/cgi-bin/mapserv"
                "?map=/home/atlas-mapserver/production/var/data/MD_041/MD_041.map"
            ),
            "typename": "MD_041",
            "pretty": "Protection au titre des abords (MH)",
        },
        # Sites classés
        "sites_classes": {
            "base": (
                "http://atlas.patrimoines.culture.fr/cgi-bin/mapserv"
                "?map=/home/atlas-mapserver/production/var/data/MD_508/MD_508.map"
            ),
            "typename": "MD_508",
            "pretty": "Site classé",
        },
        # Sites inscrits
        "sites_inscrits": {
            "base": (
                "http://atlas.patrimoines.culture.fr/cgi-bin/mapserv"
                "?map=/home/atlas-mapserver/production/var/data/MD_509/MD_509.map"
            ),
            "typename": "MD_509",
            "pretty": "Site inscrit",
        },
    }

    # Champ géométrique le plus courant sur l’Atlas (modifiable au besoin)
    atlas_geom_field: str = "geom"

    # =========================================================================
    # 4) Aéroports — chemin du fichier (KML ou KMZ)
    # =========================================================================
    # Mets .kmz si c’est ce que tu as en prod : "backend/data/aerodromes_fr.kmz"
    aerodromes_kml: str = "backend/data/aerodromes_fr.kmz"

    # =========================================================================
    # 5) CORS
    # =========================================================================
    cors_allow_origins: list[str] = ["*"]

CONFIG = Settings()
