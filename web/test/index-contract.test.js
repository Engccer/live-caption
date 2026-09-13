import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('app.js가 찾는 id가 모두 있다', () => {
  for (const id of ['status', 'captions', 'finals', 'interim',
                    'toggle', 'fontDown', 'fontUp', 'copy', 'copyDiagnostics', 'notice']) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `#${id}가 없다`);
  }
});

test('live region은 하나뿐이다', () => {
  const liveRegions = html.match(/role=["']status["']|role=["']alert["']|aria-live=/g) ?? [];
  assert.equal(liveRegions.length, 1, '자막 영역에 live region을 걸지 않는다');
});

test('복사 버튼은 숨긴 채로 시작한다', () => {
  assert.match(html, /<button[^>]*id=["']copy["'][^>]*hidden/);
  assert.match(html, /<button[^>]*id=["']copyDiagnostics["'][^>]*hidden/);
});

test('UI 라벨에 이모지를 쓰지 않는다', () => {
  const emoji = html.match(/\p{Extended_Pictographic}/gu) ?? [];
  assert.deepEqual(emoji, []);
});

test('사용자에게 보이는 문구에 em dash를 쓰지 않는다', () => {
  assert.equal(html.includes('—'), false);
});

test('모듈로 app.js를 불러온다', () => {
  assert.match(html, /<script[^>]+type=["']module["'][^>]+src=["']\.?\/?app\.js["']/);
});

test('한국어 문서로 선언한다', () => {
  assert.match(html, /<html[^>]+lang=["']ko["']/);
});
