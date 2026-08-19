import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Stations from './pages/Stations'
import History from './pages/History'
import Settings from './pages/Settings'

const NAV = [
  { to: '/', label: '⛽ Dashboard' },
  { to: '/stations', label: '📍 Stations' },
  { to: '/history', label: '📈 History' },
  { to: '/settings', label: '⚙️ Settings' },
]

export default function App() {
  return (
    <div style={{ maxWidth: 640, margin: '0 auto', padding: '0 16px' }}>
      <nav style={{
        display: 'flex', gap: 4, padding: '12px 0', borderBottom: '1px solid #e5e7eb',
        marginBottom: 24,
      }}>
        {NAV.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            style={({ isActive }) => ({
              padding: '6px 12px', borderRadius: 6, fontSize: 13, fontWeight: 600,
              background: isActive ? '#dcfce7' : 'transparent',
              color: isActive ? '#15803d' : '#374151',
            })}
          >
            {label}
          </NavLink>
        ))}
      </nav>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/stations" element={<Stations />} />
        <Route path="/history" element={<History />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </div>
  )
}
