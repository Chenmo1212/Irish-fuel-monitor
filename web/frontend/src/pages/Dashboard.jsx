import { useState, useEffect } from 'react'
import { getStations } from '../api'
import PriceCard from '../components/PriceCard'

const FUEL_OPTIONS = [
  { value: 'E10', label: '⛽ Petrol (E10)' },
  { value: 'B7', label: '🛢 Diesel (B7)' },
  { value: 'E5_98', label: '✨ Petrol Plus (E5/98)' },
  { value: 'B7_PREMIUM', label: '💎 Diesel Plus' },
]

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem('fuelbot_prefs') || '{}') } catch { return {} }
}
function savePrefs(p) { localStorage.setItem('fuelbot_prefs', JSON.stringify(p)) }

export default function Dashboard() {
  const saved = loadPrefs()
  const [lat, setLat] = useState(saved.lat ?? '')
  const [lng, setLng] = useState(saved.lng ?? '')
  const [fuel, setFuel] = useState(saved.fuel ?? 'E10')
  const [radius, setRadius] = useState(saved.radius ?? 20)
  const [best, setBest] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  function geolocate() {
    navigator.geolocation.getCurrentPosition(
      (pos) => { setLat(pos.coords.latitude.toFixed(5)); setLng(pos.coords.longitude.toFixed(5)) },
      () => setError('Geolocation denied'),
    )
  }

  async function handleSearch(e) {
    e.preventDefault()
    if (!lat || !lng) return setError('Enter or detect your location first')
    setLoading(true); setError(null)
    try {
      const stations = await getStations(lat, lng, radius, fuel)
      setBest(stations[0] || null)
      savePrefs({ lat: parseFloat(lat), lng: parseFloat(lng), fuel, radius })
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Dashboard</h2>
      <form onSubmit={handleSearch} style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 24 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <label style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 2 }}>Latitude</div>
            <input value={lat} onChange={(e) => setLat(e.target.value)}
              placeholder="53.2753" style={inputStyle} />
          </label>
          <label style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 2 }}>Longitude</div>
            <input value={lng} onChange={(e) => setLng(e.target.value)}
              placeholder="-6.2031" style={inputStyle} />
          </label>
          <button type="button" onClick={geolocate} style={btnSecondary}>📍 Detect</button>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <label style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 2 }}>Fuel type</div>
            <select value={fuel} onChange={(e) => setFuel(e.target.value)} style={inputStyle}>
              {FUEL_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 2 }}>Radius (km)</div>
            <input type="number" min={5} max={50} value={radius}
              onChange={(e) => setRadius(Number(e.target.value))} style={inputStyle} />
          </label>
        </div>
        <button type="submit" disabled={loading} style={btnPrimary}>
          {loading ? 'Checking…' : 'Find best price'}
        </button>
      </form>
      {error && <p style={{ color: '#dc2626', fontSize: 13 }}>{error}</p>}
      {best && <PriceCard station={best} />}
      {best === null && !loading && !error && (
        <p style={{ color: '#6b7280', fontSize: 13 }}>No stations found nearby.</p>
      )}
    </div>
  )
}

const inputStyle = {
  width: '100%', padding: '6px 10px', border: '1px solid #d1d5db',
  borderRadius: 6, fontSize: 14, background: '#fff',
}
const btnPrimary = {
  padding: '8px 20px', background: '#16a34a', color: '#fff',
  border: 'none', borderRadius: 6, fontWeight: 600, cursor: 'pointer',
}
const btnSecondary = {
  padding: '6px 12px', background: '#f3f4f6', color: '#374151',
  border: '1px solid #d1d5db', borderRadius: 6, cursor: 'pointer', fontSize: 13,
  whiteSpace: 'nowrap',
}
