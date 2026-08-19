const BASE = '/api'

async function _get(path) {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`)
  return res.json()
}

async function _post(path, body) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`)
  return res.json()
}

async function _delete(path, body) {
  const res = await fetch(BASE + path, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`DELETE ${path} → ${res.status}`)
  return res.json()
}

export function getStations(lat, lng, radius = 20, fuel = 'E10') {
  return _get(`/stations?lat=${lat}&lng=${lng}&radius=${radius}&fuel=${fuel}`)
}

export function getStationHistory(stationId, fuel = 'E10', days = 30) {
  return _get(`/stations/${stationId}/history?fuel=${fuel}&days=${days}`)
}

export function getPricesSummary(lat, lng, radius = 20, fuel = 'E10') {
  return _get(`/prices/summary?lat=${lat}&lng=${lng}&radius=${radius}&fuel=${fuel}`)
}

export function getVapidPublicKey() {
  return _get('/vapid-public-key').then((d) => d.publicKey)
}

export function subscribe(subscriptionObj, prefs) {
  return _post('/push/subscribe', { subscription: subscriptionObj, prefs })
}

export function unsubscribe(endpoint) {
  return _delete('/push/subscribe', { endpoint })
}
