self.addEventListener('push', (event) => {
  let data = { title: 'FuelBot', body: 'New fuel price alert', url: '/' }
  try {
    data = JSON.parse(event.data.text())
  } catch (_) {}
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/favicon.svg',
      data: { url: data.url },
    })
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = event.notification.data?.url || '/'
  event.waitUntil(clients.openWindow(url))
})
