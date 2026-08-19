import ScoreBadge from './ScoreBadge'

export default function PriceCard({ station }) {
  if (!station) return null
  return (
    <div style={{
      border: '1px solid #e5e7eb', borderRadius: 8, padding: 20,
      background: '#f9fafb', maxWidth: 420,
    }}>
      <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 4 }}>
        {station.town || station.county || ''} · {station.distance_km} km
      </div>
      <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 6 }}>{station.name}</div>
      <div style={{ fontSize: 32, fontWeight: 800, color: '#15803d', marginBottom: 8 }}>
        €{station.current_price.toFixed(3)}<span style={{ fontSize: 16, fontWeight: 400 }}>/L</span>
      </div>
      <ScoreBadge score={station.score} label={station.score_label} />
      {station.avg_7d != null && (
        <div style={{ marginTop: 12, fontSize: 13, color: '#374151' }}>
          <span>7d avg: <strong>€{station.avg_7d.toFixed(3)}</strong></span>
          {station.avg_30d != null && (
            <span style={{ marginLeft: 12 }}>30d avg: <strong>€{station.avg_30d.toFixed(3)}</strong></span>
          )}
        </div>
      )}
      {station.score_reasons?.length > 0 && (
        <ul style={{ marginTop: 8, paddingLeft: 16, fontSize: 12, color: '#6b7280' }}>
          {station.score_reasons.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
    </div>
  )
}
