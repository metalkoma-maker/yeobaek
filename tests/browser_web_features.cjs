/* Synthetic API only: real browser downloads, recent ordering, and pins.
   NODE_PATH=<playwright location> node tests/browser_web_features.cjs */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root=path.resolve(__dirname,'..');
const copy=value=>JSON.parse(JSON.stringify(value));
const seed=()=>({docs:['a','b','c'].map((id,i)=>({id,title:'가짜 원고 '+id,body:'가짜 본문 '+id,version:0,updated:3-i,total:5,today:5,day:'2026-10-15',pinned:false})),ids:['c','b','a'],pins:[],pinPuts:[],bodyPuts:[],failPin:false,holdList:null});
const sortedDocs=state=>{
 const pins=new Map(state.pins.map((id,i)=>[id,i]));
 return [...state.docs].sort((a,b)=>Number(pins.has(b.id))-Number(pins.has(a.id))||(pins.has(a.id)?pins.get(a.id)-pins.get(b.id):b.updated-a.updated));
};
function hold(){let release,started;const promise=new Promise(r=>release=r),ready=new Promise(r=>started=r);return {release,started,promise,ready};}
async function fixture(browser,state){
 const context=await browser.newContext({viewport:{width:1280,height:800},serviceWorkers:'block',timezoneId:'America/New_York'});
 await context.addInitScript(()=>{
  const original=setInterval;
  window.setInterval=(fn,ms,...args)=>ms===10000?(window.poll=fn,0):original(fn,ms,...args);
 });
 const page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('http://127.0.0.1:8765/**',async route=>{
  const req=route.request(),url=new URL(req.url());
  const json=(value,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(value)});
  if(url.pathname==='/api/me')return json({email:'web-features@example.com',csrf:'synthetic-csrf'});
  if(url.pathname==='/api/manuscripts'){
   if(req.method()==='POST'){
    const doc={id:'new-'+state.docs.length,title:'제목 없는 원고',body:'',version:0,updated:Date.now()/1000,total:0,today:0,day:'2026-10-15',pinned:false};
    state.docs.push(doc);return json(doc,201);
   }
   const snapshot=copy(sortedDocs(state));
   if(state.holdList){const pending=state.holdList;state.holdList=null;pending.started();await pending.promise;}
   return json(snapshot);
  }
  if(url.pathname==='/api/manuscript-order'){
   if(req.method()==='GET')return json({ids:sortedDocs(state).map(d=>d.id),version:0});
   return json({error:'최근 수정순을 사용합니다.'},409);
  }
  const copying=/^\/api\/manuscripts\/([^/]+)\/copy$/.exec(url.pathname);
  if(copying){
   const source=state.docs.find(d=>d.id===copying[1]),data=req.postDataJSON();
   if(data.version!==source.version)return json({error:'다른 기기에서 원고가 수정됐습니다.',current:source},409);
   const created={...copy(source),id:'copy-'+state.docs.length,title:data.title,version:0,updated:Date.now()/1000,today:0,pinned:false};
   state.docs.push(created);return json(created,201);
  }
  const pinning=/^\/api\/manuscripts\/([^/]+)\/pin$/.exec(url.pathname);
  if(pinning){
   const doc=state.docs.find(d=>d.id===pinning[1]),pinned=req.postDataJSON().pinned;
   state.pinPuts.push({id:doc.id,pinned});
   if(state.failPin)return json({error:'가짜 통신 실패'},503);
   if(pinned&&!doc.pinned)state.pins.push(doc.id);
   if(!pinned)state.pins=state.pins.filter(id=>id!==doc.id);
   doc.pinned=pinned;return json(doc);
  }
  if(/^\/api\/manuscripts\/[^/]+\/session-checkpoint$/.test(url.pathname))return json({version:req.postDataJSON().version,saved:true});
  if(url.pathname.startsWith('/api/manuscripts/')){
   const id=url.pathname.split('/')[3],doc=state.docs.find(d=>d.id===id);
   if(req.method()==='GET')return json(doc);
   const data=req.postDataJSON();state.bodyPuts.push(data);
   if(data.version!==doc.version)return json({error:'원고 충돌',current:doc},409);
   Object.assign(doc,data,{version:doc.version+1,updated:Date.now()/1000});return json(doc);
  }
  if(url.pathname.startsWith('/api/'))return json({error:'없는 가짜 경로'},404);
  const filename=url.pathname==='/'?'index.html':url.pathname.slice(1);
  const file=path.join(root,'static',filename);
  if(!fs.existsSync(file))return route.fulfill({status:404,body:''});
  return route.fulfill({body:fs.readFileSync(file),contentType:filename.endsWith('.js')?'application/javascript':filename.endsWith('.css')?'text/css':'text/html'});
 });
 await page.goto('http://127.0.0.1:8765/');
 await page.locator('#workspace').waitFor({state:'visible'});
 await page.waitForFunction(expected=>document.querySelector('#body').value===expected,sortedDocs(state)[0].body);
 return {context,page,errors};
}
const ids=page=>page.locator('#documents .documentCard').evaluateAll(nodes=>nodes.map(node=>node.dataset.id));
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  {
   const state=seed(),{context,page,errors}=await fixture(browser,state);
   await page.clock.setFixedTime(new Date('2026-10-15T03:04:05Z'));
   const body='저장 전에도 내려받는 글\n가나다 😀\n';
   await page.locator('#body').fill(body);
   const completed=page.waitForEvent('download');await page.locator('#download').click();const download=await completed;
   assert.equal(download.suggestedFilename(),'가짜 원고 a.txt');
   const contents=await fs.promises.readFile(await download.path(),'utf8');
   assert.equal(contents,'내려받은 시각: 2026-10-15 12:04:05 (한국시간)\n\n가짜 원고 a\n\n'+body);
   assert.equal(await page.inputValue('#body'),body);assert.deepEqual(errors,[]);
   console.log('PASS: TXT starts with Korean download time including seconds and preserves current text');
   await context.close();
  }
  {
   const state=seed(),{context,page,errors}=await fixture(browser,state);
   await page.locator('#body').fill('저장 후 복사할 글');
   await page.locator('[data-id="a"] ~ .documentMore').click();
   await page.locator('#copyDialog').waitFor({state:'visible'});
   assert.equal(await page.inputValue('#copyTitle'),'가짜 원고 a · 2고');
   assert.equal(await page.locator('#copyMessage').textContent(),'');
   assert.equal(await page.locator('#copyMessage').isVisible(),false);
   assert.doesNotMatch(await page.locator('#copyDialog').innerText(),/3교를 시작할 때/);
   await page.locator('#copyConfirm').click();
   await page.waitForFunction(()=>current.id==='copy-3');
   await page.waitForFunction(()=>!copyBusy&&!document.querySelector('#copyDialog').open);
   assert.equal(state.docs.find(d=>d.id==='a').body,'저장 후 복사할 글');
   assert.equal(state.docs.find(d=>d.id==='copy-3').body,'저장 후 복사할 글');
   assert.equal(state.docs.find(d=>d.id==='copy-3').today,0);
   assert.equal((await ids(page))[0],'copy-3');
   await page.locator('[data-id="a"] ~ .documentMore').click();
   await page.locator('#copyDialog').waitFor({state:'visible'});
   assert.equal(await page.inputValue('#copyTitle'),'가짜 원고 a · 3고');
   await page.locator('#copyConfirm').click();
   await page.waitForFunction(()=>current.id==='copy-4');
   await page.waitForFunction(()=>!copyBusy&&!document.querySelector('#copyDialog').open);
   await page.locator('[data-id="a"] ~ .documentMore').click();
   await page.locator('#copyDialog').waitFor({state:'visible'});
   const before=state.docs.length;state.docs.find(d=>d.id==='a').version++;
   await page.locator('#copyConfirm').click();
   await page.waitForFunction(()=>document.querySelector('#copyMessage').textContent.includes('다른 기기'));
   assert.equal(state.docs.length,before);await page.locator('#copyCancel').click();
   assert.deepEqual(errors,[]);console.log('PASS: saving as 2고/3고 preserves source and blocks stale copies');await context.close();
  }
  {
   const state=seed();state.docs.find(d=>d.id==='a').title='가짜 원고 a · 2교';
   const {context,page,errors}=await fixture(browser,state);
   await page.locator('[data-id="a"] ~ .documentMore').click();
   await page.locator('#copyDialog').waitFor({state:'visible'});
   assert.equal(await page.inputValue('#copyTitle'),'가짜 원고 a · 3고');
   assert.deepEqual(errors,[]);await context.close();
  }
  {
   const state=seed(),longTitle='가'.repeat(200);
   state.docs.find(d=>d.id==='a').title=longTitle;
   const {context,page,errors}=await fixture(browser,state);
   for(const round of [2,3]){
    await page.locator('[data-id="a"] ~ .documentMore').click();
    await page.locator('#copyDialog').waitFor({state:'visible'});
    assert.equal(await page.inputValue('#copyTitle'),longTitle.slice(0,195)+' · '+round+'고');
    await page.locator('#copyConfirm').click();
    await page.waitForFunction(expected=>docs.length===expected,round+2);
    await page.waitForFunction(()=>!copyBusy&&!document.querySelector('#copyDialog').open);
   }
   assert.deepEqual(errors,[]);console.log('PASS: a full-length title still advances copy round numbers');await context.close();
  }
  {
   const state=seed(),{context,page,errors}=await fixture(browser,state);
   assert.deepEqual(await ids(page),['a','b','c'],'old manual order must be ignored');
   assert.equal(await page.locator('[data-id="a"]').getAttribute('draggable'),null);
   await page.locator('[data-id="c"]').click();
   const saved=page.waitForResponse(response=>response.url().endsWith('/api/manuscripts/c')&&response.request().method()==='PUT');
   await page.locator('#body').fill('가짜 원고 c를 새로 수정');
   assert.equal((await saved).status(),200);
   await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent==='저장됨'&&docs[0].id==='c');
   assert.equal((await ids(page))[0],'c');
   assert.equal(await page.inputValue('#body'),'가짜 원고 c를 새로 수정');
   assert.deepEqual(errors,[]);console.log('PASS: a saved manuscript moves above the old manual order');await context.close();
  }
  {
   const state=seed(),{context,page,errors}=await fixture(browser,state);
   await page.locator('[data-pin-id="b"]').click();
   await page.waitForFunction(()=>docs[0].id==='b');
   await page.locator('[data-pin-id="c"]').click();
   await page.waitForFunction(()=>docs[1].id==='c'&&docs[1].pinned);
   assert.deepEqual(await ids(page),['b','c','a']);
   assert.equal(await page.locator('[data-pin-id="b"]').getAttribute('aria-pressed'),'true');
   await page.locator('[data-id="c"]').click();
   await page.locator('#body').fill('나중에 수정한 고정 원고');
   await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent==='저장됨');
   assert.deepEqual(await ids(page),['b','c','a'],'writing must not rearrange pins');
   const other=await fixture(browser,state);
   assert.deepEqual(await ids(other.page),['b','c','a']);await other.context.close();
   await page.reload();await page.locator('#workspace').waitFor({state:'visible'});
   assert.deepEqual(await ids(page),['b','c','a']);
   await page.locator('[data-pin-id="b"]').click();
   await page.waitForFunction(()=>!docs.find(d=>d.id==='b').pinned);
   assert.deepEqual(await ids(page),['c','a','b']);
   assert.deepEqual(errors,[]);console.log('PASS: pins persist across browsers and keep their original pin order');await context.close();
  }
  {
   const state=seed(),{context,page,errors}=await fixture(browser,state);
   state.failPin=true;await page.locator('[data-pin-id="b"]').click();
   await page.waitForFunction(()=>!document.querySelector('#pinError').hidden&&document.querySelector('#pinError').textContent.includes('가짜 통신 실패'));
   assert.deepEqual(await ids(page),['a','b','c']);
   assert.equal(state.bodyPuts.length,0);
   state.failPin=false;await page.locator('[data-pin-id="b"]').click();
   await page.waitForFunction(()=>docs[0].id==='b');
   assert.deepEqual(errors,[]);console.log('PASS: a failed pin leaves manuscripts and order unchanged');await context.close();
  }
  {
   const state=seed(),{context,page,errors}=await fixture(browser,state);
   const delayed=hold();state.holdList=delayed;
   await page.evaluate(()=>{void window.poll();});await delayed.ready;
   await page.locator('[data-pin-id="c"]').click();
   await page.waitForFunction(()=>docs[0].id==='c');
   delayed.release();await page.waitForFunction(()=>!refreshing);
   assert.deepEqual(await ids(page),['c','a','b']);
   assert.deepEqual(errors,[]);console.log('PASS: an older list response cannot undo a pin');await context.close();
  }
  {
   const state=seed(),{context,page,errors}=await fixture(browser,state);
   const delayed=hold();state.holdList=delayed;
   await page.evaluate(()=>{void window.poll();});await delayed.ready;
   await page.locator('#body').fill('목록 조회 중 새로 저장한 가짜 글');
   await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent==='저장됨');
   delayed.release();await page.waitForFunction(()=>!refreshing);
   assert.equal(await page.evaluate(()=>docs.find(d=>d.id==='a').body),state.docs.find(d=>d.id==='a').body);
   assert.equal(await page.inputValue('#body'),state.docs.find(d=>d.id==='a').body);
   assert.deepEqual(errors,[]);console.log('PASS: an older list response cannot replace a save');await context.close();
  }
  {
   const state=seed(),{context,page,errors}=await fixture(browser,state);
   const delayed=hold();state.holdList=delayed;
   await page.evaluate(()=>{void window.poll();});await delayed.ready;
   await page.locator('#newDoc').click();await page.waitForFunction(()=>current.id.startsWith('new-'));
   delayed.release();await page.waitForFunction(()=>!refreshing);
   assert.equal((await ids(page))[0],'new-3');
   assert.equal(await page.inputValue('#body'),'');assert.deepEqual(errors,[]);
   console.log('PASS: an older list response cannot remove a newly created manuscript');await context.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
