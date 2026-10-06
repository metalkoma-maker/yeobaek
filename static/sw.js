self.addEventListener('install',()=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
// Private manuscripts and session endpoints are intentionally never cached.
