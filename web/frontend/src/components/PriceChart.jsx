import {
  LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Legend,
} from 'recharts'

export default function PriceChart({ data, lines = [], height = 240 }) {
  // data: array of objects sharing an x-axis key "date" or "observed_at"
  // lines: [{ key, name, color }]
  if (!data?.length) return <p style={{ color: '#6b7280', fontSize: 13 }}>Not enough data yet.</p>

  const COLOURS = ['#16a34a', '#2563eb', '#d97706', '#dc2626']

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis dataKey={lines[0]?.xKey || 'date'} tick={{ fontSize: 11 }} />
        <YAxis
          tickFormatter={(v) => `€${v.toFixed(3)}`}
          tick={{ fontSize: 11 }}
          domain={['auto', 'auto']}
        />
        <Tooltip formatter={(v) => `€${parseFloat(v).toFixed(3)}`} />
        {lines.length > 1 && <Legend />}
        {lines.map((l, i) => (
          <Line
            key={l.key}
            type="monotone"
            dataKey={l.key}
            name={l.name || l.key}
            stroke={l.color || COLOURS[i % COLOURS.length]}
            dot={false}
            strokeWidth={2}
          />
        ))}
        {!lines.length && (
          <Line type="monotone" dataKey="price" stroke="#16a34a" dot={false} strokeWidth={2} />
        )}
      </LineChart>
    </ResponsiveContainer>
  )
}
