/* Optional real-Chromium regression suite. No live API or database is used.
   npm install --prefix /tmp/yeobaek-browser-tests playwright
   NODE_PATH=/tmp/yeobaek-browser-tests/node_modules node tests/browser_web_input.cjs
   CHROMIUM_PATH can select a locally installed Chromium binary. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const email = 'browser-test@example.com';
const fakeBody = '가나다라마'.repeat(300); // 1,500 synthetic Korean code points.
const count = body => Array.from(body.replace(/\s/gu, '')).length;
const copy = value => JSON.parse(JSON.stringify(value));
const seed = () => ({ id: 'synthetic', title: '가짜 테스트', body: fakeBody, version: 1, updated: 1, total: 1500, today: 1500, day: '2099-01-01' });
const instrument = () => {
  const m = window.metrics = { inputMs: [], frameMs: [], storageReads: 0, storageKeys: 0, storageWrites: 0, bodyAssignments: 0, counts: 0, repeatingKeys: 0, listRebuilds: 0 };
  document.addEventListener('keydown',e=>{if(e.key==='Backspace'&&e.repeat)m.repeatingKeys++;});
  const raf=window.requestAnimationFrame;window.requestAnimationFrame=fn=>raf(time=>{const start=performance.now();try{return fn(time);}finally{m.frameMs.push(performance.now()-start);}});
  const value = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
  Object.defineProperty(HTMLTextAreaElement.prototype, 'value', { ...value, set(v) { if (this.id === 'body') m.bodyAssignments++; value.set.call(this, v); } });
  for (const [method, metric] of [['getItem','storageReads'],['key','storageKeys'],['setItem','storageWrites']]) {
    const original = Storage.prototype[method];
    Storage.prototype[method] = function(...args) { m[metric]++; return original.apply(this,args); };
  }
  const replace = String.prototype.replace;
  String.prototype.replace = function(pattern,...args) { if (pattern instanceof RegExp && pattern.source === '\\s') m.counts++; return replace.call(this,pattern,...args); };
  const replaceChildren = Element.prototype.replaceChildren;
  Element.prototype.replaceChildren = function(...args) { if(this.id==='documents')m.listRebuilds++; return replaceChildren.apply(this,args); };
  const add = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function(type,callback,...args) {
    if (type === 'input' && ['body','title'].includes(this.id)) {
      const original = callback;
      callback = function(...event) { const start = performance.now(); try { return original.apply(this,event); } finally { m.inputMs.push(performance.now()-start); } };
    }
    return add.call(this,type,callback,...args);
  };
  const interval = window.setInterval;
  window.setInterval = (fn,ms,...args) => {
    if (ms === 10000) { window.poll = fn; return 0; } // deterministic polling, no sleeping ten seconds.
    return interval(fn,ms,...args);
  };
};
async function fixture(browser, before = false, options = {}) {
  const context = await browser.newContext({ viewport: options.viewport || { width: 1280, height: 800 }, serviceWorkers: 'block' });
  await context.addInitScript(instrument);
  const page = await context.newPage();
  const state = { doc: seed(), puts: [], gets: 0, fail: false, holdGet: null, holdPut: null, history: [{...seed(),version:0,title:'이전 가짜 제목',body:'가짜 이전 글'}], checkpoints: [], restores: [] };
  await page.route('http://127.0.0.1:8765/**', async route => {
    const req = route.request(), url = new URL(req.url());
    const json = (value, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) });
    if (url.pathname === '/api/me') return json({ email, csrf: 'fake-csrf' });
    if (url.pathname === '/api/manuscripts') return json([state.doc]);
    if (url.pathname === '/api/manuscripts/synthetic') {
      if (req.method() === 'GET') {
        state.gets++;
        const snapshot = copy(state.doc);
        if (state.holdGet) { const hold = state.holdGet; state.holdGet = null; hold.started(); await hold.promise; }
        return json(snapshot);
      }
      const data = req.postDataJSON(); state.puts.push(data);
      if (state.holdPut) { const hold = state.holdPut; state.holdPut = null; hold.started(); await hold.promise; }
      if (state.fail) return json({ error: '가짜 저장 실패' }, 503);
      if (data.version !== state.doc.version) return json({ error: '가짜 동시 수정', current: state.doc }, 409);
      state.history.push(copy(state.doc));
      state.doc = { ...state.doc, ...data, version: state.doc.version + 1, total: count(data.body), today: state.doc.today + count(data.body) - state.doc.total };
      return json(state.doc);
    }
    if (url.pathname === '/api/manuscripts/synthetic/checkpoints') {
      if (req.method() === 'GET') return json(state.checkpoints.map(d=>({version:d.version,title:d.title,updated:d.updated,created:d.updated,kind:d.kind,label:d.label,characters:d.body.length})));
      const data=req.postDataJSON();
      if(data.expected_current_version!==undefined&&data.expected_current_version!==state.doc.version)return json({error:'가짜 동시 수정',current:state.doc},409);
      const source=state.doc.version===data.version?state.doc:state.checkpoints.find(d=>d.version===data.version)||state.history.find(d=>d.version===data.version);
      if(!source)return json({error:'없는 버전'},404);
      state.checkpoints=state.checkpoints.filter(d=>d.version!==data.version);
      state.checkpoints.push({...copy(source),kind:'manual',label:data.label});
      return json({version:data.version,kind:'manual',label:data.label});
    }
    if (url.pathname.startsWith('/api/manuscripts/synthetic/checkpoints/')) return json(state.checkpoints.find(d=>d.version===Number(url.pathname.split('/').at(-1))));
    if (url.pathname === '/api/manuscripts/synthetic/restore') {
      const data=req.postDataJSON();state.restores.push(data);
      if(data.version!==state.doc.version)return json({error:'가짜 동시 수정',current:state.doc},409);
      const source=state.checkpoints.find(d=>d.version===data.source_version)||state.history.find(d=>d.version===data.source_version);
      if(!source)return json({error:'없는 버전'},404);
      state.history.push(copy(state.doc));state.checkpoints.push({...copy(state.doc),kind:'before_restore',label:'복원 전 글'});
      state.doc={...state.doc,title:source.title,body:source.body,version:state.doc.version+1,total:count(source.body)};
      return json(state.doc);
    }
    if (url.pathname === '/api/manuscripts/synthetic/history') return json(state.history.map(d=>({version:d.version,title:d.title,updated:d.updated,characters:d.body.length})));
    if (url.pathname.startsWith('/api/manuscripts/synthetic/history/')) return json(state.history.find(d=>d.version===Number(url.pathname.split('/').at(-1))));
    if (url.pathname.startsWith('/api/')) return json({ error: '없는 가짜 경로' }, 404);
    let filename = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
    let source = path.join(root, 'static', filename);
    if (options.preUndo && filename === 'app.js') source = '/tmp/yeobaek-app-before-undo.js';
    if (options.preUndo && filename === 'style.css') source = '/tmp/yeobaek-style-before-undo.css';
    if (before && filename === 'app.js') source = '/tmp/yeobaek-app-before-input-fix.js';
    if (before && filename === 'safety-storage.js') source = '/tmp/yeobaek-storage-before-input-fix.js';
    if (!fs.existsSync(source)) return route.fulfill({ status: 404, body: '' });
    const contentType = filename.endsWith('.js') ? 'application/javascript' : filename.endsWith('.css') ? 'text/css' : 'text/html';
    let body = fs.readFileSync(source);
    if(options.legacyHTML && filename==='index.html')body=body.toString().replace(/<button[^>]+id="(?:undoEdit|redoEdit)"[^>]*>.*?<\/button>/g,'').replace(/<script src="\/edit-history\.js[^"]*"><\/script>/g,'');
    return route.fulfill({ contentType, body });
  });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('http://127.0.0.1:8765/');
  if (options.viewport?.width <= 720) await page.locator('#documents button').first().click();
  await page.waitForFunction(() => document.querySelector('#body').value.length === 1500);
  return { page, context, state, errors };
}
function hold() {
  let release, started;
  const promise = new Promise(r => { release = r; });
  const ready = new Promise(r => { started = r; });
  return { promise, ready, release, started };
}
async function reset(page) {
  await page.evaluate(() => { const m = window.metrics; for (const k in m) m[k] = Array.isArray(m[k]) ? [] : 0; });
}
async function benchmark(browser, before, leftovers) {
  const { page, context, state, errors } = await fixture(browser, before);
  await page.evaluate(({ email, leftovers }) => {
    for (let i=0;i<leftovers;i++) localStorage.setItem('yeobaek.draft.v1:' + encodeURIComponent(email) + ':old-' + i + ':old-tab', JSON.stringify({ id:'old-' + i, title:'가짜 복구본', body:'가'.repeat(1500), version:0, time:i }));
    const b = document.querySelector('#body'); b.focus(); b.setSelectionRange(b.value.length,b.value.length);
  }, { email, leftovers });
  await reset(page);
  // Native editing commands: actual input events, cursor and selection handling.
  for (let i=0;i<300;i++) await page.keyboard.down('Backspace');
  await page.keyboard.up('Backspace');
  await page.waitForFunction(() => document.querySelector('#saveStatus').textContent === '저장됨');
  const result = await page.evaluate(() => {
    const m = window.metrics, times = [...m.inputMs].sort((a,b) => a-b);
    return { events:times.length, handlerMs: +times.reduce((a,b)=>a+b,0).toFixed(2), p95Ms: times[Math.floor(times.length*.95)], ...Object.fromEntries(Object.entries(m).filter(([k])=>!['inputMs','frameMs'].includes(k))), length:document.querySelector('#body').value.length, total:document.querySelector('#total').textContent, today:document.querySelector('#today').textContent, cursor:document.querySelector('#body').selectionStart };
  });
  assert.equal(result.events,300); assert.equal(result.repeatingKeys,299); assert.equal(result.length,1200); assert.equal(result.total,'1,200'); assert.equal(result.today,'+1,200'); assert.equal(result.cursor,1200);
  assert.equal(state.doc.body,'가나다라마'.repeat(240)); assert.equal(state.puts.length,1); assert.equal(result.bodyAssignments,0); assert.deepEqual(errors,[]);
  console.log(JSON.stringify({ test:'300 native Backspace events', version:before?'before':'after', leftovers, ...result }));
  await context.close(); return result;
}
module.exports={fixture,hold,reset,benchmark};
if(require.main===module)(async () => {
  const browser = await chromium.launch({ executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless:true, args:['--no-sandbox'] });
  try {
    if (process.env.COMPARE_BEFORE === '1') {
      for (const leftovers of [0,100]) {
        const before = await benchmark(browser,true,leftovers);
        const after = await benchmark(browser,false,leftovers);
        assert(after.storageReads < before.storageReads);
        assert(after.counts < before.counts);
      }
    } else await benchmark(browser,false,100);
    {
      const {page,context,state} = await fixture(browser);
      // A burst in one task coalesces the count; every edit remains recoverable.
      await reset(page);
      await page.evaluate(() => {
        const b=document.querySelector('#body');
        for(let i=0;i<300;i++){b.value=b.value.slice(0,-1);b.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'deleteContentBackward'}));}
      });
      await page.waitForFunction(() => document.querySelector('#total').textContent==='1,200');
      const m=await page.evaluate(()=>window.metrics);
      assert.equal(m.storageWrites,300); assert.equal(m.storageReads,0); assert.equal(m.storageKeys,0); assert.equal(m.counts,1);
      console.log('PASS: 300 burst edits, 300 immediate drafts, one count, no recovery scans');
      state.fail=true;
      await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent==='저장되지 않음');
      assert.equal(await page.inputValue('#body'),fakeBody.slice(0,-300));
      const draft=await page.evaluate(email=>YeobaekDrafts.list(email).find(YeobaekDrafts.isOwn).data,email);
      assert.equal(draft.body,fakeBody.slice(0,-300));
      state.fail=false; await page.click('#retry');
      await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent==='저장됨');
      assert.equal(state.doc.body,draft.body);
      console.log('PASS: failed save retains deleted text and recovery copy; retry succeeds');
      await context.close();
    }
    {
      const {page,context,state} = await fixture(browser);
      const delayed=hold(); state.holdGet=delayed;
      await page.evaluate(()=>{void window.poll();}); await delayed.ready;
      await page.locator('#body').press('End'); await page.keyboard.press('Backspace');
      await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent==='저장됨');
      const saved=state.doc.body; await reset(page); delayed.release();
      await page.waitForFunction(()=>!refreshing);
      assert.equal(await page.inputValue('#body'),saved);
      assert.equal(await page.evaluate(()=>window.metrics.bodyAssignments),0);
      assert.equal(await page.evaluate(()=>current.version),state.doc.version);
      console.log('PASS: GET started before deletion cannot revert completed save');
      // Same-body daily rollover must not reset cursor/scroll or textarea value.
      await page.evaluate(()=>{const b=document.querySelector('#body');b.setSelectionRange(350,350);b.scrollTop=100;});
      const scroll=await page.locator('#body').evaluate(b=>b.scrollTop);
      state.doc.day='2099-01-02';state.doc.today=0; await reset(page);
      await page.evaluate(()=>window.poll());
      assert.equal(await page.evaluate(()=>window.metrics.bodyAssignments),0);
      assert.equal(await page.locator('#body').evaluate(b=>b.selectionStart),350);
      assert.equal(await page.locator('#body').evaluate(b=>b.scrollTop),scroll);
      console.log('PASS: day-only refresh preserves selection and scroll');
      await context.close();
    }
    {
      const {page,context,state} = await fixture(browser);
      const delayed=hold();state.holdPut=delayed;
      await page.locator('#body').press('End'); await page.keyboard.press('Backspace');
      await delayed.ready;
      await page.keyboard.press('Backspace'); await page.keyboard.press('Backspace');
      await reset(page); delayed.release();
      await page.waitForFunction(()=>!saving&&dirty);
      assert.equal(await page.evaluate(()=>window.metrics.listRebuilds),0);
      await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent==='저장됨');
      assert.equal(state.doc.body.length,1497); assert.equal(await page.inputValue('#body'),state.doc.body);
      assert.equal(state.puts.length,2);assert.equal(state.puts[1].version,2);
      assert.equal(await page.evaluate(()=>window.metrics.listRebuilds),1);
      console.log('PASS: deletion during PUT retains latest input; sidebar rebuild waits for idle save');
      await context.close();
    }
    {
      const {page,context,state} = await fixture(browser);
      state.doc={...state.doc,body:'다른 기기의 가짜 글',total:11,version:2};
      await page.locator('#body').press('End'); await page.keyboard.press('Backspace');
      await page.waitForFunction(()=>conflict!==null);
      const local=await page.inputValue('#body');
      assert.equal(local.length,1499);assert.equal(state.doc.body,'다른 기기의 가짜 글');
      assert.equal(await page.evaluate(()=>save(true)),false);assert.equal(state.puts.length,1);
      const draft=await page.evaluate(email=>YeobaekDrafts.list(email).find(YeobaekDrafts.isOwn).data,email);
      assert.equal(draft.body,local);
      console.log('PASS: 409 stops writes and preserves local deletion and server version');
      await context.close();
    }
    {
      const {page,context,state} = await fixture(browser);
      const recovery={id:'synthetic',title:'가짜 복구 제목',body:'가짜 기기 보관본 B',version:0,time:1};
      const key='yeobaek.draft.v1:'+encodeURIComponent(email)+':synthetic:previous-tab';
      await page.evaluate(({key,recovery})=>{localStorage.setItem(key,JSON.stringify(recovery));window.dispatchEvent(new StorageEvent('storage',{key}));},{key,recovery});
      await page.waitForFunction(()=>!document.querySelector('#recoveryBanner').hidden);
      await page.click('#draftsButton');
      await page.getByRole('button',{name:'B 불러오기',exact:true}).click();
      assert.equal(await page.inputValue('#body'),recovery.body);
      assert.equal(await page.evaluate(()=>save()),false);assert.equal(state.puts.length,0);assert.equal(state.doc.body,fakeBody);
      await page.click('#retry');
      await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent==='저장됨');
      assert.equal(state.doc.body,recovery.body);
      console.log('PASS: cross-tab recovery discovery and B requires explicit save');
      await context.close();
    }
    {
      const {page,context,state} = await fixture(browser);
      await page.evaluate(()=>document.querySelector('#body').dispatchEvent(new CompositionEvent('compositionstart')));
      await page.evaluate(()=>window.poll());assert.equal(state.gets,0);
      await page.evaluate(()=>{const b=document.querySelector('#body');b.value='가짜 조합 중';b.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true}));});
      assert.equal(state.puts.length,0);
      await page.evaluate(()=>document.querySelector('#body').dispatchEvent(new CompositionEvent('compositionend')));
      await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent==='저장됨');
      assert.equal(state.doc.body,'가짜 조합 중');
      console.log('PASS: IME composition blocks polling and saves only after composition ends');
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
