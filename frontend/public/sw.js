/**
 * TG-Assistant 稳健 Service Worker
 * ─────────────────────────────────
 * 解决 NetworkFirst 策略中 cache.put() 在断网/响应体消费后抛出
 * "Failed to execute 'put' on 'Cache'" 的问题。
 *
 * 核心特性：
 * 1. cache.put() 全局错误捕获 + 优雅降级
 * 2. 在线/离线自动检测 + 策略自动切换
 * 3. 防抖的竞态保护，避免网络抖动时重复报错
 * 4. 平滑重试 + 静默失败
 */

// ── 网络状态追踪（防抖 + 竞态保护） ──
let _online = typeof navigator !== 'undefined' ? navigator.onLine : true
let _lastOnlineChange = 0
let _pendingState: boolean | null = null
let _stateTransitionTimer: ReturnType<typeof setTimeout> | null = null
const ONLINE_DEBOUNCE_MS = 500

function _setOnline(state: boolean) {
  const now = Date.now()
  // 短时间内相同状态不重复处理
  if (state === _online && now - _lastOnlineChange < ONLINE_DEBOUNCE_MS) return

  _pendingState = state
  if (_stateTransitionTimer) clearTimeout(_stateTransitionTimer)

  _stateTransitionTimer = setTimeout(() => {
    if (_pendingState === _online) return
    const prev = _online
    _online = _pendingState!
    _lastOnlineChange = Date.now()
    _pendingState = null

    console.log(
      `[SW] 网络状态变更: ${prev ? '在线' : '离线'} -> ${_online ? '在线' : '离线'}`
    )
  }, ONLINE_DEBOUNCE_MS)
}

if (typeof self !== 'undefined' && 'addEventListener' in self) {
  self.addEventListener('online', () => _setOnline(true))
  self.addEventListener('offline', () => _setOnline(false))
}

// ── 带保护的 cache.put () ──
async function _safeCachePut(
  cache: Cache,
  request: Request,
  response: Response
): Promise<boolean> {
  // 只缓存 GET 请求的 2xx 响应
  if (
    !_online ||
    request.method !== 'GET' ||
    response.status < 200 ||
    response.status >= 300
  ) {
    return false
  }

  try {
    // 克隆响应，避免消费后 cache.put 失败
    const clone = response.clone()
    await cache.put(request, clone)
    return true
  } catch (err: any) {
    // 静默处理常见的缓存写入错误
    if (
      err.name === 'NetworkError' ||
      err.name === 'QuotaExceededError' ||
      err.message?.includes('put') ||
      err.message?.includes('Cache')
    ) {
      // 磁盘满时清理旧缓存
      if (err.name === 'QuotaExceededError') {
        try {
          const keys = await cache.keys()
          const staleKeys = keys.filter(
            (k) =>
              k.url.includes('/api/') &&
              !k.url.includes('/api/auth/')
          )
          for (const key of staleKeys.slice(0, Math.floor(staleKeys.length * 0.7))) {
            await cache.delete(key)
          }
        } catch { /* ignore */ }
      }
      return false
    }
    throw err // 其他错误向上抛
  }
}

// ── 稳健的 NetworkFirst 策略 ──
async function _robustNetworkFirst(
  request: Request,
  cacheName: string,
  networkTimeoutSeconds: number = 3
): Promise<Response> {
  const cache = await caches.open(cacheName)

  // 并行：网络请求 + 缓存查找
  let networkResolved = false
  let networkResponse: Response | null = null

  const networkPromise = (async (): Promise<Response | null> => {
    if (!_online) return null
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), networkTimeoutSeconds * 1000)

      const fetched = await fetch(request.clone(), {
        signal: controller.signal,
      })
      clearTimeout(timeoutId)

      if (fetched.ok) {
        networkResponse = fetched
        networkResolved = true

        // 后台缓存（不影响响应速度）
        _safeCachePut(cache, request, fetched.clone()).catch(() => {})

        return fetched
      }
      return null
    } catch {
      return null
    }
  })()

  const cachePromise = (async (): Promise<Response | undefined> => {
    try {
      return await cache.match(request)
    } catch {
      return undefined
    }
  })()

  // 等待网络或缓存任一返回
  const result = await Promise.race([
    networkPromise,
    (async () => {
      // 缓存始终在并行查找，给网络一点时间
      const cached = await cachePromise
      if (cached && !networkResolved) {
        // 再等 200ms，看网络有没有更快回来
        await new Promise((r) => setTimeout(r, 200))
        if (networkResolved && networkResponse) {
          return networkResponse
        }
        return cached
      }
      // 继续等网络
      return await networkPromise.then((r) => r || cached)
    })(),
  ])

  if (result) return result

  // 彻底失败时返回离线页
  return new Response(
    JSON.stringify({ error: 'Network unavailable' }),
    {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    }
  )
}

// ── 稳健的 CacheFirst 策略 ──
async function _robustCacheFirst(
  request: Request,
  cacheName: string,
  networkTimeoutSeconds: number = 3
): Promise<Response> {
  const cache = await caches.open(cacheName)

  // 先查缓存
  try {
    const cached = await cache.match(request)
    if (cached) return cached
  } catch { /* ignore */ }

  // 在线时尝试网络，并缓存结果
  if (_online) {
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), networkTimeoutSeconds * 1000)
      const fetched = await fetch(request.clone(), { signal: controller.signal })
      clearTimeout(timeoutId)

      if (fetched.ok) {
        _safeCachePut(cache, request, fetched.clone()).catch(() => {})
        return fetched
      }
    } catch { /* ignore */ }
  }

  return new Response(
    JSON.stringify({ error: 'Network unavailable' }),
    { status: 503, headers: { 'Content-Type': 'application/json' } }
  )
}

// ── 策略路由器：根据请求类型和网络状态自动切换 ──
function _getStrategy(url: URL): 'NetworkFirst' | 'CacheFirst' | 'StaleWhileRevalidate' {
  // SSE 流不缓存
  if (url.pathname.includes('/monitors/stream') || url.pathname.includes('/events')) {
    return 'NetworkFirst'
  }
  // API 请求：在线时 NetworkFirst，离线时已由 _robustNetworkFirst 内部降级
  if (url.pathname.includes('/api/')) {
    return 'NetworkFirst'
  }
  // 静态资源
  return 'CacheFirst'
}

// ── install / activate 事件 ──
const STATIC_CACHE = 'tg-assistant-static-v1'
const PRECACHE_URLS = self.__WB_MANIFEST || []

self.addEventListener('install', (event: ExtendableEvent) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(STATIC_CACHE)
      try {
        await Promise.allSettled(
          PRECACHE_URLS.map((entry: any) => {
            const url = typeof entry === 'string' ? entry : entry.url
            return _safeCachePut(cache, new Request(url), new Response('', { status: 200 }))
          })
        )
      } catch { /* pre-cache failure is non-fatal */ }
      ;(self as any).skipWaiting()
    })()
  )
})

self.addEventListener('activate', (event: ExtendableEvent) => {
  event.waitUntil(
    (async () => {
      const keep = [STATIC_CACHE, 'api-cache']
      const allKeys = await caches.keys()
      await Promise.allSettled(
        allKeys.filter((k) => !keep.includes(k)).map((k) => caches.delete(k))
      )
      ;(self as any).clients.claim()
    })()
  )
})

// ── fetch 事件：核心拦截 ──
self.addEventListener('fetch', (event: FetchEvent) => {
  const request = event.request
  const url = new URL(request.url)

  // 只处理 GET 请求
  if (request.method !== 'GET') return

  // 跳过非 HTTP/HTTPS
  if (!url.protocol.startsWith('http')) return

  const strategy = _getStrategy(url)

  if (strategy === 'NetworkFirst') {
    event.respondWith(
      _robustNetworkFirst(request, 'api-cache', _online ? 4 : 2)
    )
  } else {
    event.respondWith(
      _robustCacheFirst(request, STATIC_CACHE, 5)
    )
  }
})

// ── 定期清理过期缓存 ──
self.addEventListener('message', (event: ExtendableMessageEvent) => {
  if (event.data?.type === 'SKIP_WAITING') {
    ;(self as any).skipWaiting()
  }
  if (event.data?.type === 'CLEAR_API_CACHE') {
    event.waitUntil(
      caches.delete('api-cache').catch(() => {})
    )
  }
})

// 每 10 分钟清理一次过期的 api 缓存
const CLEANUP_INTERVAL = 10 * 60 * 1000
let _lastCleanup = Date.now()
setInterval(() => {
  const now = Date.now()
  if (now - _lastCleanup < CLEANUP_INTERVAL) return
  _lastCleanup = now

  caches.open('api-cache').then(async (cache) => {
    try {
      const keys = await cache.keys()
      const oldKeys = keys.filter(
        (k) =>
          !k.url.includes('/api/auth/') &&
          !k.url.includes('/monitors/stream')
      )
      for (const key of oldKeys.slice(0, 100)) {
        await cache.delete(key)
      }
    } catch { /* ignore */ }
  }).catch(() => {})
}, 60000)
