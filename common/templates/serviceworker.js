// {% load static %}

const VERSION = '{{ version }}';

const CACHE_NAME = `NWU.ICU-${VERSION}`;
const appFiles = [
    '/', // 缓存首页使首页能够秒开
]

const log = function () {
    console.log.call(console, '[Service Worker]', ...arguments)
}

self.addEventListener('install', (e) => {
    console.log('[Service Worker] Installing SW version: ', VERSION);
    e.waitUntil((async () => {
        const cache = await caches.open(CACHE_NAME);
        log('Caching', appFiles)
        await cache.addAll(appFiles);
    })());
});

self.addEventListener('activate', event => {
    event.waitUntil((async () => {
        // delete old caches
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    if (cacheName !== CACHE_NAME) {
                        log('deleting', cacheName)
                        return caches.delete(cacheName)
                    }
                })
            )
        })
    })());
});

const cacheRequest = async (request) => {
    const response = await fetch(request);
    const cache = await caches.open(CACHE_NAME);
    await cache.put(request, response.clone());
    return response
}

self.addEventListener('fetch', (e) => {
    console.log('[Service Worker] Receiving fetch request: ', e.request)
    // FIXME: 有无更好的处理 '/' 路径的方法?
    if (e.request.url === 'http://127.0.0.1:8000/' || e.request.url === 'https://nwu.icu/') {}
    else if (e.request.url.startsWith('chrome-extension') || e.request.method !== 'GET' || e.request.destination === 'document') {
        console.log(`[Service Worker] Skipping: ${e.request.url}`);
        return
    }
    e.respondWith((async () => {
        const r = await caches.match(e.request);
        if (r) {
            console.log(`[Service Worker] Cache hit: ${e.request.url}`);
            if (r.url === 'http://127.0.0.1:8000/' || r.url === 'https://nwu.icu/') {
                log('Re-caching "/"')
                cacheRequest(e.request)
            }
            return r;
        }
        console.log(`[Service Worker] Cache miss, fetching: ${e.request.url}`);
        return await cacheRequest(e.request);
    })());
});

self.addEventListener('push', function(event) {
    console.log(event)
    console.log(event.data.text())
    const promiseChain = self.registration.showNotification(event.data.text());

    event.waitUntil(promiseChain);
});
