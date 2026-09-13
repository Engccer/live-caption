// 앱 화면만 캐시한다.
// 음성 인식 자체는 네트워크가 필요하므로(아이폰은 애플 서버로 보낸다) 진짜 오프라인
// 동작은 애초에 불가능하다. 이 캐시가 주는 것은 회의실 와이파이가 느릴 때 화면이
// 즉시 뜨는 것뿐이다.

const CACHE = 'maldongmu-v1';   // 파일을 고치면 이 숫자를 올린다. 안 올리면 옛 화면에 갇힌다.

const SHELL = [
  './',
  './index.html',
  './app.js',
  './captions.js',
  './recognition.js',
  './manifest.webmanifest',
  './icon-192.png',
  './icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();   // 새 버전을 기다리지 않고 바로 넘긴다
});

self.addEventListener('activate', (event) => {
  // 옛 버전 캐시를 지운다. 안 지우면 기기에 계속 쌓인다.
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  // 네트워크를 먼저 보고 실패하면 캐시로 간다.
  // 반대로 하면 배포한 수정이 사용자에게 늦게 닿는다.
  event.respondWith(
    fetch(event.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(event.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(event.request).then((hit) => hit ?? caches.match('./index.html'))),
  );
});
