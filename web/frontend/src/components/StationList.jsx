import ScoreBadge from './ScoreBadge'

export default function StationList({ stations, onSelect }) {
  if (!stations?.length) return <p style={{ color: '#6b7280' }}>No stations found.</p>
  return (
    <div>
      {stations.map((s) => (
        <div
          key={s.station_id}
          onClick={() => onSelect?.(s)}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '12px 16px', borderBottom: '1px solid #e5e7eb',
            cursor: 'pointer', background: '#fff',
          }}
        >
          <div>
            <div style={{ fontWeight: 600, fontSize: 14 }}>{s.name}</div>
            <div style={{ fontSize: 12, color: '#6b7280' }}>
              {s.distance_km} km · {s.town || s.county || ''}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontWeight: 700, color: '#15803d' }}>€{s.current_price.toFixed(3)}</div>
            <ScoreBadge score={s.score} label={s.score_label} />
          </div>
        </div>
      ))}
    </div>
  )
}
