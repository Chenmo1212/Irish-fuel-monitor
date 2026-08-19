import { useState } from 'react'
import { getStations, getStationHistory } from '../api'
import StationList from '../components/StationList'
import PriceChart from '../components/PriceChart'
import ScoreBadge from '../components/ScoreBadge'

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem('fuelbot_prefs') || '{}') } catch { return {} }
}

export default function Stations() {
  const prefs = loadPrefs()
  const [stations, setStations] = useState([])
  const [selected, setSelected] = useState(null)
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function load() {
    if (!prefs.lat || !prefs.lng) return setError('Set your location on the Dashboard first')
    setLoading(true); setError(null)
    try {
      const data = await getStations(prefs.lat, prefs.lng, prefs.radius ?? 20, prefs.fuel ?? 'E10')
      setStations(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleSelect(station) {
    setSelected(station)
    const hist = await getStationHistory(station.station_id, prefs.fuel ?? 'E10', 30)
    const chartData = hist.map((r) => ({
      date: r.observed_at.slice(0, 10),
      price: r.price,
    }))
    setHistory(chartData)
  }

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Nearby Stations</h2>
      <button onClick={load} disabled={loading} style={btnPrimary}>
        {loading ? 'Loading…' : 'Load stations'}
      </button>
      {error && <p style={{ color: '#dc2626', fontSize: 13 }}>{error}</p>}
      <div style={{ marginTop: 16 }}>
        <StationList stations={stations} onSelect={handleSelect} />
      </div>
      {selected && (
        <div style={{ marginTop: 24, padding: 16, border: '1px solid #e5e7eb', borderRadius: 8, background: '#fff' }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>{selected.name}</div>
          <div style={{ marginBottom: 8 }}>
            <ScoreBadge score={selected.score} label={selected.score_label} />
          </div>
          <PriceChart
            data={history}
            lines={[{ key: 'price', name: 'Price (€/L)', xKey: 'date' }]}
          />
        </div>
      )}
    </div>
  )
}

const btnPrimary = {
  padding: '8px 20px', background: '#16a34a', color: '#fff',
  border: 'none', borderRadius: 6, fontWeight: 600, cursor: 'pointer',
}
