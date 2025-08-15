// Pas d'import ESM ici. On utilise les globaux UMD: React et ReactDOM.
console.log("app.jsx chargé");

const { useState, useEffect } = React;

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

function Pill({ ok, children }) {
  return (
    <span style={{
      display:'inline-block',
      minWidth:22, textAlign:'center',
      marginRight:8, padding:'2px 6px',
      borderRadius:6,
      background: ok ? '#e6ffed' : '#ffecec',
      border: '1px solid ' + (ok ? '#34c759' : '#ff3b30')
    }}>
      {ok ? "✓" : "✗"} {children}
    </span>
  );
}

function App() {
  const [lon, setLon] = useState(2.3522);
  const [lat, setLat] = useState(48.8566);
  const [paste, setPaste] = useState("");

  const [sheet, setSheet] = useState(null);
  const [plu, setPlu] = useState(null);
  const [urbanisme, setUrbanisme] = useState(null);

  // Nouveau: résumé des protections Atlas
  const [heritageSummary, setHeritageSummary] = useState(null);

  const [airport, setAirport] = useState(null);
  const [err, setErr] = useState("");

  // Styles globaux (fond, police)
  useEffect(() => {
    document.body.style.margin = "0";
    document.body.style.fontFamily = "system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif";
    document.body.style.background = "linear-gradient(135deg, #FFD84C 0%, #6BCB77 100%)";
  }, []);

  const applyPasted = (text) => {
    const parsed = parseLatLon(text ?? paste);
    if (!parsed) return setErr("Coordonnées collées invalides. Format: lat, lon");
    setLat(parsed.lat); setLon(parsed.lon); setErr("");
  };

  const swap = () => { const a = lon; setLon(lat); setLat(a); };

  const run = async () => {
    setErr("");
    setSheet(null); setPlu(null); setUrbanisme(null);
    setHeritageSummary(null); setAirport(null);

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

    try { setSheet(await fetchJSON('/sheet/by-point', { lon: lonNum, lat: latNum })); }
    catch (e) { setErr(prev => (prev ? prev + " | " : "") + "Feuille: " + e.message); }

    try { setPlu(await fetchJSON('/plu/by-point', { lon: lonNum, lat: latNum })); }
    catch (e) { setErr(prev => (prev ? prev + " | " : "") + "PLU: " + e.message); }

    // Statut d'urbanisme (si ton backend l'a ajouté)
    try { setUrbanisme(await fetchJSON('/urbanisme/status/by-point', { lon: lonNum, lat: latNum })); }
    catch (e) { /* optionnel: silencieux si pas implémenté */ }

    // >>> Atlas des patrimoines - résumé (nouveau)
    try { setHeritageSummary(await fetchJSON('/heritage/summary/by-point', { lon: lonNum, lat: latNum })); }
    catch (e) {
      setHeritageSummary({ not_available: true, error: String(e.message || e) });
    }

    try { setAirport(await fetchJSON('/airport/check', { lon: lonNum, lat: latNum, buffer_m: 1000 })); }
    catch (e) { setErr(prev => (prev ? prev + " | " : "") + "Aéroport: " + e.message); }
  };

  return (
    <div style={{
      maxWidth: 940,
      margin: '24px auto',
      padding:'16px 16px 32px',
      background: 'rgba(255,255,255,0.92)',
      borderRadius: '16px',
      boxShadow: '0 10px 30px rgba(0,0,0,0.12)'
    }}>
      {/* Header avec logo + titre */}
      <header style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '16px',
        paddingBottom: '12px',
        borderBottom: '3px solid #6BCB77'
      }}>
        <div style={{display:'flex', alignItems:'center', gap:12}}>
          <img
            src="./Logo-DevEnR-web.png"
            alt="Logo Dev'EnR"
            style={{height: '56px', width:'auto'}}
          />
          <h1 style={{margin: 0, fontSize: '1.6rem', color: '#1b1b1b'}}>
            Outil pour chargé d'étude
          </h1>
        </div>
        <small style={{opacity:0.8}}>v0.1</small>
      </header>

      {/* Intro courte */}
      <p style={{margin:'14px 0 22px'}}>
        Analyse rapide des données cadastrales, d’urbanisme (GPU) et d’environnement
        autour d’un point GPS.
      </p>

      {/* Entrée coordonnées */}
      <div style={{display:'flex', gap:8, alignItems:'center', marginBottom:8}}>
        <input
          placeholder="Ex: 43.32047104103794, 3.2202660369625726"
          value={paste}
          onChange={e=>setPaste(e.target.value)}
          onPaste={e => {
            const text = e.clipboardData?.getData("text");
            if (text) { e.preventDefault(); setPaste(text); applyPasted(text); }
          }}
          style={{flex:1, padding:'10px 12px', borderRadius:8, border:'1px solid #ddd'}}
        />
        <button onClick={()=>applyPasted()} style={{padding:'10px 12px', borderRadius:8, border:'1px solid #ccc', background:'#fff'}}>Appliquer</button>
        <button onClick={swap} title="Inverser lat/lon" style={{padding:'10px 12px', borderRadius:8, border:'1px solid #ccc', background:'#fff'}}>↔︎</button>
      </div>

      <div style={{display:'flex', gap:12, alignItems:'center', marginBottom:16}}>
        <label>Lon{" "}
          <input type="number" step="0.000001" value={lon} onChange={e=>setLon(e.target.value)} style={{width:180, padding:'6px 8px'}}/>
        </label>
        <label>Lat{" "}
          <input type="number" step="0.000001" value={lat} onChange={e=>setLat(e.target.value)} style={{width:180, padding:'6px 8px'}}/>
        </label>
        <button onClick={run} style={{padding:'10px 14px', borderRadius:8, border:'none', background:'#6BCB77', color:'#103311', fontWeight:600}}>
          Lancer
        </button>
      </div>

      {err && <p style={{color:'crimson'}}>Erreurs: {err}</p>}

      {/* ===================== Feuille cadastrale ===================== */}
      <section>
        <h2>Feuille cadastrale</h2>
        {sheet ? (
          <div>
            {sheet.source && <p>Source: {sheet.source}</p>}
            {sheet.download_url
              ? <a href={sheet.download_url} target="_blank" rel="noopener">Télécharger (WFS shapefile ZIP)</a>
              : <p>Aucun lien de téléchargement.</p>}
          </div>
        ) : <p>Aucune requête effectuée.</p>}
      </section>

      {/* ============================ PLU ============================= */}
      <section>
        <h2>PLU</h2>
        {plu ? (
          <div>
            {plu.zone_code && <p>Zone : <b>{plu.zone_code}</b></p>}
            {plu.nature && <p>Nature : {plu.nature}</p>}
            {plu.type && <p>Type : {plu.type}</p>}

            {/* ⚠️ Lien 'Télécharger zonage' retiré comme demandé */}

            {/* Règlement écrit (si disponible) */}
            {Array.isArray(plu.reglement_pdfs) && plu.reglement_pdfs.length > 0 && (
              <div>
                <p>Règlement écrit :</p>
                <ul>{plu.reglement_pdfs.map((u,i)=>(
                  <li key={i}><a href={u} target="_blank" rel="noopener">PDF {i+1}</a></li>
                ))}</ul>
              </div>
            )}

            {/* Pièces ATOM éventuelles */}
            {Array.isArray(plu.atom_links) && plu.atom_links.length > 0 && (
              <ul>{plu.atom_links.map((u,i)=>(
                <li key={i}><a href={u} target="_blank" rel="noopener">Pièce {i+1}</a></li>
              ))}</ul>
            )}
          </div>
        ) : <p>Aucune requête effectuée.</p>}
      </section>

      {/* ================== Statut d’urbanisme (commune) ================== */}
      <section>
        <h2>Statut d’urbanisme (commune)</h2>
        {urbanisme ? (
          <div style={{border:'1px solid #ddd', padding:8, borderRadius:8}}>
            <p><b>{urbanisme.status}</b></p>
            {urbanisme.commune && <p>Commune : {urbanisme.commune}{urbanisme.insee ? ` (${urbanisme.insee})` : ""}</p>}
            {urbanisme.du_type && <p>Type de document : {urbanisme.du_type}</p>}
            {urbanisme.partition && <p>Partition : {urbanisme.partition}</p>}
            {urbanisme.doc_id && <p>Document ID : {urbanisme.doc_id}</p>}
          </div>
        ) : <p>Aucune requête effectuée.</p>}
      </section>

      {/* ============== Atlas des patrimoines — lien seulement ============== */}
      <section>
        <h2>Atlas des patrimoines</h2>
        {plu && plu.download_url ? (
          <p>
            <a href={plu.download_url} target="_blank" rel="noopener">
              Ouvrir la réponse GPU (zone-urba) pour ce point
            </a>
          </p>
        ) : (
          <p>Aucune requête effectuée.</p>
        )}
      </section>

      {/* ============================ Aéroports ============================ */}
      <section>
        <h2>Aéroports (≤ 1000 m)</h2>
        {airport ? (
          <div>
            <p>Statut: <b>{airport.status}</b> — Distance min: {airport.distance_m} m</p>
            {airport.closest_airport_latlon && (
              <p>Aéroport le plus proche: lat/lon {airport.closest_airport_latlon[0]}, {airport.closest_airport_latlon[1]}</p>
            )}
          </div>
        ) : <p>Aucune requête effectuée.</p>}
      </section>
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
