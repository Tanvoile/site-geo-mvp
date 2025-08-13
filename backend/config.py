from dataclasses import dataclass

@dataclass
class WFSConfig:
    # --- IGN Parcellaire Express (feuille) ---
    ign_base: str = "https://data.geopf.fr/wfs/ows"
    ign_version: str = "2.0.0"
    ign_feuille_typename: str = "CADASTRALPARCELS.PARCELLAIRE_EXPRESS:feuille"

    # --- GPU (Géoportail de l'Urbanisme) ---
    gpu_base: str = "(A RENSEIGNER)"
    gpu_typename: str = "(A RENSEIGNER)"

    # --- Atlas des patrimoines ---
    atlas_base: str = "(A RENSEIGNER)"
    atlas_typename: str = "(A RENSEIGNER)"

    # --- Aéroports ---
    aerodromes_kml: str = "backend/data/aerodromes_fr.kml"

CONFIG = WFSConfig()
