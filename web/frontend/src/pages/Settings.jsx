import { useState } from 'react'
import PushToggle from '../components/PushToggle'

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem('fuelbot_prefs') || '{}') } catch { return {} }
}
function savePrefs(p) { localStorage.setItem('fuelbot_prefs', JSON.stringify(p)) }

export default function Settings() {
  const saved = loadPrefs()
  const [petrolTarget, setPetrolTarget] = useState(saved.petrolTarget ?? '')
  const [dieselTarget, setDieselTarget] = useState(saved.dieselTarget ?? '')
  const [radius, setRadius] = useState(saved.radius ?? 20)
  const [saved_, setSaved] = useState(false)

  function handleSave(e) {
    e.preventDefault()
    savePrefs({
      ...loadPrefs(),
      petrolTarget: petrolTarget ? parseFloat(petrolTarget) : null,
      dieselTarget: dieselTarget ? parseFloat(dieselTarget) : null,
      radius: Number(radius),
    })
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const prefs = {
    ...loadPrefs(),
    petrol_target: petrolTarget ? parseFloat(petrolTarget) : null,
    diesel_target: dieselTarget ? parseFloat(dieselTarget) : null,
    radius_km: Number(radius),
    fuel_type: saved.fuel ?? 'E10',
    latitude: saved.lat ?? 0,
    longitude: saved.lng ?? 0,
  }

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Settings</h2>
      <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 360 }}>
        <label>
          <div style={labelStyle}>Petrol target price (€/L)</div>
          <input type="number" step="0.001" min="0" max="5"
            value={petrolTarget} onChange={(e) => setPetrolTarget(e.target.value)}
            placeholder="e.g. 1.750" style={inputStyle} />
          <div style={hintStyle}>Alert when petrol ≤ this price</div>
        </label>
        <label>
          <div style={labelStyle}>Diesel target price (€/L)</div>
          <input type="number" step="0.001" min="0" max="5"
            value={dieselTarget} onChange={(e) => setDieselTarget(e.target.value)}
            placeholder="e.g. 1.650" style={inputStyle} />
          <div style={hintStyle}>Alert when diesel ≤ this price</div>
        </label>
        <label>
          <div style={labelStyle}>Search radius (km)</div>
          <input type="range" min={5} max={50} step={5}
            value={radius} onChange={(e) => setRadius(Number(e.target.value))}
            style={{ width: '100%' }} />
          <div style={hintStyle}>{radius} km</div>
        </label>
        <button type="submit" style={btnPrimary}>
          {saved_ ? '✓ Saved' : 'Save preferences'}
        </button>
      </form>
      <hr style={{ margin: '24px 0', borderColor: '#e5e7eb' }} />
      <h3 style={{ marginTop: 0, fontSize: 15 }}>Push notifications</h3>
      <p style={{ fontSize: 13, color: '#6b7280', marginTop: 0 }}>
        Get browser notifications when prices drop to your targets.
        Requires targets to be set above and your location saved on the Dashboard.
      </p>
      <PushToggle prefs={prefs} />
    </div>
  )
}

const inputStyle = {
  width: '100%', padding: '6px 10px', border: '1px solid #d1d5db',
  borderRadius: 6, fontSize: 14, background: '#fff', marginTop: 2,
}
const labelStyle = { fontSize: 13, fontWeight: 600, color: '#374151' }
const hintStyle = { fontSize: 12, color: '#6b7280', marginTop: 2 }
const btnPrimary = {
  padding: '8px 20px', background: '#16a34a', color: '#fff',
  border: 'none', borderRadius: 6, fontWeight: 600, cursor: 'pointer',
}
