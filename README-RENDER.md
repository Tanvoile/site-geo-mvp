
# Déploiement chez Render (tout-en-un)

Ce dépôt contient **backend** (FastAPI) + **frontend** (statique). Un fichier **render.yaml** permet un déploiement en un clic chez Render (Blueprint).

## Étapes

1) Crée un **nouveau dépôt Git** (GitHub, GitLab…). Copie-y tout le contenu de ce dossier.
2) Sur https://render.com → **New +** → **Blueprint** → connecte ton dépôt → valide.
3) Choisis la région **Frankfurt** (EU) pour les deux services.
4) Attends la fin du build.

### Après déploiement
- Dans Render, ouvre le service **geo-backend** et récupère son **URL publique** (ex: `https://geo-backend-xxxx.onrender.com`).
- Va sur le service **geo-frontend** → **Environment** → clique **Edit Files** (ou redeploie) et édite `frontend/index.html` pour définir :
  ```html
  <script>window.API_BASE = "https://geo-backend-xxxx.onrender.com";</script>
  ```
  Puis redeploie le **frontend**.

### Aéroports KML
- Dans le service **geo-backend** → **Files** (ou via un commit), place ton fichier `aerodromes_fr.kml` dans `backend/data/`.
- Sinon, modifie `backend/config.py` pour pointer vers un autre chemin public.

### Tester
- Frontend: URL Render du **geo-frontend**
- API docs (backend): `https://geo-backend-xxxx.onrender.com/docs`
- Santé: `/health`

### Notes
- CORS est ouvert (`*`) par défaut. En prod, restreins aux domaines de ton front.
- Pour PLU/Atlas, complète les WFS dans `backend/config.py` (`gpu_base`, `gpu_typename`, `atlas_base`, `atlas_typename`).

Bon déploiement !
