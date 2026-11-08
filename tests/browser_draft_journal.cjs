/* Synthetic draft durability and compaction in a real browser. */
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const {fixture}=require('./browser_web_input.cjs');

(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const {page,context,state}=await fixture(browser);
  const email='journal-test@example.com',id='journal-test';
  await page.evaluate(({email,id})=>{
   YeobaekDrafts.put(email,{id,title:'첫 제목',body:'가 나 😀 끝',version:1,time:1});
   YeobaekDrafts.put(email,{id,title:'둘째 제목',body:'가 😀 끝',version:1,time:2});
   YeobaekDrafts.put(email,{id,title:'둘째 제목',body:'가 😀 끝에 문장',version:1,time:3});
  },{email,id});
  let item=await page.evaluate(email=>YeobaekDrafts.list(email)[0],email);
  assert.equal(item.data.body,'가 😀 끝에 문장');
  assert.equal(item.data.title,'둘째 제목');
  assert.equal(item.patches.length,2);
  // A recovery dialog must not remove a draft changed after it was opened.
  await page.evaluate(({email,id,item})=>{
   YeobaekDrafts.put(email,{id,title:'둘째 제목',body:'가 😀 끝에 문장!',version:1,time:4});
   YeobaekDrafts.removeUnchanged(item);
  },{email,id,item});
  assert.equal((await page.evaluate(email=>YeobaekDrafts.list(email)[0].data.body,email)),'가 😀 끝에 문장!');
  await page.reload();
  item=await page.evaluate(email=>YeobaekDrafts.list(email)[0],email);
  assert.equal(item.data.body,'가 😀 끝에 문장!');
  assert.equal(item.data.title,'둘째 제목');
  await page.evaluate(({email,id})=>{
   let body='초안';
   for(let i=0;i<205;i++){body+='가';YeobaekDrafts.put(email,{id,title:'긴 초안',body,version:1,time:100+i});}
  },{email,id});
  await page.waitForTimeout(2200);
  item=await page.evaluate(email=>YeobaekDrafts.list(email)[0],email);
  assert.equal(item.data.body,'초안'+'가'.repeat(205));
  assert.equal(item.patches.length,0);
  await page.evaluate(({email,id})=>YeobaekDrafts.put(email,{id,title:'긴 초안',body:'초안'+'가'.repeat(206),version:1,time:400}),{email,id});
  await page.reload();
  item=await page.evaluate(email=>YeobaekDrafts.list(email)[0],email);
  assert.equal(item.data.body,'초안'+'가'.repeat(206));
  await page.evaluate(email=>{for(const draft of YeobaekDrafts.list(email))YeobaekDrafts.removeUnchanged(draft);},email);
  assert.equal(await page.evaluate(email=>YeobaekDrafts.list(email).length,email),0);
  state.doc.body='가'.repeat(120000);state.doc.total=120000;
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#body').value.length===120000);
  await page.evaluate(()=>{const body=document.querySelector('#body');body.focus();body.setSelectionRange(body.value.length,body.value.length);window.metrics.inputMs=[];});
  for(let i=0;i<40;i++)await page.keyboard.press('Backspace');
  const sample=await page.evaluate(()=>{
   const own=YeobaekDrafts.list('browser-test@example.com').find(YeobaekDrafts.isOwn);
   const times=[...window.metrics.inputMs].sort((a,b)=>a-b);
   return {body:own.data.body,patchSizes:own.patches.map(p=>p.value.length),p95:times[Math.floor(times.length*.95)]};
  });
  assert.equal(sample.body,'가'.repeat(119960));
  assert.equal(sample.patchSizes.length,39);
  assert(sample.patchSizes.every(size=>size<500));
  console.log('120k character Backspace p95 input handler: '+sample.p95.toFixed(1)+'ms; patch writes under 500 bytes');
  await context.close();
  console.log('PASS: durable Unicode edits, reload recovery, safe removal, idle compaction');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
