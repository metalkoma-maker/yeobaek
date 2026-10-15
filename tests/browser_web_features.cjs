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
  if(url.pathname==='/api/manuscripts')return json(state.ids.map(id=>state.docs.find(d=>d.id===id)));
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
const ids=page=>page.locator('#documents button').evaluateAll(nodes=>nodes.map(node=>node.dataset.id));
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
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
