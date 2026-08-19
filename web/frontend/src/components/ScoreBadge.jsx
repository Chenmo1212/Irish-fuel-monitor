const COLOURS = {
  'Excellent':      { bg: '#dcfce7', text: '#166534' },
  'Very good':      { bg: '#d1fae5', text: '#065f46' },
  'Normal':         { bg: '#fef9c3', text: '#713f12' },
  'Expensive':      { bg: '#fee2e2', text: '#991b1b' },
  'Very expensive': { bg: '#fecaca', text: '#7f1d1d' },
}

export default function ScoreBadge({ score, label }) {
  if (score == null) return <span style={{ color: '#6b7280', fontSize: 12 }}>no history</span>
  const c = COLOURS[label] || { bg: '#f3f4f6', text: '#374151' }
  return (
    <span style={{
      background: c.bg, color: c.text,
      borderRadius: 4, padding: '2px 8px', fontSize: 12, fontWeight: 600,
    }}>
      {score.toFixed(0)}/100 · {label}
    </span>
  )
}
