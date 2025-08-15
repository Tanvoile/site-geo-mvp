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
      // Si pas dispo chez toi pour l'instant, on met un petit message
      setHeritageSummary({ not_available: true, error: String(e.message || e) });
    }

    try { setAirport(await fetchJSON('/airport/check', { lon: lonNum, lat: latNum, buffer_m: 1000 })); }
    catch (e) { setErr(prev => (prev ? prev + " | " : "") + "Aéroport: " + e.message); }
  };

  return (
    <div style={{maxWidth: 860, margin: '0 auto', padding:'0 12px'}}>
      <h1>Site GEO — MVP</h1>
      <p>Entrez un point GPS (WGS84) ou collez-le directement.</p>

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
            {/* Affiche les méta si ton backend les renvoie */}
            {plu.zone_code && <p>Zone : <b>{plu.zone_code}</b></p>}
            {plu.nature && <p>Nature : {plu.nature}</p>}
            {plu.type && <p>Type : {plu.type}</p>}

            {/* Ancien lien WFS si présent */}
            {plu.download_url && (
              <p><a href={plu.download_url} target="_blank" rel="noopener">
                Télécharger zonage (WFS shapefile ZIP)
              </a></p>
            )}

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
          <div style={{border:'1px solid #ddd', padding:8}}>
            <p><b>{urbanisme.status}</b></p>
            {urbanisme.commune && <p>Commune : {urbanisme.commune}{urbanisme.insee ? ` (${urbanisme.insee})` : ""}</p>}
            {urbanisme.du_type && <p>Type de document : {urbanisme.du_type}</p>}
            {urbanisme.partition && <p>Partition : {urbanisme.partition}</p>}
            {urbanisme.doc_id && <p>Document ID : {urbanisme.doc_id}</p>}
          </div>
        ) : <p>Aucune requête effectuée.</p>}
      </section>

      {/* ============== Atlas des patrimoines — récap ============== */}
      <section>
        <h2>Atlas des patrimoines (récap protections)</h2>
        {!heritageSummary ? (
          <p>Aucune requête effectuée.</p>
        ) : heritageSummary.not_available ? (
          <div style={{color:'#a15c00', background:'#fff8e6', border:'1px solid #ffd479', padding:8}}>
            Récap non disponible (backend /heritage/summary/by-point absent).<br/>
            <small>{heritageSummary.error}</small>
          </div>
        ) : (
          <div>
            <p>
              Protection(s) trouvée(s) :{" "}
              <b>{heritageSummary.any_protection ? "✓ OUI" : "✗ NON"}</b>
              {heritageSummary.any_protection && <> — {heritageSummary.total_hits} élément(s)</>}
            </p>
            <ul style={{listStyle:'none', paddingLeft:0}}>
              {Object.entries(heritageSummary.layers || {}).map(([key, layer]) => (
                <li key={key} style={{marginBottom:10}}>
                  <Pill ok={layer.count>0} />
                  <b>{layer.pretty || key}</b>
                  {layer.count>0 && (
                    <details style={{marginTop:6}}>
                      <summary>Voir les {layer.count} élément(s)</summary>
                      <ul>
                        {(layer.hits || []).map((h,i)=>(
                          <li key={i}>{h.label || "(sans libellé)"}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {layer.error && <div style={{color:'crimson'}}>Erreur: {layer.error}</div>}
                </li>
              ))}
            </ul>
          </div>
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
