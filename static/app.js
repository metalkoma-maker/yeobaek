const $=id=>document.getElementById(id);
let csrf='',docs=[],current=null,dirty=false,timer=null,saving=false,conflict=null,register=false,composing=false;
const mobileLayout=window.matchMedia('(max-width:720px)');
const modifiedFormat=new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
function modifiedDate(value){const date=new Date(Number(value)*1000);return value!=null&&Number.isFinite(date.getTime())?'최근 수정 '+modifiedFormat.format(date):'최근 수정일 없음';}
function showEditor(){ $('workspace').classList.remove('view-list');$('sidebar').classList.remove('open'); }
async function showList(){if(dirty&&!await save())return;$('workspace').classList.add('view-list');$('sidebar').classList.remove('open');$('closeList').hidden=!current;try{docs=await api('/manuscripts');list();}catch(e){showEditor();notice(e.message);}}
const count=s=>Array.from(s.replace(/\s/gu,'')).length;
async function api(path,method='GET',data){const r=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:data===undefined?undefined:JSON.stringify(data)});const value=await r.json();if(!r.ok){const e=Error(value.error||'요청에 실패했습니다.');e.status=r.status;e.value=value;throw e;}return value;}
function stats(){if(!current)return;$('total').textContent=count($('body').value).toLocaleString();let n=current.today+count($('body').value)-current.total;$('today').textContent=(n>0?'+':'')+n.toLocaleString();}
function list(){ $('documents').replaceChildren();for(const d of docs){const b=document.createElement('button');b.className=current?.id===d.id?'active':'';const t=document.createElement('b');t.textContent=d.title||'제목 없는 원고';const s=document.createElement('small');s.textContent=d.total.toLocaleString()+'자';const date=document.createElement('small');date.className='modifiedDate';date.textContent=modifiedDate(d.updated);b.append(t,s,date);b.onclick=()=>openDoc(d.id);$('documents').append(b);}}
function render(d,navigate=false){recoveryReview=false;$('retry').textContent='다시 저장';$('historyButton').disabled=false;current=d;dirty=false;conflict=null;$('title').value=d.title;$('body').value=d.body;$('empty').hidden=true;$('editor').hidden=false;$('download').disabled=false;$('notice').hidden=true;$('saveStatus').textContent='저장됨';stats();list();$('closeList').hidden=false;if(navigate)showEditor();}
async function openDoc(id){if(saving)return;if(dirty&&!await save())return;try{const epoch=editEpoch;const d=await api('/manuscripts/'+id);if(dirty||saving||epoch!==editEpoch)return;render(d,true);}catch(e){notice(e.message);}}
function notice(message,isConflict=false){$('noticeText').textContent=message;$('notice').hidden=false;$('useServer').hidden=!isConflict;$('retry').hidden=isConflict;}
async function save(manual=false){if(recoveryReview&&!manual)return false;clearTimeout(timer);if(!dirty)return true;if(saving)return false;if(conflict)return false;saving=true;const id=current.id,title=$('title').value,body=$('body').value;$('saveStatus').textContent='저장 중…';try{const d=await api('/manuscripts/'+id,'PUT',{title,body,version:current.version});clearSavedDraft(id,title,body);recoveryReview=false;current=d;docs=docs.map(x=>x.id===id?d:x);dirty=$('title').value!==title||$('body').value!==body;if(dirty)persistDraft();stats();list();$('notice').hidden=true;$('saveStatus').textContent=dirty?'저장 대기':'저장됨';return !dirty;}catch(e){$('saveStatus').textContent='저장되지 않음';if(e.status===409){conflict=e.value.current;notice('다른 기기에서 원고가 수정되었습니다. 현재 입력은 유지됩니다. 내 원고를 내려받은 뒤 서버 원고를 열어 내용을 비교해 주세요.',true);}else{notice(e.message+' 입력한 내용은 이 화면에 유지됩니다. 다시 저장하거나 내려받아 주세요.');}return false;}finally{saving=false;if(dirty&&!conflict&&!recoveryReview&&$('notice').hidden)timer=setTimeout(save,700);}}
function edit(){editEpoch++;dirty=true;persistDraft();stats();$('saveStatus').textContent=recoveryReview?'불러온 내용 확인 중 · 서버 저장 전':'저장 대기';clearTimeout(timer);if(!composing&&!recoveryReview)timer=setTimeout(save,700);}
for(const id of ['title','body']){$(id).addEventListener('input',edit);$(id).addEventListener('compositionstart',()=>{composing=true;clearTimeout(timer);});$(id).addEventListener('compositionend',()=>{composing=false;edit();});}
function download(){if(!current)return;const blob=new Blob([$('title').value+'\n\n'+$('body').value],{type:'text/plain;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=($('title').value||'원고').replace(/[\\/:*?"<>|]/g,'_')+'.txt';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
async function newDoc(){if(saving)return;if(dirty&&!await save())return;try{const d=await api('/manuscripts','POST',{});docs.unshift(d);if(dirty||saving){list();return;}render(d,true);$('title').focus();}catch(e){notice(e.message);}}
async function enter(user){draftEmail=user.email;refreshDraftCount();csrf=user.csrf;$('adminLink').hidden=!user.is_admin;$('accountEmail').textContent=user.email;docs=await api('/manuscripts');$('auth').hidden=true;$('workspace').hidden=false;$('download').disabled=true;$('workspace').classList.add('view-list');$('closeList').hidden=true;list();if(docs.length&&!mobileLayout.matches)render(docs[0]);}
$('authForm').onsubmit=async e=>{e.preventDefault();$('authError').textContent='';$('submitAuth').disabled=true;try{await enter(await api(register?'/register':'/login','POST',{email:$('email').value,password:$('password').value}));$('password').value='';}catch(err){$('authError').textContent=err.message;}finally{$('submitAuth').disabled=false;}};
$('toggleAuth').onclick=()=>{register=!register;$('submitAuth').textContent=register?'가입하고 시작하기':'로그인';$('toggleAuth').textContent=register?'이미 계정이 있나요? 로그인':'처음 오셨나요? 가입하기';$('password').autocomplete=register?'new-password':'current-password';};
$('logout').onclick=async()=>{if(dirty&&!await save())return;try{await api('/logout','POST',{});location.reload();}catch(e){notice(e.message);}};
$('newDoc').onclick=$('firstDoc').onclick=newDoc;$('download').onclick=$('backup').onclick=download;$('retry').onclick=()=>save(true);$('useServer').onclick=()=>{persistDraft();if(confirm('서버 원고를 열면 현재 화면의 수정 내용이 교체됩니다. 필요한 내용은 내려받았나요?')){const d=conflict;docs=docs.map(x=>x.id===d.id?d:x);render(d);}};
$('openList').onclick=showList;$('closeList').onclick=showEditor;
window.addEventListener('pagehide',()=>{if(dirty)persistDraft();});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden'&&dirty&&!composing)save();});
let refreshing=false;
setInterval(async()=>{
 if(dirty||saving||document.hidden||refreshing)return;
 refreshing=true;
 try{
  if(mobileLayout.matches&&$('workspace').classList.contains('view-list')){
   const latest=await api('/manuscripts');if(!dirty&&!saving){docs=latest;list();}
  }else if(current){
   const id=current.id,d=await api('/manuscripts/'+id);
   if(!dirty&&!saving&&current?.id===id&&(d.version!==current.version||d.day!==current.day)){
    docs=docs.map(x=>x.id===id?d:x);render(d);
   }
  }
 }catch{}finally{refreshing=false;}
},10000);
api('/me').then(enter).catch(e=>{if(e.status!==401)$('authError').textContent='서버에 연결하지 못했습니다. 잠시 후 새로고침해 주세요.';});
if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});

let draftEmail='',editEpoch=0,recoveredDraft=null,recoveryReview=false;const dismissedDrafts=new Set();
function draftData(){return current?{id:current.id,title:$('title').value,body:$('body').value,version:current.version,time:Date.now()}:null;}
function persistDraft(){if(!dirty||!current||!draftEmail)return;try{YeobaekDrafts.put(draftEmail,draftData());refreshDraftCount();}catch{$('saveStatus').textContent='기기 임시 저장 실패';notice('이 기기에 임시 저장하지 못했습니다. 서버 저장 상태를 확인하고 TXT를 내려받아 주세요.');}}
function availableDrafts(){return YeobaekDrafts.list(draftEmail).filter(item=>!YeobaekDrafts.isOwn(item)&&!dismissedDrafts.has(item.raw+item.key));}
function refreshDraftCount(){try{const n=availableDrafts().length;$('draftsCount').textContent=n>1?'('+n+')':'';$('recoveryBanner').hidden=!n;}catch{$('recoveryBanner').hidden=true;}}

function clearSavedDraft(id,title,body){try{YeobaekDrafts.clearOwn(draftEmail,id,title,body);if(recoveredDraft&&recoveredDraft.data.id===id){YeobaekDrafts.removeUnchanged(recoveredDraft);recoveredDraft=null;}refreshDraftCount();}catch{}}
function safetyDialog(heading,help){$('safetyHeading').textContent=heading;$('safetyHelp').textContent=help;$('safetyItems').replaceChildren();if(!$('safetyDialog').open)$('safetyDialog').showModal();}
$('safetyClose').onclick=()=> $('safetyDialog').close();
$('draftsButton').onclick=()=>{safetyDialog('저장되지 않은 글 확인','A와 B를 비교해 선택할 수 있습니다. B를 불러오기만 해서는 서버에 저장되지 않습니다.');try{const items=availableDrafts();if(!items.length){$('safetyHelp').textContent='복구할 글이 없습니다.';refreshDraftCount();return;}for(const item of items){const b=document.createElement('button');b.textContent=(item.data.title||'제목 없는 원고')+' · '+new Date(item.data.time).toLocaleString('ko-KR');b.onclick=()=>compareDraft(item);$('safetyItems').append(b);}if(items.length===1)compareDraft(items[0]);}catch{$('safetyHelp').textContent='기기 보관본에 접근하지 못했습니다.';}};
async function compareDraft(item){
 if(saving)return;if(dirty&&!await save())return;
 const epoch=editEpoch;try{const a=await api('/manuscripts/'+item.data.id);if(dirty||saving||epoch!==editEpoch)return;
 safetyDialog('저장되지 않은 글 확인','B 불러오기는 작성 화면에만 반영됩니다. 확인 후 이 내용으로 저장을 눌러야 서버에 반영됩니다.');
 YeobaekRecoveryView.render($('safetyItems'),a,item.data,()=>{
  if(dirty||saving||epoch!==editEpoch)return;
  render(a,true);dismissedDrafts.add(item.raw+item.key);refreshDraftCount();$('safetyDialog').close();
 },()=>{
  if(dirty||saving||epoch!==editEpoch)return;
  render(a,true);$('title').value=item.data.title;$('body').value=item.data.body;recoveredDraft=item;dismissedDrafts.add(item.raw+item.key);recoveryReview=true;dirty=true;editEpoch++;persistDraft();stats();
  $('saveStatus').textContent='불러온 내용 확인 중 · 서버 저장 전';notice('B를 불러왔습니다. 내용을 확인한 뒤 이 내용으로 저장을 눌러 주세요.');$('retry').textContent='이 내용으로 저장';$('safetyDialog').close();
 });
 }catch(e){$('safetyHelp').textContent=e.message;}
}
$('historyButton').onclick=async()=>{if(!current||saving)return;if(dirty&&!await save())return;const id=current.id;safetyDialog('수정 이력','최근 변경 전 원고 50개를 보관합니다. 업데이트 이전의 이력은 없습니다. 복원 전 현재 원고도 이력에 남습니다.');try{const rows=await api('/manuscripts/'+id+'/history');if(!rows.length)$('safetyHelp').textContent='아직 수정 이력이 없습니다.';for(const row of rows){const b=document.createElement('button');b.textContent=new Date(row.updated*1000).toLocaleString('ko-KR')+' · '+row.characters.toLocaleString()+'자 · '+row.title;b.onclick=async()=>{try{const old=await api('/manuscripts/'+id+'/history/'+row.version);if(!confirm('이 버전으로 복원할까요?\n\n'+old.body.slice(0,300)))return;if(current?.id!==id||dirty||saving)return;$('title').value=old.title;$('body').value=old.body;dirty=true;editEpoch++;persistDraft();stats();$('safetyDialog').close();await save();}catch(e){$('safetyHelp').textContent=e.message;}};$('safetyItems').append(b);}}catch(e){$('safetyHelp').textContent=e.message;}};
