const { useState } = React;

const API = (path, qs) => {
  const base = window.API_BASE || "http://localhost:8000";
  return `${base}${path}?${new URLSearchParams(qs).toString()}`;
};

// Parse "lat, lon" (ou "lat lon", "lat;lon", etc.), tolère points/virgules décimales
function parseLatLon(str) {
  if (!str) return null;
  const nums = (str.match(/-?\d+(?:[.,]\d+)?/g) || []).slice(0, 2).map(v =>
    Number(v.replace(",", "."))
  );
  if (nums.length !== 2 || !nums.every(n => Number.isFinite(n))) return null;
  // Convention: on suppose "lat, lon" (comme dans ton exemple)
  const [lat, lon] = nums;
  return { lat, lon };
}

function App() {
  const [lon, setLon] = useState(2.3522);
  const [lat, setLat] = useState(48.8566);
  const [paste, setPaste] = useState(""); // zone de collage
  const [sheet, setSheet] = useState(null);
  const [plu, setPlu] = useState(null);
  const [heritage, setHeritage] = useState(null);
  const [airport, setAirport] = useState(null);
  const [err, setErr] = useState("");

  const applyPasted = (text) => {
    const parsed = parseLatLon(text ?? paste);
    if (!parsed) {
      setErr("Coordonnées collées invalides. Format attendu: lat, lon");
      return;
    }
    setLat(parsed.lat);
    setLon(parsed.lon);
    setErr("");
  };

  const swap = () => { // au cas où tu colles "lon, lat"
    const a = lon; setLon(lat); setLat(a);
  };

  const run = async () => {
    setErr("");
    setSheet(null); setPlu(null); setHeritage(null); setAirport(null);

    const lonNum = Number(String(lon).replace(",", "."));
    const latNum = Number(String(lat).replace(",", "."));
    if (!Number.isFinite(lonNum) || !Number.isFinite(latNum)) {
      setErr("Coordonnées invalides (ex: 48.8566 / 2.3522).");
      return;
    }

    const fetchJSON = async (path, qs) => {
      const res = await fetch(API(path, qs));
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      return res.json();
    };

    try { setSheet(await fetchJSON('/sheet/by-point', { lon: lonNum, lat: latNum })); }
    catch (e) { setErr(prev => (prev ? prev + " | " : "") + "Feuille: " + e.message); }

    try { setPlu(await fetchJSON('/plu/by-point', { lon: lonNum, lat: latNum })); }
    catch (e) { setErr(prev => (prev ? prev + " | " : "") + "PLU: " + e.message); }

    try { setHeritage(await fetchJSON('/heritage/by-point', { lon: lonNum, lat: latNum })); }
    catch (e) { setErr(prev => (prev ? prev + " | " : "") + "Atlas: " + e.message); }

    try { setAirport(await fetchJSON('/airport/check', { lon: lonNum, lat: latNum, buffer_m: 1000 })); }
    catch (e) { setErr(prev => (prev ? prev + " | " : "") + "Aéroport: " + e.message); }
  };

  return (
    <div style={{maxWidth: 800, margin: '40px auto', fontFamily: 'system-ui'}}>
      <h1>Site GEO — MVP sans base</h1>
      <p>Entrez un point GPS (WGS84) ou collez-le directement.</p>

      {/* Champ pour coller "lat, lon" */}
      <div style={{display:'flex', gap:8, alignItems:'center', marginBottom:8}}>
        <input
          placeholder="Ex: 43.32047104103794, 3.2202660369625726"
          value={paste}
          onChange={e=>setPaste(e.target.value)}
          onPaste={e => { // appliquer automatiquement au collage
            const text = e.clipboardData?.getData("text");
            if (text) { e.preventDefault(); setPaste(text); applyPasted(text); }
          }}
          style={{flex:1, padding:'6px 8px'}}
        />
        <button onClick={()=>applyPasted()}>Appliquer</button>
        <button onClick={swap} title="Inverser lat/lon">↔︎</button>
      </div>

      {/* Édition fine si besoin */}
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

      <section>
        <h2>Feuille cadastrale</h2>
        {sheet ? (
          <div>
            {sheet.source && <p>Source: {sheet.source}</p>}
            {sheet.download_url ? (
              <a href={sheet.download_url} target="_blank" rel="noopener">Télécharger (WFS shapefile ZIP)</a>
            ) : <p>Aucun lien de téléchargement.</p>}
          </div>
        ) : <p>Aucune requête effectuée.</p>}
      </section>

      <section>
        <h2>PLU</h2>
        {plu ? (
          <div>
            {plu.download_url && <a href={plu.download_url} target="_blank" rel="noopener">Télécharger zonage (WFS shapefile ZIP)</a>}
            {plu.atom_links?.length ? (
              <ul>{plu.atom_links.map((u,i)=>(<li key={i}><a href={u} target="_blank" rel="noopener">Pièce {i+1}</a></li>))}</ul>
            ) : <p>(ATOM à brancher par commune)</p>}
          </div>
        ) : <p>Aucune requête effectuée.</p>}
      </section>

      <section>
        <h2>Atlas des patrimoines</h2>
        {heritage ? (
          <div>
            {heritage.download_url ? (
              <a href={heritage.download_url} target="_blank" rel="noopener">Télécharger (WFS shapefile ZIP)</a>
            ) : <p>Aucun lien de téléchargement.</p>}
          </div>
        ) : <p>Aucune requête effectuée.</p>}
      </section>

      <section>
        <h2>Aéroports (≤ 1000 m)</h2>
        {airport ? (
          <div>
            <p>Statut: <b>{airport.status}</b> — Distance min: {airport.distance_m} m</p>
            {airport.closest_airport_lonlat && (
              <p>Aéroport le plus proche: lon/lat {airport.closest_airport_lonlat[0]}, {airport.closest_airport_lonlat[1]}</p>
            )}
          </div>
        ) : <p>Aucune requête effectuée.</p>}
      </section>
    </div>
  );
}

const { createRoot } = ReactDOM;
createRoot(document.getElementById('root')).render(<App/>);
