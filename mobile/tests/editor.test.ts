import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Editor, Draft, count, koreaDay } from '../src/editor';
import { Api, ApiError, Manuscript, serverAddress } from '../src/api';
import { createDraftStore } from '../src/draftStorage';
const doc = (): Manuscript => ({ id: 'fake', title: '가짜 원고', body: '가', version: 1, total: 1, today: 1, day: koreaDay(), updated: 1 });
function storage() {
  let local: Draft | null = null;
  return { put: async (draft: Draft) => { local = { ...draft }; }, clear: async (draft: Draft) => { if (local?.body === draft.body && local?.title === draft.title) local = null; }, read: () => local };
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
test('Python-compatible whitespace and Unicode counts; Korea day rollover', () => {
  assert.equal(count('가 나\n다😀\u0085\u001c'), 4);
  assert.equal(count('\ufeff'), 1);
  const e = new Editor({ ...doc(), day: '2000-01-01', today: 80 }, storage(), async d => d, () => {});
  e.edit('가짜', '가나다'); assert.deepEqual(e.stats(), { total: 3, today: 2 });
});
test('failed save retains input and durable draft; retry keeps original version', async () => {
  const store = storage(); let attempts = 0;
  const e = new Editor(doc(), store, async d => { assert.equal(d.version, 1); if (++attempts === 1) throw Error('offline'); return { ...d, version: 2 }; }, () => {});
  e.edit('테스트', '가나다'); assert.equal(await e.save(), false);
  assert.equal(e.body, '가나다'); assert.equal(store.read()?.body, '가나다'); assert.equal(e.base.version, 1);
  assert.equal(await e.save(true), true); assert.equal(store.read(), null);
});
test('typing while PUT is pending never loses newer input or clears newer draft', async () => {
  const pending = deferred<Manuscript>(), started = deferred<void>(), store = storage();
  const e = new Editor(doc(), store, async () => { started.resolve(); return pending.promise; }, () => {});
  e.edit('제목', '첫 입력'); const saving = e.save(); await started.promise;
  e.edit('제목', '추가 입력'); assert.equal(await e.save(), false);
  pending.resolve({ ...doc(), title: '제목', body: '첫 입력', total: 3, version: 2 }); await saving;
  assert.equal(e.body, '추가 입력'); assert.equal(e.dirty, true); assert.equal(e.base.version, 2); assert.equal(store.read()?.body, '추가 입력');
});
test('409 stops all writes; recovering B requires explicit save against newly fetched A', async () => {
  const store = storage(); let calls = 0;
  const current = { ...doc(), body: '다른 기기 글', version: 2 };
  const e = new Editor(doc(), store, async () => { calls++; throw new ApiError('충돌', 409, current); }, () => {});
  e.edit('제목', '내 기기 글'); await e.save();
  assert.equal(e.conflict, current); assert.equal(await e.save(true), false); assert.equal(calls, 1); assert.equal(e.body, '내 기기 글');
  const b = store.read()!;
  const restored = new Editor(current, store, async d => { calls++; assert.equal(d.version, 2); return { ...d, version: 3 }; }, () => {});
  restored.loadRecovery(b); assert.equal(await restored.save(), false); assert.equal(calls, 1);
  assert.equal(await restored.save(true), true); assert.equal(calls, 2);
});
test('lost success response followed by stale retry detects conflict, never blind overwrites', async () => {
  let server = doc(), calls = 0;
  const e = new Editor(server, storage(), async d => {
    if (++calls === 1) { server = { ...d, version: 2 }; throw Error('lost response'); }
    if (d.version !== server.version) throw new ApiError('충돌', 409, server);
    throw Error('must not write');
  }, () => {});
  e.edit('제목', '새 글'); await e.save(); e.edit('제목', '더 새 글'); await e.save(true);
  assert.equal(server.body, '새 글'); assert.equal(e.body, '더 새 글'); assert.equal(e.conflict?.version, 2);
});
test('late GET cannot replace typing started after refresh', async () => {
  const pending = deferred<Manuscript>(); const e = new Editor(doc(), storage(), async d => d, () => {});
  const refresh = e.refresh(() => pending.promise); e.edit('제목', '입력 중');
  pending.resolve({ ...doc(), body: '서버 글', version: 2 }); await refresh;
  assert.equal(e.body, '입력 중'); assert.equal(e.base.version, 1);
});
test('local storage failure prevents network save', async () => {
  let calls = 0;
  const e = new Editor(doc(), { put: async () => { throw Error('disk full'); }, clear: async () => {} }, async d => { calls++; return d; }, () => {});
  e.edit('제목', '보존할 글'); assert.equal(await e.save(), false); assert.equal(calls, 0); assert.equal(e.body, '보존할 글');
});
test('production and malformed destinations blocked', () => {
  assert.equal(serverAddress('http://192.168.0.10:8000/'), 'http://192.168.0.10:8000');
  for (const address of ['https://production.example.test', 'https://example.com', 'http://10.example.com', 'http://192.168.example.com', 'http://192.168.0.1/path', 'file:///tmp/x', 'http://user:pass@192.168.0.1']) assert.throws(() => serverAddress(address));
});
test('native API requests include cookie credentials, CSRF and version; errors retain current', async () => {
  const original = globalThis.fetch; const client = new Api('http://192.168.0.10:8000'); client.csrf = 'fake-csrf';
  globalThis.fetch = (async (url, options) => {
    assert.equal(url, 'http://192.168.0.10:8000/api/manuscripts/fake');
    assert.equal(options?.credentials, 'include'); assert.equal((options?.headers as Record<string,string>)['X-CSRF-Token'], 'fake-csrf');
    assert.equal(JSON.parse(options?.body as string).version, 1);
    return new Response(JSON.stringify({ error: '충돌', current: { ...doc(), version: 2 } }), { status: 409 });
  }) as typeof fetch;
  try { await assert.rejects(client.save(doc()), (error: unknown) => error instanceof ApiError && error.status === 409 && error.current?.version === 2); }
  finally { globalThis.fetch = original; }
});
test('only explicitly configured Codespaces HTTPS API allowed; public production remains blocked', () => {
  const old = process.env.EXPO_PUBLIC_TEST_API_URL;
  const address = 'https://synthetic-demo-8000.app.github.dev';
  try {
    assert.throws(() => serverAddress(address));
    process.env.EXPO_PUBLIC_TEST_API_URL = address;
    assert.equal(serverAddress(address), address);
    for (const url of ['http://synthetic-demo-8000.app.github.dev', 'https://other-demo-8000.app.github.dev', address + '/api', 'https://synthetic-demo-8081.app.github.dev']) assert.throws(() => serverAddress(url));
    process.env.EXPO_PUBLIC_TEST_API_URL = 'https://example.com';
    assert.throws(() => serverAddress('https://example.com'));
  } finally { if (old === undefined) delete process.env.EXPO_PUBLIC_TEST_API_URL; else process.env.EXPO_PUBLIC_TEST_API_URL = old; }
});
test('login refuses a server without synthetic marker before transmitting credentials', async () => {
  const old = globalThis.fetch; let requests = 0;
  globalThis.fetch = (async (url, options) => {
    requests++; assert.equal(options?.method, undefined);
    assert.equal(options?.body, undefined);
    return new Response(JSON.stringify({ syntheticOnly: false }), { status: 200 });
  }) as typeof fetch;
  try { await assert.rejects(new Api('http://127.0.0.1:8000').login('fake@example.com', 'fake'), /로그인을 중단/); assert.equal(requests, 1); }
  finally { globalThis.fetch = old; }
});
test('recovery B survives editing and saving A; namespaces and corrupted drafts are isolated', async () => {
  const entries = new Map<string, string>();
  const disk = { getItem: async (key: string) => entries.get(key) ?? null, setItem: async (key: string, value: string) => { entries.set(key, value); }, removeItem: async (key: string) => { entries.delete(key); } };
  const store = createDraftStore(disk, 'http://localhost:8000', 'fake@example.com');
  const b: Draft = { id: 'synthetic', title: 'B', body: '기기 보관본', version: 1, time: 1 };
  await store.archive(b);
  const a = { ...b, title: 'A', body: '새 서버 글', time: 2 };
  await store.put(a); await store.clear(a);
  assert.deepEqual(await store.read(b.id), b);
  assert.equal(await createDraftStore(disk, 'http://localhost:8000', 'other@example.com').read(b.id), null);
  assert.equal(await createDraftStore(disk, 'http://localhost:8001', 'fake@example.com').read(b.id), null);
  entries.set('yeobaek.mobile.draft.v1:' + JSON.stringify(['http://localhost:8000', 'fake@example.com', b.id]), '{bad');
  await assert.rejects(store.read(b.id));
  assert.equal(entries.size, 2);
});
