/* Real Chromium, synthetic API only. See browser_web_input.cjs for setup. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {fixture,hold,reset}=require('./browser_web_input.cjs');
const full='가나다라마'.repeat(300);
const saved=page=>page.waitForFunction(()=>document.querySelector('#saveStatus').textContent==='저장됨');
async function end(page,id='body'){await page.locator('#'+id).focus();await page.locator('#'+id).evaluate(b=>b.setSelectionRange(b.value.length,b.value.length));}
async function paste(page,text){
 await page.context().grantPermissions(['clipboard-read','clipboard-write'],{origin:'http://127.0.0.1:8765'});
 await page.evaluate(text=>navigator.clipboard.writeText(text),text);
 await page.keyboard.press('Control+v');
}
async function performanceCheck(browser,preUndo){
 const {page,context,state}=await fixture(browser,false,{preUndo});
 await page.evaluate(()=>{for(let i=0;i<100;i++)localStorage.setItem('yeobaek.draft.v1:browser-test%40example.com:'+i+':old',JSON.stringify({id:String(i),title:'가짜',body:'가'.repeat(1500),version:1,time:1}));});
 await end(page);await reset(page);
 for(let i=0;i<300;i++)await page.keyboard.down('Backspace');await page.keyboard.up('Backspace');await saved(page);
 const m=await page.evaluate(()=>({...window.metrics,undoGroups:typeof editHistory==='undefined'?null:editHistory.undoStack.length}));
 assert.equal(await page.inputValue('#body'),full.slice(0,-300));assert.equal(state.puts.length,1);assert.equal(m.bodyAssignments,0);assert.equal(m.storageWrites,300);assert.equal(m.storageReads,101);assert(m.counts<301);
 const times=m.inputMs.sort((a,b)=>a-b);const p95=times[Math.floor(times.length*.95)];
 if(!preUndo){assert.equal(m.undoGroups,1);await page.keyboard.press('Control+z');assert.equal(await page.inputValue('#body'),full);await saved(page);assert.equal(state.doc.body,full);await page.keyboard.press('Control+y');assert.equal(await page.inputValue('#body'),full.slice(0,-300));await saved(page);assert.equal(state.doc.body,full.slice(0,-300));}
 console.log(JSON.stringify({test:'300 repeat Backspaces',version:preUndo?'previous input fix':'final with undo',handlerMs:+times.reduce((a,b)=>a+b,0).toFixed(2),p95Ms:p95,storageReads:m.storageReads,counts:m.counts,bodyAssignments:m.bodyAssignments,undoGroups:m.undoGroups,frameCallbacks:m.frameMs.length,frameMs:+m.frameMs.reduce((a,b)=>a+b,0).toFixed(2),frameP95:[...m.frameMs].sort((a,b)=>a-b)[Math.floor(m.frameMs.length*.95)]}));
 await context.close();return p95;
}
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const before=fs.existsSync('/tmp/yeobaek-app-before-undo.js')&&fs.existsSync('/tmp/yeobaek-style-before-undo.css')?await performanceCheck(browser,true):0,after=await performanceCheck(browser,false);
  assert(after<Math.max(5,before*5),'input p95 regression exceeds generous shared-environment threshold');
  {
   const {page,context,state,errors}=await fixture(browser);
   assert.equal(await page.locator('#undoEdit').isDisabled(),true);assert.equal(await page.locator('#redoEdit').isDisabled(),true);
   assert.match(await page.locator('#undoEdit').getAttribute('title'),/실행 취소/);assert.equal(await page.locator('#redoEdit').getAttribute('aria-label'),'다시 실행');
   await end(page);await paste(page,' 붙여넣기 가짜 글');await saved(page);const pasted=await page.inputValue('#body');
   await page.getByRole('button',{name:'실행 취소',exact:true}).click();assert.equal(await page.inputValue('#body'),full);await saved(page);assert.equal(state.doc.body,full);
   await page.keyboard.press('Control+Shift+z');assert.equal(await page.inputValue('#body'),pasted);await saved(page);
   await page.keyboard.press('Control+z');assert.equal(await page.inputValue('#body'),full);await page.getByRole('button',{name:'다시 실행',exact:true}).click();assert.equal(await page.inputValue('#body'),pasted);
   await page.keyboard.press('Control+z');await page.keyboard.type('new');assert.equal(await page.locator('#redoEdit').isDisabled(),true);await saved(page);
   await end(page,'title');await page.keyboard.type(' 제목');await saved(page);await page.keyboard.press('Control+z');assert.equal(await page.inputValue('#title'),'가짜 테스트');
   // Clean day-only server refresh must leave editing history intact.
   await saved(page);const groups=await page.evaluate(()=>editHistory.undoStack.length);state.doc.day='2099-01-02';await page.evaluate(()=>window.poll());assert.equal(await page.evaluate(()=>editHistory.undoStack.length),groups);
   // A different manuscript or externally replaced text starts a separate history.
   await page.evaluate(()=>render({...current,id:'other',title:'다른 가짜 원고',body:'다른 글',total:3}));assert.equal(await page.locator('#undoEdit').isDisabled(),true);await page.keyboard.press('Control+z');assert.equal(await page.inputValue('#body'),'다른 글');
   assert.deepEqual(errors,[]);console.log('PASS: buttons/three shortcuts/paste/title edits/redo invalidation/autosave/history isolation');await context.close();
  }
  {
   const {page,context,state}=await fixture(browser);await end(page);
   const cdp=await context.newCDPSession(page);
   // Browser IME implementation: compositionstart/update/input/end, not only fake JS events.
   await cdp.send('Input.imeSetComposition',{text:'ㅎ',selectionStart:1,selectionEnd:1});assert.equal(await page.locator('#undoEdit').isDisabled(),true);
   await cdp.send('Input.imeSetComposition',{text:'하',selectionStart:1,selectionEnd:1});await cdp.send('Input.imeSetComposition',{text:'한',selectionStart:1,selectionEnd:1});
   assert.equal(state.puts.length,0);await cdp.send('Input.insertText',{text:'한'});await saved(page);
   assert.equal(await page.inputValue('#body'),full+'한');assert.equal(await page.evaluate(()=>editHistory.undoStack.length),1);
   await page.keyboard.press('Control+z');assert.equal(await page.inputValue('#body'),full);await page.keyboard.press('Control+y');assert.equal(await page.inputValue('#body'),full+'한');
   console.log('PASS: real Chromium IME composition undone/redone as one complete Korean character');await context.close();
  }
  {
   const {page,context,state}=await fixture(browser);const delayed=hold();state.holdPut=delayed;
   await end(page);await paste(page,' 가짜 추가');await delayed.ready;await page.keyboard.press('Control+z');delayed.release();await saved(page);assert.equal(state.doc.body,full);assert.equal(state.puts.length,2);assert.equal(state.puts[1].version,2);
   console.log('PASS: undo during pending PUT saves current input against the updated version');await context.close();
  }
  {
   const {page,context,state}=await fixture(browser);state.fail=true;await end(page);await paste(page,' 실패 테스트');await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent==='저장되지 않음');
   await page.keyboard.press('Control+z');assert.equal(await page.inputValue('#body'),full);const draft=await page.evaluate(()=>YeobaekDrafts.list('browser-test@example.com').find(YeobaekDrafts.isOwn).data);assert.equal(draft.body,full);
   state.fail=false;await page.click('#retry');await saved(page);assert.equal(state.doc.body,full);
   console.log('PASS: undo after failed save updates durable draft and can be retried');await context.close();
  }
  {
   const {page,context,state}=await fixture(browser);await page.evaluate(()=>{const key='yeobaek.draft.v1:browser-test%40example.com:synthetic:old';localStorage.setItem(key,JSON.stringify({id:'synthetic',title:'복구',body:'가짜 B',version:0,time:1}));window.dispatchEvent(new StorageEvent('storage',{key}));});
   await page.waitForFunction(()=>!document.querySelector('#recoveryBanner').hidden);await page.click('#draftsButton');await page.getByRole('button',{name:'B 불러오기',exact:true}).click();
   await end(page);await paste(page,' 추가');await page.keyboard.press('Control+z');await page.keyboard.press('Control+y');assert.equal(await page.evaluate(()=>save()),false);assert.equal(state.puts.length,0);assert.equal(state.doc.body,full);
   await page.click('#retry');await saved(page);assert.equal(state.doc.body,'가짜 B 추가');
   state.doc={...state.doc,body:'서버 다른 글',version:state.doc.version+1};await page.keyboard.press('Control+z');await page.waitForFunction(()=>conflict!==null);await page.keyboard.press('Control+y');assert.equal(await page.evaluate(()=>save(true)),false);assert.equal(state.doc.body,'서버 다른 글');
   console.log('PASS: undo/redo of recovery B still requires explicit save; 409 never bypassed');await context.close();
  }
  {
   const {page,context,errors}=await fixture(browser,false,{legacyHTML:true});await end(page);await page.keyboard.type('fake');await saved(page);assert.deepEqual(errors,[]);console.log('PASS: previous cached HTML with updated scripts remains editable');await context.close();
  }
  {
   const {page,context,state}=await fixture(browser);await page.locator('#body').focus();await page.locator('#body').evaluate(b=>b.setSelectionRange(700,705));await page.keyboard.press('Backspace');assert.equal((await page.inputValue('#body')).length,1495);await page.keyboard.press('Control+z');assert.equal(await page.inputValue('#body'),full);assert.deepEqual(await page.locator('#body').evaluate(b=>[b.selectionStart,b.selectionEnd]),[700,705]);await saved(page);
   state.checkpoints.push({...state.history[0],kind:'manual',label:'중요한 초고'});
   await page.click('#historyButton');await page.locator('#historyDialog').waitFor({state:'visible'});
   assert.equal(await page.locator('#historyList .historyRow[data-version="0"]').count(),1);
   assert.match(await page.locator('#historyList').innerText(),/중요한 초고/);
   assert.equal(await page.locator('.historyPin').count(),0);
   await page.locator('#historyList .historyRow[data-version="0"]').click();
   await page.waitForFunction(()=>document.querySelector('#historyOldBody').value==='가짜 이전 글');
   page.once('dialog',d=>d.accept());await page.click('#restoreHistory');
   await page.waitForFunction(()=>document.querySelector('#body').value==='가짜 이전 글');
   assert.equal(state.doc.body,'가짜 이전 글');assert.equal(state.restores.length,1);
   assert.equal(state.checkpoints.find(point=>point.kind==='before_restore').body,full);
   assert.equal(await page.locator('#undoEdit').isDisabled(),true);
   await end(page);await page.keyboard.type('more');await page.keyboard.press('Control+z');assert.equal(await page.inputValue('#body'),'가짜 이전 글');
   console.log('PASS: unified history keeps existing named point and atomically restores a version');await context.close();
  }
  {
   const {page,context,state}=await fixture(browser);
   await page.locator('#body').fill('가 나\n다😀');
   await page.waitForFunction(()=>document.querySelector('#total').textContent==='5');
   assert.match(await page.locator('#countRule').textContent(),/띄어쓰기 포함 · 줄바꿈 제외/);
   await saved(page);assert.equal(state.doc.total,5);
   console.log('PASS: visible and saved character totals include spaces but exclude line breaks');await context.close();
  }
  {
   const {page,context,state}=await fixture(browser);
   state.doc.today_count_rule='without_spaces';
   await page.evaluate(doc=>render(doc),state.doc);
   await page.locator('#body').fill('가 나\n다😀');
   await page.waitForFunction(()=>document.querySelector('#total').textContent==='5');
   assert.equal(await page.locator('#today').textContent(),'+4');
   assert.match(await page.locator('#countRule').textContent(),/오늘: 공백 제외 \(내일부터 통일\)/);
   console.log('PASS: existing daily counter keeps its original units during the switch day');await context.close();
  }
  for(const viewport of [{width:1280,height:800},{width:390,height:844}]){
   const {page,context}=await fixture(browser,false,{viewport});
   await page.evaluate(()=>render({...current,body:'가짜 줄\n'.repeat(150),total:450}));
   const originalWidth=await page.locator('#title').evaluate(n=>n.getBoundingClientRect().width);
   await page.evaluate(()=>document.querySelector('#editor').scrollTop=400);
   const dimensions=await page.evaluate(()=>{
    const r=id=>document.querySelector('#'+id).getBoundingClientRect(),pane=r('editor'),title=r('title'),body=r('body'),header=document.querySelector('header').getBoundingClientRect();
    return {titleBottom:title.bottom,paneTop:pane.top,bodyTop:body.top,headerTop:header.top,headerBottom:header.bottom,scroll:document.querySelector('#editor').scrollTop,windowScroll:window.scrollY,horizontal:document.querySelector('#editor').scrollWidth>document.querySelector('#editor').clientWidth};
   });
   assert(dimensions.titleBottom<dimensions.paneTop);assert(dimensions.bodyTop<dimensions.paneTop);assert(dimensions.headerTop>=0&&dimensions.headerBottom<viewport.height);assert.equal(dimensions.windowScroll,0);assert.equal(dimensions.horizontal,false);
   // Font style changes immediately; the textarea height follows on its RAF.
   await page.click('#fontToggle');await page.locator('[data-size="18"]').click();await page.waitForFunction(()=>bodySizeFrame===null && document.querySelector('#body').style.height!=='' && getComputedStyle(document.querySelector('#body')).fontSize==='24px');
   assert.equal(await page.locator('#title').evaluate(n=>n.getBoundingClientRect().width),originalWidth);
   const fit=await page.locator('#body').evaluate(n=>({scroll:n.scrollHeight,height:n.clientHeight}));assert(fit.scroll<=fit.height+1);
   await page.locator('#editor').evaluate(n=>n.scrollTop=0);assert.equal(await page.locator('#body').evaluate(n=>n.scrollTop),0);
   const bodyPadding=await page.locator('#body').evaluate(n=>parseFloat(getComputedStyle(n).paddingLeft));assert.equal(bodyPadding,viewport.width<720?24:Math.max(50,(viewport.width-272-720-15)/2));
   await end(page);await page.keyboard.press('Backspace');await page.waitForFunction(()=>bodySizeFrame===null);assert(await page.locator('#editor').evaluate(n=>n.scrollTop)>100);
   await page.screenshot({path:'/tmp/yeobaek-writing-'+viewport.width+'.png'});
   console.log('PASS: title/body share scroll, no reserved title gap, toolbar visible, font/width retained',viewport.width);await context.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
