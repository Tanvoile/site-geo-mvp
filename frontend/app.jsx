
import { useState } from "https://esm.sh/react@18";

const API = (path, qs) => {
  const base = window.API_BASE || "http://localhost:8000";
  return `${base}${path}?${new URLSearchParams(qs).toString()}`;
};

function App() {
  const [lon, setLon] = useState(2.3522);
  const [lat, setLat] = useState(48.8566);
  const [sheet, setSheet] = useState(null);
  const [plu, setPlu] = useState(null);
  const [heritage, setHeritage] = useState(null);
  const [airport, setAirport] = useState(null);
  const [err, setErr] = useState("");

  const run = async () => {
    setErr("");
    setSheet(null); setPlu(null); setHeritage(null); setAirport(null);
    try {
      const s = await fetch(API('/sheet/by-point', {lon, lat})).then(r => r.json());
      setSheet(s);
    } catch(e) { setErr("Feuille: " + e.message); }

    try {
      const p = await fetch(API('/plu/by-point', {lon, lat})).then(r => r.json());
      setPlu(p);
    } catch(e) { setErr(prev => (prev ? prev + " | " : "") + "PLU: " + e.message); }

    try {
      const h = await fetch(API('/heritage/by-point', {lon, lat})).then(r => r.json());
      setHeritage(h);
    } catch(e) { setErr(prev => (prev ? prev + " | " : "") + "Atlas: " + e.message); }

    try {
      const a = await fetch(API('/airport/check', {lon, lat, buffer_m:1000})).then(r => r.json());
      setAirport(a);
    } catch(e) { setErr(prev => (prev ? prev + " | " : "") + "Aéroport: " + e.message); }
  };

  return (
    <div style={{maxWidth: 800, margin: '40px auto', fontFamily: 'system-ui'}}>
      <h1>Site GEO — MVP sans base</h1>
      <p>Entrez un point GPS (WGS84). Le backend renverra les liens/tickets pour chaque source.</p>
      <div style={{display:'flex', gap:12}}>
        <label>Lon <input value={lon} onChange={e=>setLon(e.target.value)} style={{width:140}}/></label>
        <label>Lat <input value={lat} onChange={e=>setLat(e.target.value)} style={{width:140}}/></label>
        <button onClick={run}>Lancer</button>
      </div>

      {err && <p style={{color:'crimson'}}>Erreurs: {err}</p>}

      <section>
        <h2>Feuille cadastrale</h2>
        {sheet ? (
          <div>
            <p>Source: {sheet.source}</p>
            <a href={sheet.download_url} target="_blank">Télécharger (WFS shapefile ZIP)</a>
          </div>
        ) : <p>Aucune requête effectuée.</p>}
      </section>

      <section>
        <h2>PLU</h2>
        {plu ? (
          <div>
            <a href={plu.download_url} target="_blank">Télécharger zonage (WFS shapefile ZIP)</a>
            {plu.atom_links?.length ? (
              <ul>{plu.atom_links.map((u,i)=>(<li key={i}><a href={u} target="_blank">Pièce {i+1}</a></li>))}</ul>
            ) : <p>(ATOM à brancher par commune)</p>}
          </div>
        ) : <p>Aucune requête effectuée.</p>}
      </section>

      <section>
        <h2>Atlas des patrimoines</h2>
        {heritage ? (
          <div>
            <a href={heritage.download_url} target="_blank">Télécharger (WFS shapefile ZIP)</a>
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

import { createRoot } from "https://esm.sh/react-dom@18/client";
createRoot(document.getElementById('root')).render(<App/>);
