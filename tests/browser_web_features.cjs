/* Synthetic API only: real browser downloads and mouse drag sorting.
   NODE_PATH=<playwright location> node tests/browser_web_features.cjs */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root=path.resolve(__dirname,'..');
const copy=value=>JSON.parse(JSON.stringify(value));
const seed=()=>({docs:['a','b','c'].map((id,i)=>({id,title:'가짜 원고 '+id,body:'가짜 본문 '+id,version:0,updated:i+1,total:5,today:5,day:'2026-10-15'})),ids:['a','b','c'],version:0,orderPuts:[],bodyPuts:[],fail:false,holdOrder:null});
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
    const doc={id:'new-'+state.docs.length,title:'제목 없는 원고',body:'',version:0,updated:99,total:0,today:0,day:'2026-10-15'};
    state.docs.push(doc);state.ids.unshift(doc.id);return json(doc,201);
   }
   return json(state.ids.map(id=>state.docs.find(d=>d.id===id)));
  }
  if(url.pathname==='/api/manuscript-order'){
   if(req.method()==='GET'){
    const snapshot={ids:[...state.ids],version:state.version};
    if(state.holdOrder){const pending=state.holdOrder;state.holdOrder=null;pending.started();await pending.promise;}
    return json(snapshot);
   }
   const data=req.postDataJSON();state.orderPuts.push(data);
   if(state.fail)return json({error:'가짜 통신 실패'},503);
   if(data.version!==state.version)return json({error:'다른 기기의 순서 변경',current:{ids:state.ids,version:state.version}},409);
   state.ids=[...data.ids];state.version++;return json({ids:state.ids,version:state.version});
  }
  const copying=/^\/api\/manuscripts\/([^/]+)\/copy$/.exec(url.pathname);
  if(copying){
   const source=state.docs.find(d=>d.id===copying[1]),data=req.postDataJSON();
   if(data.version!==source.version)return json({error:'다른 기기에서 원고가 수정됐습니다.',current:source},409);
   const created={...copy(source),id:'copy-'+state.docs.length,title:data.title,version:0,updated:Date.now()/1000|0,today:0};
   state.docs.push(created);state.ids.unshift(created.id);return json(created,201);
  }
  if(url.pathname.startsWith('/api/manuscripts/')){
   const id=url.pathname.split('/')[3],doc=state.docs.find(d=>d.id===id);
   if(req.method()==='GET')return json(doc);
   const data=req.postDataJSON();state.bodyPuts.push(data);
   if(data.version!==doc.version)return json({error:'원고 충돌',current:doc},409);
   Object.assign(doc,data,{version:doc.version+1});return json(doc);
  }
  if(url.pathname.startsWith('/api/'))return json({error:'없는 가짜 경로'},404);
  const filename=url.pathname==='/'?'index.html':url.pathname.slice(1);
  const file=path.join(root,'static',filename);
  if(!fs.existsSync(file))return route.fulfill({status:404,body:''});
  return route.fulfill({body:fs.readFileSync(file),contentType:filename.endsWith('.js')?'application/javascript':filename.endsWith('.css')?'text/css':'text/html'});
 });
 await page.goto('http://127.0.0.1:8765/');
 await page.locator('#workspace').waitFor({state:'visible'});
 await page.waitForFunction(expected=>document.querySelector('#body').value===expected,state.docs.find(d=>d.id===state.ids[0]).body);
 return {context,page,errors};
}
const ids=page=>page.locator('#documents .documentCard').evaluateAll(nodes=>nodes.map(node=>node.dataset.id));
async function dragBefore(page,from,to){
 const saved=page.waitForResponse(r=>r.url().endsWith('/api/manuscript-order')&&r.request().method()==='PUT');
 await page.locator('[data-id="'+from+'"]').dragTo(page.locator('[data-id="'+to+'"]'),{targetPosition:{x:20,y:5}});
 const result=await saved;
 await page.waitForFunction(()=>!orderBusy);
 return result.status();
}
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
   await page.locator('[data-id="a"] + .documentMore').click();
   await page.locator('#copyDialog').waitFor({state:'visible'});
   assert.equal(await page.inputValue('#copyTitle'),'가짜 원고 a · 2교');
   await page.locator('#copyConfirm').click();
   await page.waitForFunction(()=>current.id==='copy-3');
   await page.waitForFunction(()=>!copyBusy&&!document.querySelector('#copyDialog').open);
   assert.equal(state.docs.find(d=>d.id==='a').body,'저장 후 복사할 글');
   assert.equal(state.docs.find(d=>d.id==='copy-3').body,'저장 후 복사할 글');
   assert.equal(state.docs.find(d=>d.id==='copy-3').today,0);
   assert.equal((await ids(page))[0],'copy-3');
   await page.locator('[data-id="a"] + .documentMore').click();
   await page.locator('#copyDialog').waitFor({state:'visible'});
   assert.equal(await page.inputValue('#copyTitle'),'가짜 원고 a · 3교');
   await page.locator('#copyConfirm').click();
   await page.waitForFunction(()=>current.id==='copy-4');
   await page.waitForFunction(()=>!copyBusy&&!document.querySelector('#copyDialog').open);
   await page.locator('[data-id="a"] + .documentMore').click();
   await page.locator('#copyDialog').waitFor({state:'visible'});
   const before=state.docs.length;state.docs.find(d=>d.id==='a').version++;
   await page.locator('#copyConfirm').click();
   await page.waitForFunction(()=>document.querySelector('#copyMessage').textContent.includes('다른 기기'));
   assert.equal(state.docs.length,before);await page.locator('#copyCancel').click();
   assert.deepEqual(errors,[]);console.log('PASS: saving as 2교/3교 preserves source and blocks stale copies');await context.close();
  }
  {
   const state=seed(),longTitle='가'.repeat(200);
   state.docs.find(d=>d.id==='a').title=longTitle;
   const {context,page,errors}=await fixture(browser,state);
   for(const round of [2,3]){
    await page.locator('[data-id="a"] + .documentMore').click();
    await page.locator('#copyDialog').waitFor({state:'visible'});
    assert.equal(await page.inputValue('#copyTitle'),longTitle.slice(0,195)+' · '+round+'교');
    await page.locator('#copyConfirm').click();
    await page.waitForFunction(expected=>docs.length===expected,round+2);
    await page.waitForFunction(()=>!copyBusy&&!document.querySelector('#copyDialog').open);
   }
   assert.deepEqual(errors,[]);console.log('PASS: a full-length title still advances copy round numbers');await context.close();
  }
  {
   const state=seed(),{context,page,errors}=await fixture(browser,state);
   const original=await page.inputValue('#body');
   assert.equal(await dragBefore(page,'c','a'),200);
   assert.deepEqual(await ids(page),['c','a','b']);assert.deepEqual(state.orderPuts[0],{ids:['c','a','b'],version:0});
   assert.equal(await page.inputValue('#body'),original);assert.equal(state.bodyPuts.length,0);
   await page.reload();await page.locator('#workspace').waitFor({state:'visible'});
   assert.deepEqual(await ids(page),['c','a','b']);
   const other=await fixture(browser,state);
   assert.deepEqual(await ids(other.page),['c','a','b']);await other.context.close();
   // An independent device changes order; periodic refresh must adopt it.
   state.ids=['b','c','a'];state.version++;
   await page.evaluate(()=>window.poll());
   assert.deepEqual(await ids(page),state.ids);assert.deepEqual(errors,[]);
   console.log('PASS: native mouse drag persists after reload and on another browser; remote order refreshes');
   await context.close();
  }
  {
   const state=seed(),{context,page,errors}=await fixture(browser,state);
   let saved=page.waitForResponse(r=>r.url().endsWith('/api/manuscript-order')&&r.request().method()==='PUT');
   await page.locator('[data-id="a"]').dragTo(page.locator('#sidebar .account'),{targetPosition:{x:30,y:18}});
   assert.equal((await saved).status(),200);
   await page.waitForFunction(()=>!orderBusy);
   assert.deepEqual(state.ids,['b','c','a']);
   saved=page.waitForResponse(r=>r.url().endsWith('/api/manuscript-order')&&r.request().method()==='PUT');
   await page.locator('[data-id="a"]').dragTo(page.locator('#sidebar .sideTop'),{targetPosition:{x:150,y:10}});
   assert.equal((await saved).status(),200);
   await page.waitForFunction(()=>!orderBusy);
   assert.deepEqual(state.ids,['a','b','c']);
   assert.equal(await page.inputValue('#body'),'가짜 본문 a');
   assert.equal(state.bodyPuts.length,0);assert.deepEqual(errors,[]);
   console.log('PASS: dropping far below or above the manuscript cards saves the correct order');
   await context.close();
  }
  {
   const state=seed();
   state.docs=Array.from({length:30},(_,i)=>({id:'row-'+i,title:'가짜 원고 '+i,body:'가짜 본문 '+i,version:0,updated:i+1,total:5,today:5,day:'2026-10-15'}));
   state.ids=state.docs.map(d=>d.id);
   const {context,page,errors}=await fixture(browser,state);
   const source=await page.locator('[data-id="row-0"]').boundingBox();
   const nav=await page.locator('#documents').boundingBox();
   await page.mouse.move(source.x+30,source.y+25);
   await page.mouse.down();
   await page.mouse.move(source.x+30,source.y+60,{steps:5});
   await page.mouse.move(nav.x+60,nav.y+nav.height-8,{steps:10});
   await page.waitForFunction(()=>draggedId==='row-0'&&document.querySelector('#documents').scrollTop>80);
   await page.mouse.move(nav.x+61,nav.y+nav.height-9,{steps:2});
   const saved=page.waitForResponse(r=>r.url().endsWith('/api/manuscript-order')&&r.request().method()==='PUT');
   await page.mouse.up();
   assert.equal((await saved).status(),200);
   await page.waitForFunction(()=>!orderBusy);
   await page.waitForFunction(()=>!orderBusy);
   assert.ok(state.ids.indexOf('row-0')>1);
   assert.deepEqual(errors,[]);
   console.log('PASS: holding a dragged manuscript near the list edge scrolls toward distant positions');
   await context.close();
  }
  {
   const state=seed(),{context,page,errors}=await fixture(browser,state);
   state.fail=true;assert.equal(await dragBefore(page,'c','a'),503);
   assert.deepEqual(await ids(page),['a','b','c']);assert.equal(await page.inputValue('#body'),'가짜 본문 a');
   assert.match(await page.locator('#listOrderStatus').textContent(),/저장하지 못했습니다/);
   state.fail=false;state.ids=['b','a','c'];state.version++;
   assert.equal(await dragBefore(page,'c','a'),409);
   assert.deepEqual(await ids(page),['b','a','c']);
   assert.match(await page.locator('#listOrderStatus').textContent(),/다른 기기/);
   assert.equal(state.bodyPuts.length,0);assert.deepEqual(errors,[]);
   console.log('PASS: failed sorting restores order; stale sorting adopts server list without touching text');
   await context.close();
  }
  {
   const state=seed(),{context,page,errors}=await fixture(browser,state);
   const delayed=hold();state.holdOrder=delayed;
   await page.evaluate(()=>{void window.poll();});await delayed.ready;
   assert.equal(await dragBefore(page,'c','a'),200);
   delayed.release();await page.waitForFunction(()=>!refreshing);
   assert.deepEqual(await ids(page),['c','a','b']);
   assert.equal(await page.inputValue('#body'),'가짜 본문 a');assert.deepEqual(errors,[]);
   // Keyboard sorting is available alongside the mouse operation.
   await page.locator('[data-id="a"]').press('Alt+ArrowDown');
   await page.waitForFunction(()=>!orderBusy&&docs.map(d=>d.id).join(',')==='c,b,a');
   assert.deepEqual(state.ids,['c','b','a']);
   console.log('PASS: late list response cannot undo a completed drag; keyboard move also saves');
   await context.close();
  }
  {
   const state=seed(),{context,page,errors}=await fixture(browser,state);
   const delayed=hold();state.holdOrder=delayed;
   await page.evaluate(()=>{void window.poll();});await delayed.ready;
   await page.locator('#body').fill('목록 조회 중 새로 저장한 가짜 글');
   await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent==='저장됨');
   delayed.release();await page.waitForFunction(()=>!refreshing);
   assert.equal(await page.evaluate(()=>docs.find(d=>d.id==='a').body),state.docs.find(d=>d.id==='a').body);
   assert.equal(await page.inputValue('#body'),state.docs.find(d=>d.id==='a').body);
   assert.deepEqual(errors,[]);await context.close();
   console.log('PASS: list response started before an edit cannot replace the newly saved sidebar data');
  }
  {
   const state=seed(),{context,page,errors}=await fixture(browser,state);
   const delayed=hold();state.holdOrder=delayed;
   await page.evaluate(()=>{void window.poll();});await delayed.ready;
   await page.locator('#newDoc').click();await page.waitForFunction(()=>current.id.startsWith('new-'));
   delayed.release();await page.waitForFunction(()=>!refreshing);
   assert.equal((await ids(page))[0],'new-3');
   assert.equal(await page.inputValue('#body'),'');assert.deepEqual(errors,[]);await context.close();
   console.log('PASS: a late list response cannot remove a newly created manuscript');
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
