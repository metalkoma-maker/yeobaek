/* Synthetic browser account flows. No real email or user data. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'../static');
async function fixture(browser,loggedIn){
 const context=await browser.newContext({serviceWorkers:'block'}),page=await context.newPage();
 const state={loggedIn,calls:[],errors:[]};page.on('pageerror',e=>state.errors.push(e.message));
 await page.route('http://127.0.0.1:8766/**',async route=>{
  const req=route.request(),url=new URL(req.url());
  const json=(data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
  if(url.pathname.startsWith('/api/')){
   if(url.pathname==='/api/me')return state.loggedIn?json({email:'fake@example.test',csrf:'old-csrf'}):json({error:'로그인이 필요합니다.'},401);
   if(url.pathname==='/api/manuscripts')return json([]);
   if(url.pathname==='/api/manuscript-order')return json({ids:[],version:0});
   state.calls.push({path:url.pathname,data:req.postDataJSON(),csrf:req.headers()['x-csrf-token']});
   if(url.pathname==='/api/account/password')return json({email:'fake@example.test',csrf:'new-csrf'});
   if(url.pathname==='/api/account/delete'){state.loggedIn=false;return json({ok:true});}
   if(url.pathname==='/api/password-reset/confirm')return json({ok:true});
   if(url.pathname==='/api/account/recover-id'||url.pathname==='/api/password-reset/request')return json({message:'입력한 이메일로 안내를 보냈습니다.'});
   return json({error:'가짜 경로 없음'},404);
  }
  const filename=url.pathname==='/'?'index.html':url.pathname.slice(1),file=path.join(root,filename);
  if(!fs.existsSync(file))return route.fulfill({status:404,body:''});
  return route.fulfill({body:fs.readFileSync(file),contentType:filename.endsWith('.js')?'application/javascript':filename.endsWith('.css')?'text/css':'text/html'});
 });
 await page.goto('http://127.0.0.1:8766/');
 if(loggedIn)await page.locator('#workspace').waitFor({state:'visible'});
 return {context,page,state};
}
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  {
   const {context,page,state}=await fixture(browser,false);
   assert.equal(await page.locator('#recoverId').count(),0);
   await page.locator('#forgotPassword').click();
   await page.locator('#recoveryEmail').fill('fake@example.test');await page.locator('#recoveryMailSubmit').click();
   await page.waitForFunction(()=>document.querySelector('#recoveryMailMessage').textContent.includes('안내'));
   assert.equal(state.calls.at(-1).path,'/api/password-reset/request');
   await page.goto('http://127.0.0.1:8766/#reset='+'a'.repeat(43));await page.reload();
   await page.locator('#resetDialog').waitFor({state:'visible'});
   assert.equal(await page.evaluate(()=>location.hash),'');
   await page.locator('#resetPassword').fill('new-password-123');await page.locator('#resetPasswordAgain').fill('different-password-123');
   await page.locator('#resetSubmit').click();
   assert.equal(state.calls.filter(x=>x.path==='/api/password-reset/confirm').length,0);
   await page.locator('#resetPasswordAgain').fill('new-password-123');await page.locator('#resetSubmit').click();
   await page.waitForFunction(()=>document.querySelector('#resetMessage').textContent.includes('바꿨습니다'));
   assert.equal(state.calls.at(-1).data.token,'a'.repeat(43));
   assert.deepEqual(state.errors,[]);await context.close();console.log('PASS: account reminder and one-use reset-link web screens');
  }
  {
   const {context,page,state}=await fixture(browser,true);
   await page.locator('#accountSettings').click();await page.locator('#currentPassword').fill('old-password-123');
   await page.locator('#newPassword').fill('new-password-123');await page.locator('#newPasswordAgain').fill('new-password-123');
   await page.locator('#changePasswordSubmit').click();
   await page.waitForFunction(()=>document.querySelector('#changePasswordMessage').textContent.includes('바꿨습니다'));
   assert.equal(await page.evaluate(()=>csrf),'new-csrf');
   await page.locator('#deleteAccountDetails summary').click();
   await page.locator('#deletePassword').fill('new-password-123');await page.locator('#deleteConfirmation').fill('탈퇴');
   await page.evaluate(()=>localStorage.setItem('yeobaek.draft.v1:fake%40example.test:doc:tab','synthetic'));
   await page.locator('#deleteAccountSubmit').click();
   await page.locator('#deleteWarningDialog').waitFor({state:'visible'});
   assert.match(await page.locator('#deleteWarningText').textContent(),/계정과 모든 원고, 수정 이력, 복원 지점/);
   assert.equal(await page.locator('#accountDialog').getByText('백업 파일에는 탈퇴 전 데이터가 남아 있을 수 있습니다.').count(),0);
   assert.equal(await page.locator('#deleteWarningDialog').getByText('백업 파일에는 탈퇴 전 데이터가 남아 있을 수 있습니다.').count(),0);
   assert.equal(state.calls.filter(x=>x.path==='/api/account/delete').length,0);
   await page.locator('#deleteWarningCancel').click();
   assert.equal(state.calls.filter(x=>x.path==='/api/account/delete').length,0);
   assert.equal(await page.evaluate(()=>localStorage.getItem('yeobaek.draft.v1:fake%40example.test:doc:tab')),'synthetic');
   await page.locator('#deleteAccountSubmit').click();
   await page.locator('#deleteWarningDialog').waitFor({state:'visible'});
   await page.locator('#deleteWarningConfirm').click();
   await page.waitForFunction(()=>!localStorage.getItem('yeobaek.draft.v1:fake%40example.test:doc:tab'));
   assert.equal(state.calls.at(-1).path,'/api/account/delete');
   assert.equal(state.calls.at(-1).csrf,'new-csrf');
   assert.deepEqual(state.errors,[]);await context.close();console.log('PASS: password change and account deletion web screens');
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
