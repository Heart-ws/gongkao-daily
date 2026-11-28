/* Service Worker · 公考日报
 * 策略：
 *   - 页面文档 → 网络优先，断网回落缓存（保证一打开就是最新一期）
 *   - 静态资源 → 缓存优先 + 后台静默更新
 * 注意：file:// 下不会注册（见 index.html 中的协议判断）。
 */
var CACHE = 'gongkao-daily-v1';
var ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './data/manifest.js',
  './data/facts-pool.js',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png',
  './icons/apple-touch-icon.png'
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) {
      // 逐个添加：某个文件 404 不会让整个安装失败
      return Promise.all(ASSETS.map(function (u) {
        return c.add(new Request(u, { cache: 'reload' })).catch(function () { return null; });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) { return k === CACHE ? null : caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;

  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  var isDoc = req.mode === 'navigate' || req.destination === 'document';

  if (isDoc) {
    // 文档：网络优先 → 断网回落缓存
    e.respondWith(
      fetch(req).then(function (res) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put('./index.html', copy); });
        return res;
      }).catch(function () {
        return caches.match('./index.html').then(function (hit) {
          return hit || new Response('离线且无缓存', { status: 503, headers: { 'Content-Type': 'text/plain;charset=utf-8' } });
        });
      })
    );
    return;
  }

  // 数据文件（data/*.js）同样走网络优先：保证当天新一期能取到
  if (/\/data\//.test(url.pathname)) {
    e.respondWith(
      fetch(req).then(function (res) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(req, copy); });
        return res;
      }).catch(function () { return caches.match(req); })
    );
    return;
  }

  // 其他静态资源：缓存优先 + 后台更新
  e.respondWith(
    caches.match(req).then(function (hit) {
      var net = fetch(req).then(function (res) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(req, copy); });
        return res;
      }).catch(function () { return hit; });
      return hit || net;
    })
  );
});
