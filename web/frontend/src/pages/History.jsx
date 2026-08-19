import { useState } from 'react'
import { getPricesSummary } from '../api'
import PriceChart from '../components/PriceChart'

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem('fuelbot_prefs') || '{}') } catch { return {} }
}

export default function History() {
  const prefs = loadPrefs()
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function load() {
    if (!prefs.lat || !prefs.lng) return setError('Set your location on the Dashboard first')
    setLoading(true); setError(null)
    try {
      const data = await getPricesSummary(prefs.lat, prefs.lng, prefs.radius ?? 20, prefs.fuel ?? 'E10')
      setSummary(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const chartData = summary?.daily_avg?.map((d) => ({
    date: d.date,
    'Area median': d.median_price,
  })) ?? []

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Price History</h2>
      <button onClick={load} disabled={loading} style={btnPrimary}>
        {loading ? 'Loading…' : 'Load history'}
      </button>
      {error && <p style={{ color: '#dc2626', fontSize: 13 }}>{error}</p>}
      {summary && (
        <>
          {summary.cheapest_today && (
            <div style={{
              marginTop: 16, padding: 12, background: '#dcfce7',
              borderRadius: 8, fontSize: 14,
            }}>
              <strong>Cheapest today:</strong> {summary.cheapest_today.name} —{' '}
              €{summary.cheapest_today.current_price.toFixed(3)}/L
              ({summary.cheapest_today.distance_km} km)
            </div>
          )}
          <div style={{ marginTop: 20 }}>
            <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 14 }}>
              30-day regional median price
            </div>
            <PriceChart
              data={chartData}
              lines={[{ key: 'Area median', name: 'Area median', xKey: 'date' }]}
              height={260}
            />
          </div>
        </>
      )}
    </div>
  )
}

const btnPrimary = {
  padding: '8px 20px', background: '#16a34a', color: '#fff',
  border: 'none', borderRadius: 6, fontWeight: 600, cursor: 'pointer',
}
