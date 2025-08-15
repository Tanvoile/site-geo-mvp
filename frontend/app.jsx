// Pas d'import ESM ici. On utilise les globaux UMD: React et ReactDOM.
console.log("app.jsx chargé");

const { useState } = React;

const API = (path, qs) => {
  const base = window.API_BASE || "http://localhost:8000";
  const q = qs ? "?" + new URLSearchParams(qs).toString() : "";
  return `${base}${path}${q}`;
};

// Parse "lat, lon" (ou "lat lon", "lat;lon", etc.), tolère points/virgules
function parseLatLon(str) {
  if (!str) return null;
  const nums = (str.match(/-?\d+(?:[.,]\d+)?/g) || []).slice(0, 2).map(v =>
    Number(v.replace(",", "."))
  );
  if (nums.length !== 2 || !nums.every(Number.isFinite)) return null;
  const [lat, lon] = nums; // on suppose "lat, lon"
  return { lat, lon };
}

function App() {
  const [lon, setLon] = useState(2.3522);
  const [lat, setLat] = useState(48.8566);
  const [paste, setPaste] = useState("");
  const [err, setErr] = useState("");

  // Uniquement ce qu'il faut pour le lien GPU
  const [parcelInfo, setParcelInfo] = useState(null);

  const applyPasted = (text) => {
    const parsed = parseLatLon(text ?? paste);
    if (!parsed) return setErr("Coordonnées collées invalides. Format: lat, lon");
    setLat(parsed.lat); setLon(parsed.lon); setErr("");
  };

  const swap = () => { const a = lon; setLon(lat); setLat(a); };

  const run = async () => {
    setErr("");
    setParcelInfo(null);

    const lonNum = Number(String(lon).replace(",", "."));
    const latNum = Number(String(lat).replace(",", "."));
    if (!Number.isFinite(lonNum) || !Number.isFinite(latNum)) {
      setErr("Coordonnées invalides (ex: 48.8566 / 2.3522).");
      return;
    }

    const fetchJSON = async (path, qs) => {
      const res = await fetch(API(path, qs));
      const txt = await res.text();
      if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${txt}`);
      try { return JSON.parse(txt); } catch { return txt; }
    };

    try {
      const pi = await fetchJSON('/parcel-info/by-point', { lon: lonNum, lat: latNum });
      setParcelInfo(pi);
    } catch (e) {
      setErr("Parcel-info: " + (e?.message || String(e)));
    }
  };

  return (
    <div style={{maxWidth: 860, margin: '0 auto', padding:'0 12px'}}>
      <h1>Site GEO — MVP</h1>
      <p>Entrez un point GPS (WGS84) ou collez-le directement. Le front affiche uniquement le lien vers la fiche parcelle du GPU.</p>

      {/* Champ pour coller "lat, lon" */}
      <div style={{display:'flex', gap:8, alignItems:'center', marginBottom:8}}>
        <input
          placeholder="Ex: 43.32047104103794, 3.2202660369625726"
          value={paste}
          onChange={e=>setPaste(e.target.value)}
          onPaste={e => {
            const text = e.clipboardData?.getData("text");
            if (text) { e.preventDefault(); setPaste(text); applyPasted(text); }
          }}
          style={{flex:1, padding:'6px 8px'}}
        />
        <button onClick={()=>applyPasted()}>Appliquer</button>
        <button onClick={swap} title="Inverser lat/lon">↔︎</button>
      </div>

      {/* Édition fine */}
      <div style={{display:'flex', gap:12, alignItems:'center', marginBottom:12}}>
        <label>Lon{" "}
          <input type="number" step="0.000001" value={lon} onChange={e=>setLon(e.target.value)} style={{width:180}}/>
        </label>
        <label>Lat{" "}
          <input type="number" step="0.000001" value={lat} onChange={e=>setLat(e.target.value)} style={{width:180}}/>
        </label>
        <button onClick={run}>Lancer</button>
      </div>

      {err && <p style={{color:'crimson'}}>Erreurs: {err}</p>}

      {/* ======= Lien unique vers la fiche parcelle GPU ======= */}
      <section>
        <h2>Parcelle — fiche Géoportail Urbanisme</h2>
        {parcelInfo && parcelInfo.gpu_url ? (
          <p>
            <a href={parcelInfo.gpu_url} target="_blank" rel="noopener">
              {parcelInfo.gpu_url}
            </a>
          </p>
        ) : (
          <p>Aucune requête effectuée.</p>
        )}
      </section>
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
