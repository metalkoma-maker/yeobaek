import assert from 'node:assert/strict';
import { test } from 'node:test';
import { parseTxtExport, TXT_EXPORT_MESSAGE, txtExportName } from '../src/webExport';

test('TXT export message keeps Korean manuscript text and rejects invalid requests', () => {
  const text = '내려받은 시각: 2026-11-14 16:25:00 (한국시간)\n\n가짜 원고\n\n가짜 본문';
  assert.deepEqual(parseTxtExport(JSON.stringify({ type: TXT_EXPORT_MESSAGE, title: '가짜 원고', text })), { type: TXT_EXPORT_MESSAGE, title: '가짜 원고', text });
  assert.equal(parseTxtExport(JSON.stringify({ type: 'other', title: '가짜 원고', text })), null);
  assert.equal(parseTxtExport(JSON.stringify({ type: TXT_EXPORT_MESSAGE, title: '가짜 원고', text: 123 })), null);
  assert.equal(parseTxtExport('{'), null);
});

test('TXT export name cannot escape the app documents folder', () => {
  const name = txtExportName('../가짜:원고', new Date('2026-11-14T07:25:00.123Z'));
  assert.equal(name, '_가짜_원고-20261114072500123.txt');
  assert(!name.includes('/'));
});
