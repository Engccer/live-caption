// PWA 계약. 홈 화면에 설치되려면 이 조각들이 서로 맞물려 있어야 하는데,
// 하나만 어긋나도 브라우저는 조용히 설치를 제안하지 않는다.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, statSync } from 'node:fs';

const url = (p) => new URL(`../${p}`, import.meta.url);
const html = readFileSync(url('index.html'), 'utf8');
const manifest = JSON.parse(readFileSync(url('manifest.webmanifest'), 'utf8'));

test('index.html이 manifest를 링크한다', () => {
  assert.match(html, /<link[^>]+rel=["']manifest["'][^>]+href=["']\.?\/?manifest\.webmanifest["']/);
});

test('manifest에 설치에 필요한 필드가 있다', () => {
  assert.equal(manifest.name, '말동무');
  assert.ok(manifest.short_name.length <= 12, 'short_name은 홈 화면에서 잘린다');
  assert.equal(manifest.start_url, './');
  assert.equal(manifest.display, 'standalone');
  assert.ok(manifest.theme_color, 'theme_color가 있어야 주소창 색이 맞는다');
  assert.ok(manifest.background_color, '설치 직후 첫 화면 색이다');
  assert.equal(manifest.lang, 'ko');
});

test('아이콘 둘이 선언돼 있고 실제로 존재한다', () => {
  const sizes = manifest.icons.map((i) => i.sizes);
  assert.ok(sizes.includes('192x192'), '안드로이드 홈 화면');
  assert.ok(sizes.includes('512x512'), '설치 화면과 스플래시');
  for (const icon of manifest.icons) {
    // 선언만 하고 파일이 없으면 설치 제안이 조용히 사라진다.
    assert.ok(statSync(url(icon.src.replace(/^\.\//, ''))).size > 0, `${icon.src}가 비었다`);
    assert.equal(icon.type, 'image/png');
  }
});

test('maskable 아이콘이 있다', () => {
  // 없으면 안드로이드가 아이콘을 흰 원 안에 축소해 넣어 작아 보인다.
  const purposes = manifest.icons.map((i) => i.purpose ?? 'any').join(' ');
  assert.match(purposes, /maskable/);
});

test('iOS 홈 화면용 메타가 있다', () => {
  // iOS는 manifest의 display를 읽지 않는다. 이 메타가 없으면 주소창이 남는다.
  assert.match(html, /<meta[^>]+name=["']apple-mobile-web-app-capable["'][^>]+content=["']yes["']/);
  assert.match(html, /<link[^>]+rel=["']apple-touch-icon["']/);
});

test('서비스워커 파일이 존재한다', () => {
  assert.ok(statSync(url('sw.js')).size > 0);
});

test('서비스워커가 캐시할 파일이 실제로 있다', () => {
  const sw = readFileSync(url('sw.js'), 'utf8');
  const listed = [...sw.matchAll(/'\.\/([^']*)'/g)].map((m) => m[1]).filter((p) => p !== '');
  assert.ok(listed.length >= 4, '앱 셸이 비었다');
  for (const p of listed) {
    assert.ok(statSync(url(p)).size > 0, `캐시 목록의 ${p}가 없다`);
  }
});

test('서비스워커 버전이 캐시 이름에 박혀 있다', () => {
  // 버전을 올리지 않으면 사용자가 옛 화면에 갇힌다.
  const sw = readFileSync(url('sw.js'), 'utf8');
  assert.match(sw, /const CACHE = ['"]maldongmu-v\d+['"]/);
});
