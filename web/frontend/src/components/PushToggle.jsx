import { useState, useEffect } from 'react'
import { getVapidPublicKey, subscribe, unsubscribe } from '../api'

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = atob(base64)
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)))
}

export default function PushToggle({ prefs }) {
  const [supported, setSupported] = useState(false)
  const [subscribed, setSubscribed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    setSupported('serviceWorker' in navigator && 'PushManager' in window)
    navigator.serviceWorker?.ready.then((reg) =>
      reg.pushManager.getSubscription().then((sub) => setSubscribed(!!sub))
    )
  }, [])

  async function handleToggle() {
    setLoading(true)
    setError(null)
    try {
      const reg = await navigator.serviceWorker.ready
      if (subscribed) {
        const sub = await reg.pushManager.getSubscription()
        if (sub) {
          await unsubscribe(sub.endpoint)
          await sub.unsubscribe()
        }
        setSubscribed(false)
      } else {
        const vapidKey = await getVapidPublicKey()
        const sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(vapidKey),
        })
        const json = sub.toJSON()
        await subscribe(
          { endpoint: json.endpoint, keys: json.keys },
          prefs,
        )
        setSubscribed(true)
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  if (!supported) return <p style={{ fontSize: 13, color: '#6b7280' }}>Push not supported in this browser.</p>

  return (
    <div>
      <button
        onClick={handleToggle}
        disabled={loading}
        style={{
          padding: '8px 20px', borderRadius: 6, border: 'none',
          background: subscribed ? '#fee2e2' : '#dcfce7',
          color: subscribed ? '#991b1b' : '#166534',
          fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer',
        }}
      >
        {loading ? '…' : subscribed ? 'Disable notifications' : 'Enable notifications'}
      </button>
      {error && <p style={{ color: '#dc2626', fontSize: 12, marginTop: 4 }}>{error}</p>}
    </div>
  )
}
