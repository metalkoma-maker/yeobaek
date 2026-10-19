const $=id=>document.getElementById(id);
let csrf='',docs=[],current=null,dirty=false,timer=null,saving=false,conflict=null,register=false,composing=false;
const mobileLayout=window.matchMedia('(max-width:720px)');
const modifiedFormat=new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
function modifiedDate(value){const date=new Date(Number(value)*1000);return value!=null&&Number.isFinite(date.getTime())?'최근 수정 '+modifiedFormat.format(date):'최근 수정일 없음';}
function showEditor(){ $('workspace').classList.remove('view-list');$('sidebar').classList.remove('open'); }
async function showList(){if(dirty&&!await save())return;$('workspace').classList.add('view-list');$('sidebar').classList.remove('open');$('closeList').hidden=!current;try{await refreshDocuments();}catch(e){showEditor();notice(e.message);}}
const count=s=>Array.from(s.replace(/[\r\n\u2028\u2029]/gu,'')).length;
const countWithoutSpaces=s=>Array.from(s.replace(/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/gu,'')).length;
async function api(path,method='GET',data){const r=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:data===undefined?undefined:JSON.stringify(data)});const value=await r.json();if(!r.ok){const e=Error(value.error||'요청에 실패했습니다.');e.status=r.status;e.value=value;throw e;}return value;}
let statsFrame=null;
function textIfChanged(id,value){const node=$(id);if(node.textContent!==value)node.textContent=value;}
function stats(){
 if(statsFrame!==null){cancelAnimationFrame(statsFrame);statsFrame=null;}
 if(!current)return;
 const total=count($('body').value);
 const oldRule=current.today_count_rule==='without_spaces';
 const n=current.today+(oldRule?countWithoutSpaces($('body').value)-countWithoutSpaces(current.body):total-current.total);
 textIfChanged('total',total.toLocaleString());textIfChanged('today',(n>0?'+':'')+n.toLocaleString());
 textIfChanged('countRule',oldRule?'전체: 공백 포함 · 오늘: 공백 제외 (내일부터 통일)':'띄어쓰기 포함 · 줄바꿈 제외 · 한국시간 기준');
}
// Multiple input events before a paint need only one latest-value count.
function scheduleStats(){if(statsFrame===null)statsFrame=requestAnimationFrame(()=>{statsFrame=null;stats();});}
let editHistory=null,historyDoc=null,bodySizeFrame=null;
function editingState(field=document.activeElement?.id==='title'?'title':'body'){
 const node=$(field);return {title:$('title').value,body:$('body').value,field,start:node.selectionStart,end:node.selectionEnd,direction:node.selectionDirection,scroll:$('editor').scrollTop};
}
function historyButtons(){if($('undoEdit'))$('undoEdit').disabled=!editHistory||composing||!editHistory.undoStack.length;if($('redoEdit'))$('redoEdit').disabled=!editHistory||composing||!editHistory.redoStack.length;}
function syncEditingHistory(id){
 if(typeof YeobaekEditHistory!=='function'){editHistory=null;historyButtons();resizeBody();return;}
 const state=editingState();
 if(historyDoc!==id||!editHistory||editHistory.state.title!==state.title||editHistory.state.body!==state.body){editHistory=new YeobaekEditHistory(state);historyDoc=id;}
 historyButtons();resizeBody();
}
function resizeBody(){
 if(bodySizeFrame!==null){cancelAnimationFrame(bodySizeFrame);bodySizeFrame=null;}
 if(!current||$('editor').hidden)return;
 const body=$('body'),pane=$('editor'),scroll=pane.scrollTop;
 body.style.height='0px';body.style.height=body.scrollHeight+'px';pane.scrollTop=scroll;
}
function scheduleBodySize(){if(bodySizeFrame===null)bodySizeFrame=requestAnimationFrame(()=>{bodySizeFrame=null;resizeBody();});}
function undoEditing(redo=false){
 if(!current||composing||!editHistory)return;
 const state=editHistory.move(redo);if(!state)return;
 if($('title').value!==state.title)$('title').value=state.title;
 if($('body').value!==state.body)$('body').value=state.body;
 const node=$(state.field);node.focus({preventScroll:true});node.setSelectionRange(state.start,state.end,state.direction);
 resizeBody();$('editor').scrollTop=state.scroll;historyButtons();edit();
}
for(const [id,redo] of [['undoEdit',false],['redoEdit',true]]){
 if(!$(id))continue;$(id).addEventListener('mousedown',e=>e.preventDefault());$(id).onclick=()=>undoEditing(redo);
}
window.addEventListener('resize',scheduleBodySize);
$('body').addEventListener('yeobaek-font-change',scheduleBodySize);
let orderVersion=null,orderEpoch=0,orderBusy=false,draggedId=null,ignoreDocClickUntil=0,dragPointerY=null,dragScrollFrame=0;
function orderStatus(message){const node=$('listOrderStatus');if(node)node.textContent=message;}
function arrangeDocs(items,ids){
 const rank=new Map(ids.map((id,i)=>[id,i]));
 return [...items].sort((a,b)=>(rank.has(a.id)?1:0)-(rank.has(b.id)?1:0)||(rank.get(a.id)??0)-(rank.get(b.id)??0));
}
async function fetchListState(){
 const [items,order]=await Promise.all([api('/manuscripts'),api('/manuscript-order').catch(()=>null)]);
 return {items:order?arrangeDocs(items,order.ids):items,version:order?.version??null};
}
function acceptListState(state){
 docs=state.items;orderVersion=state.version;list();
 if(orderVersion===null)orderStatus('원고 순서를 불러오지 못했습니다. 목록을 다시 열어 주세요.');
}
async function refreshDocuments(){
 const epoch=orderEpoch,editing=editEpoch,state=await fetchListState();
 if(epoch!==orderEpoch||editing!==editEpoch||dirty||saving||composing||recoveryReview||orderBusy||draggedId)return;
 acceptListState(state);
}
function clearDropTarget(){for(const node of $('documents').children)node.classList.remove('dropBefore','dropAfter');}
function dropSlotAt(y){
 const rows=[...$('documents').children];
 for(let i=0;i<rows.length;i++)if(y<rows[i].getBoundingClientRect().top+rows[i].offsetHeight/2)return i;
 return rows.length;
}
function showDropSlot(slot){
 clearDropTarget();const rows=[...$('documents').children],from=docs.findIndex(d=>d.id===draggedId);
 if(!rows.length||from<0||slot-(slot>from?1:0)===from)return;
 (rows[slot]||rows[rows.length-1]).classList.add(slot===rows.length?'dropAfter':'dropBefore');
}
function stopDragScroll(){if(dragScrollFrame)cancelAnimationFrame(dragScrollFrame);dragScrollFrame=0;dragPointerY=null;}
function scrollDraggedList(){
 dragScrollFrame=0;if(!draggedId||dragPointerY===null)return;
 const nav=$('documents'),bounds=nav.getBoundingClientRect(),edge=48;
 const amount=dragPointerY<bounds.top+edge?-Math.min(22,Math.max(5,(bounds.top+edge-dragPointerY)/2)):
  dragPointerY>bounds.bottom-edge?Math.min(22,Math.max(5,(dragPointerY-(bounds.bottom-edge))/2)):0;
 if(amount){const before=nav.scrollTop;nav.scrollTop+=amount;if(nav.scrollTop!==before)showDropSlot(dropSlotAt(dragPointerY));}
 dragScrollFrame=requestAnimationFrame(scrollDraggedList);
}
function dropDocumentAt(source,slot){
 const ids=docs.map(d=>d.id),from=ids.indexOf(source);if(from<0)return;
 ids.splice(from,1);ids.splice(slot-(slot>from?1:0),0,source);return storeOrder(ids);
}
$('sidebar').addEventListener('dragover',e=>{
 if(!draggedId||orderBusy)return;
 e.preventDefault();e.dataTransfer.dropEffect='move';dragPointerY=e.clientY;
 showDropSlot(dropSlotAt(e.clientY));
 if(!dragScrollFrame)dragScrollFrame=requestAnimationFrame(scrollDraggedList);
});
$('sidebar').addEventListener('drop',e=>{
 if(!draggedId||orderBusy)return;
 e.preventDefault();const source=draggedId,slot=dropSlotAt(e.clientY);
 draggedId=null;ignoreDocClickUntil=performance.now()+250;stopDragScroll();clearDropTarget();void dropDocumentAt(source,slot);
});
$('sidebar').addEventListener('dragleave',e=>{
 if(!e.currentTarget.contains(e.relatedTarget)){stopDragScroll();clearDropTarget();}
});
async function storeOrder(ids){
 if(orderBusy||orderVersion===null||ids.every((id,i)=>docs[i]?.id===id))return;
 const previous=docs.map(d=>d.id),version=orderVersion;
 orderBusy=true;orderEpoch++;docs=arrangeDocs(docs,ids);list();orderStatus('원고 순서 저장 중…');
 try{
  const result=await api('/manuscript-order','PUT',{ids,version});
  docs=arrangeDocs(docs,result.ids);orderVersion=result.version;orderStatus('');
 }catch(e){
  docs=arrangeDocs(docs,previous);
  if(e.status===409){
   try{acceptListState(await fetchListState());}catch{}
   orderStatus('다른 기기에서 목록이 바뀌었습니다. 확인 후 다시 옮겨 주세요.');
  }else orderStatus('원고 순서를 저장하지 못했습니다. 다시 옮겨 주세요.');
 }finally{orderBusy=false;list();}
}
function moveDocument(source,target,after){
 const ids=docs.map(d=>d.id);if(source===target||!ids.includes(source)||!ids.includes(target))return;
 ids.splice(ids.indexOf(source),1);ids.splice(ids.indexOf(target)+(after?1:0),0,source);return storeOrder(ids);
}
function list(){
 if(draggedId)return; // Do not replace the native drag source during autosave.
 $('documents').replaceChildren();
 for(const d of docs){
  const row=document.createElement('div');row.className='documentRow';
  const b=document.createElement('button');b.dataset.id=d.id;b.className='documentCard'+(current?.id===d.id?' active':'');
  b.draggable=!orderBusy&&orderVersion!==null;b.title='드래그하여 순서 변경 · Alt+↑/↓';
  const handle=document.createElement('span');handle.className='orderHandle';handle.textContent='⠿';handle.setAttribute('aria-hidden','true');
  const t=document.createElement('b');t.textContent=d.title||'제목 없는 원고';
  const s=document.createElement('small');s.textContent=d.total.toLocaleString()+'자';
  const date=document.createElement('small');date.className='modifiedDate';date.textContent=modifiedDate(d.updated);
  b.append(handle,t,s,date);b.onclick=()=>{if(!draggedId&&performance.now()>ignoreDocClickUntil)openDoc(d.id);};
  b.addEventListener('dragstart',e=>{
   if(orderBusy||orderVersion===null||composing){e.preventDefault();return;}
   draggedId=d.id;b.classList.add('dragging');e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',d.id);
  });
  b.addEventListener('dragend',()=>{draggedId=null;ignoreDocClickUntil=performance.now()+250;stopDragScroll();clearDropTarget();list();});
  b.addEventListener('keydown',async e=>{
   if(!e.altKey||!['ArrowUp','ArrowDown'].includes(e.key)||orderBusy||orderVersion===null)return;
   const index=docs.findIndex(x=>x.id===d.id),target=docs[index+(e.key==='ArrowUp'?-1:1)];if(!target)return;
   e.preventDefault();await moveDocument(d.id,target.id,e.key==='ArrowDown');
   [...$('documents').children].find(node=>node.querySelector('.documentCard')?.dataset.id===d.id)?.querySelector('.documentCard')?.focus();
  });
  const more=document.createElement('button');more.type='button';more.className='documentMore';more.textContent='⋯';
  more.setAttribute('aria-label',(d.title||'제목 없는 원고')+'을 다른 이름으로 저장');
  more.title='다른 이름으로 저장';
  more.onclick=()=>void openCopyDialog(d.id);
  row.append(b,more);$('documents').append(row);
 }
}
function render(d,navigate=false){recoveryReview=false;$('retry').textContent='다시 저장';$('historyButton').disabled=false;current=d;dirty=false;conflict=null;if($('title').value!==d.title)$('title').value=d.title;if($('body').value!==d.body)$('body').value=d.body;$('empty').hidden=true;$('editor').hidden=false;$('download').disabled=false;$('notice').hidden=true;$('saveStatus').textContent='저장됨';stats();list();$('closeList').hidden=false;if(navigate)showEditor();syncEditingHistory(d.id);}
async function openDoc(id){if(saving)return;if(dirty&&!await save())return;try{const epoch=editEpoch;const d=await api('/manuscripts/'+id);if(dirty||saving||epoch!==editEpoch)return;render(d,true);}catch(e){notice(e.message);}}
function notice(message,isConflict=false){$('noticeText').textContent=message;$('notice').hidden=false;$('useServer').hidden=!isConflict;$('retry').hidden=isConflict;}
async function save(manual=false){if(recoveryReview&&!manual)return false;clearTimeout(timer);if(!dirty)return true;if(saving)return false;if(conflict)return false;saving=true;const id=current.id,title=$('title').value,body=$('body').value;$('saveStatus').textContent='저장 중…';try{const d=await api('/manuscripts/'+id,'PUT',{title,body,version:current.version});clearSavedDraft(id,title,body);recoveryReview=false;current=d;docs=docs.map(x=>x.id===id?d:x);dirty=$('title').value!==title||$('body').value!==body;if(dirty){persistDraft();scheduleStats();}else{stats();list();}$('notice').hidden=true;$('saveStatus').textContent=dirty?'저장 대기':'저장됨';return !dirty;}catch(e){$('saveStatus').textContent='저장되지 않음';if(e.status===409){conflict=e.value.current;notice('다른 기기에서 원고가 수정되었습니다. 현재 입력은 유지됩니다. 내 원고를 내려받은 뒤 서버 원고를 열어 내용을 비교해 주세요.',true);}else{notice(e.message+' 입력한 내용은 이 화면에 유지됩니다. 다시 저장하거나 내려받아 주세요.');}return false;}finally{saving=false;if(dirty&&!conflict&&!recoveryReview&&$('notice').hidden)timer=setTimeout(save,700);}}
function edit(){editEpoch++;dirty=true;persistDraft();scheduleStats();scheduleBodySize();textIfChanged('saveStatus',recoveryReview?'불러온 내용 확인 중 · 서버 저장 전':'저장 대기');clearTimeout(timer);if(!composing&&!recoveryReview)timer=setTimeout(save,700);}
for(const id of ['title','body']){
 const node=$(id);
 node.addEventListener('beforeinput',e=>{
  if(editHistory&&(e.inputType==='historyUndo'||e.inputType==='historyRedo')){e.preventDefault();undoEditing(e.inputType==='historyRedo');return;}
  if(editHistory)editHistory.before(editingState(id),e.inputType);
 });
 node.addEventListener('input',e=>{if(editHistory)editHistory.input(editingState(id),e.inputType);historyButtons();edit();});
 node.addEventListener('compositionstart',()=>{composing=true;clearTimeout(timer);if(editHistory)editHistory.beginComposition(editingState(id));historyButtons();});
 node.addEventListener('compositionend',()=>{composing=false;if(editHistory)editHistory.endComposition(editingState(id));historyButtons();edit();});
}
document.addEventListener('keydown',e=>{
 if(!current||!editHistory||$('workspace').hidden||$('safetyDialog').open||$('historyDialog').open||$('copyDialog').open||composing||e.isComposing||e.keyCode===229||e.altKey||!(e.ctrlKey||e.metaKey))return;
 if(e.target.matches('input,textarea')&&!['title','body'].includes(e.target.id))return;
 const key=e.key.toLowerCase();if(key==='z'||(key==='y'&&!e.shiftKey)){e.preventDefault();undoEditing(key==='y'||e.shiftKey);}
});
const downloadFormat=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
function downloadedAt(date){
 const parts=Object.fromEntries(downloadFormat.formatToParts(date).map(p=>[p.type,p.value]));
 return parts.year+'-'+parts.month+'-'+parts.day+' '+parts.hour+':'+parts.minute+':'+parts.second+' (한국시간)';
}
function download(){if(!current)return;const stamp='내려받은 시각: '+downloadedAt(new Date());const blob=new Blob([stamp+'\n\n'+$('title').value+'\n\n'+$('body').value],{type:'text/plain;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=($('title').value||'원고').replace(/[\\/:*?"<>|]/g,'_')+'.txt';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
async function newDoc(){if(saving)return;if(dirty&&!await save())return;try{const d=await api('/manuscripts','POST',{});orderEpoch++;docs.unshift(d);if(dirty||saving){list();return;}render(d,true);$('title').focus();}catch(e){notice(e.message);}}
function suggestedCopyTitle(source){
 const base=(source.title.trim()||'제목 없는 원고').replace(/ · [2-9][0-9]*교$/u,'');
 let number=1;
 for(const doc of docs){
  const title=doc.title,match=/ · ([2-9][0-9]*)교$/u.exec(title);
  if(match&&title.slice(0,match.index)===base.slice(0,200-match[0].length))number=Math.max(number,Number(match[1]));
 }
 const suffix=' · '+Math.max(2,number+1)+'교';return base.slice(0,200-suffix.length)+suffix;
}
let copySource=null,copyBusy=false;
async function openCopyDialog(id){
 if(copyBusy||saving||orderBusy||draggedId||$('copyDialog').open)return;
 if(dirty&&!await save())return;
 try{
  const source=await api('/manuscripts/'+id);
  if(dirty||saving)return;
  copySource=source;$('copyTitle').value=suggestedCopyTitle(source);$('copyMessage').textContent='원본은 그대로 남고 사본은 별도 원고가 됩니다.';
  $('copyDialog').showModal();$('copyTitle').focus();$('copyTitle').select();
 }catch(e){notice(e.message);}
}
$('copyCancel').onclick=()=>{if(!copyBusy)$('copyDialog').close();};
$('copyDialog').addEventListener('cancel',e=>{if(copyBusy)e.preventDefault();});
$('copyDialog').addEventListener('close',()=>{copySource=null;});
$('copyConfirm').onclick=async()=>{
 if(copyBusy||!copySource)return;
 const title=$('copyTitle').value.trim();if(!title){$('copyMessage').textContent='새 원고 제목을 입력해 주세요.';return;}
 copyBusy=true;$('copyConfirm').disabled=true;$('copyCancel').disabled=true;
 try{
  const created=await api('/manuscripts/'+copySource.id+'/copy','POST',{version:copySource.version,title});
  orderEpoch++;
  try{acceptListState(await fetchListState());}catch{docs.unshift(created);list();}
  render(created,true);$('copyDialog').close();$('title').focus();
 }catch(e){$('copyMessage').textContent=e.status===409?'다른 기기에서 원고가 수정됐습니다. 창을 닫고 다시 확인해 주세요.':e.message;}
 finally{copyBusy=false;$('copyConfirm').disabled=false;$('copyCancel').disabled=false;}
};
async function enter(user){draftEmail=user.email;refreshDraftCount();csrf=user.csrf;$('adminLink').hidden=!user.is_admin;$('accountEmail').textContent=user.email;await refreshDocuments();$('auth').hidden=true;$('workspace').hidden=false;$('download').disabled=true;$('workspace').classList.add('view-list');$('closeList').hidden=true;list();if(docs.length&&!mobileLayout.matches)render(docs[0]);}
$('authForm').onsubmit=async e=>{e.preventDefault();$('authError').textContent='';$('submitAuth').disabled=true;try{await enter(await api(register?'/register':'/login','POST',{email:$('email').value,password:$('password').value}));$('password').value='';}catch(err){$('authError').textContent=err.message;}finally{$('submitAuth').disabled=false;}};
$('toggleAuth').onclick=()=>{register=!register;$('submitAuth').textContent=register?'가입하고 시작하기':'로그인';$('toggleAuth').textContent=register?'이미 계정이 있나요? 로그인':'처음 오셨나요? 가입하기';$('password').autocomplete=register?'new-password':'current-password';};
$('logout').onclick=async()=>{if(dirty&&!await save())return;try{await api('/logout','POST',{});location.reload();}catch(e){notice(e.message);}};
$('newDoc').onclick=$('firstDoc').onclick=newDoc;$('download').onclick=$('backup').onclick=download;$('retry').onclick=()=>save(true);$('useServer').onclick=()=>{persistDraft();if(confirm('서버 원고를 열면 현재 화면의 수정 내용이 교체됩니다. 필요한 내용은 내려받았나요?')){const d=conflict;docs=docs.map(x=>x.id===d.id?d:x);render(d);}};
$('openList').onclick=showList;$('closeList').onclick=showEditor;
window.addEventListener('pagehide',()=>{if(dirty)persistDraft();});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden'&&dirty&&!composing)save();});
let refreshing=false;
setInterval(async()=>{
 if(dirty||saving||composing||recoveryReview||document.hidden||refreshing||orderBusy||draggedId||$('historyDialog').open||$('copyDialog').open)return;
 const epoch=editEpoch;
 refreshing=true;
 try{
  if(mobileLayout.matches&&$('workspace').classList.contains('view-list')){
   const sequence=orderEpoch,latest=await fetchListState();if(!dirty&&!saving&&!composing&&!orderBusy&&!draggedId&&sequence===orderEpoch&&epoch===editEpoch)acceptListState(latest);
  }else if(current){
   const id=current.id,d=await api('/manuscripts/'+id);
   if(!dirty&&!saving&&!composing&&epoch===editEpoch&&current?.id===id&&(d.version!==current.version||d.day!==current.day)){
    docs=docs.map(x=>x.id===id?d:x);render(d);
   }
   if(!dirty&&!saving&&!composing&&!orderBusy&&!draggedId&&epoch===editEpoch)await refreshDocuments();
  }
 }catch{}finally{refreshing=false;}
},10000);
api('/me').then(enter).catch(e=>{if(e.status!==401)$('authError').textContent='서버에 연결하지 못했습니다. 잠시 후 새로고침해 주세요.';});
if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});

let draftEmail='',editEpoch=0,recoveredDraft=null,recoveryReview=false;const dismissedDrafts=new Set();
function draftData(){return current?{id:current.id,title:$('title').value,body:$('body').value,version:current.version,time:Date.now()}:null;}
function persistDraft(){if(!dirty||!current||!draftEmail)return;try{YeobaekDrafts.put(draftEmail,draftData());}catch{$('saveStatus').textContent='기기 임시 저장 실패';notice('이 기기에 임시 저장하지 못했습니다. 서버 저장 상태를 확인하고 TXT를 내려받아 주세요.');}}
function availableDrafts(){return YeobaekDrafts.list(draftEmail,true).filter(item=>!YeobaekDrafts.isOwn(item)&&!dismissedDrafts.has(item.raw+item.key));}
// Recovery discovery is unrelated to saving this tab's current input. Scan on
// entry, successful save, cross-tab storage changes, focus and explicit review.
let draftCountTimer=null;
function scheduleDraftCount(){if(draftCountTimer===null)draftCountTimer=setTimeout(()=>{draftCountTimer=null;refreshDraftCount();},150);}
window.addEventListener('storage',e=>{if(e.key===null||e.key.startsWith('yeobaek.draft.v1:'))scheduleDraftCount();});
window.addEventListener('focus',scheduleDraftCount);
function refreshDraftCount(){try{const n=availableDrafts().length;$('draftsCount').textContent=n>1?'('+n+')':'';$('recoveryBanner').hidden=!n;}catch{$('recoveryBanner').hidden=true;}}

function clearSavedDraft(id,title,body){try{YeobaekDrafts.clearOwn(draftEmail,id,title,body);if(recoveredDraft&&recoveredDraft.data.id===id){YeobaekDrafts.removeUnchanged(recoveredDraft);recoveredDraft=null;}refreshDraftCount();}catch{}}
function safetyDialog(heading,help){$('safetyHeading').textContent=heading;$('safetyHelp').textContent=help;$('safetyItems').replaceChildren();if(!$('safetyDialog').open)$('safetyDialog').showModal();}
$('safetyClose').onclick=()=> $('safetyDialog').close();
$('draftsButton').onclick=()=>{refreshDraftCount();safetyDialog('저장되지 않은 글 확인','A와 B를 비교해 선택할 수 있습니다. B를 불러오기만 해서는 서버에 저장되지 않습니다.');try{const items=availableDrafts();if(!items.length){$('safetyHelp').textContent='복구할 글이 없습니다.';refreshDraftCount();return;}for(const item of items){const b=document.createElement('button');b.textContent=(item.data.title||'제목 없는 원고')+' · '+new Date(item.data.time).toLocaleString('ko-KR');b.onclick=()=>compareDraft(item);$('safetyItems').append(b);}if(items.length===1)compareDraft(items[0]);}catch{$('safetyHelp').textContent='기기 보관본에 접근하지 못했습니다.';}};
async function compareDraft(item){
 if(saving)return;if(dirty&&!await save())return;
 const epoch=editEpoch;try{const a=await api('/manuscripts/'+item.data.id);if(dirty||saving||epoch!==editEpoch)return;
 safetyDialog('저장되지 않은 글 확인','B 불러오기는 작성 화면에만 반영됩니다. 확인 후 이 내용으로 저장을 눌러야 서버에 반영됩니다.');
 YeobaekRecoveryView.render($('safetyItems'),a,item.data,()=>{
  if(dirty||saving||epoch!==editEpoch)return;
  render(a,true);dismissedDrafts.add(item.raw+item.key);refreshDraftCount();$('safetyDialog').close();
 },()=>{
  if(dirty||saving||epoch!==editEpoch)return;
  render(a,true);$('title').value=item.data.title;$('body').value=item.data.body;recoveredDraft=item;dismissedDrafts.add(item.raw+item.key);recoveryReview=true;syncEditingHistory(a.id);dirty=true;editEpoch++;persistDraft();stats();
  $('saveStatus').textContent='불러온 내용 확인 중 · 서버 저장 전';notice('B를 불러왔습니다. 내용을 확인한 뒤 이 내용으로 저장을 눌러 주세요.');$('retry').textContent='이 내용으로 저장';$('safetyDialog').close();
 });
 }catch(e){$('safetyHelp').textContent=e.message;}
}
const historyDateFormat=new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'});
const historyTimeFormat=new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
let historyId=null,historyBaseVersion=null,historySelected=null,historyEpoch=0,historySelectionEpoch=0,historyBusy=false;
function historyMessage(message){$('historyMessage').textContent=message;}
function historyActive(id,epoch){return $('historyDialog').open&&historyId===id&&historyEpoch===epoch;}
function historyRows(target,rows,source){
 target.replaceChildren();let previousDay='';
 for(const row of rows){
  const date=historyDateFormat.format(new Date(row.updated*1000));
  if(date!==previousDay){const heading=document.createElement('p');heading.className='historyDate';heading.textContent=date;target.append(heading);previousDay=date;}
  const button=document.createElement('button');button.type='button';button.className='historyRow';button.dataset.version=String(row.version);button.dataset.source=source;
  button.setAttribute('aria-pressed',String(historySelected?.version===row.version&&historySelected?.source===source));
  const title=document.createElement('b');title.textContent=row.label||row.title||'제목 없는 원고';
  const detail=document.createElement('small');detail.textContent=historyTimeFormat.format(new Date(row.updated*1000))+' · '+Number(row.characters).toLocaleString()+'자'+(row.kind==='manual'?' · 중요 보관':row.kind==='before_restore'?' · 복원 전':'');
  button.append(title,detail);button.onclick=()=>void selectHistory(row,source);target.append(button);
 }
}
async function refreshHistory(preferred){
 const id=historyId,epoch=historyEpoch;
 const [points,recent]=await Promise.all([api('/manuscripts/'+id+'/checkpoints'),api('/manuscripts/'+id+'/history')]);
 if(!historyActive(id,epoch))return;
 const saved=new Set(points.map(row=>row.version)),other=recent.filter(row=>!saved.has(row.version));
 historyRows($('checkpointList'),points,'checkpoint');historyRows($('recentHistoryList'),other,'recent');
 $('recentHistoryCount').textContent='('+other.length+'개)';
 if(!points.length){const p=document.createElement('p');p.className='historyDate';p.textContent='아직 복원 지점이 없습니다. 현재 글을 중요 버전으로 보관할 수 있습니다.';$('checkpointList').append(p);}
 const found=preferred&&(points.find(row=>row.version===preferred.version)||other.find(row=>row.version===preferred.version));
 if(found)await selectHistory(found,saved.has(found.version)?'checkpoint':'recent');
}
async function selectHistory(row,source){
 const id=historyId,epoch=historyEpoch,selection=++historySelectionEpoch;
 try{
  const item=await api('/manuscripts/'+id+'/'+(source==='checkpoint'?'checkpoints':'history')+'/'+row.version);
  if(!historyActive(id,epoch)||selection!==historySelectionEpoch)return;
  historySelected={...item,source};
  $('historyOldBody').value=item.body;$('historySelectedMeta').textContent=(row.label||item.title||'제목 없는 원고')+' · '+historyTimeFormat.format(new Date(item.updated*1000))+' · 버전 '+item.version;
  $('pinSelected').disabled=false;$('restoreHistory').disabled=false;
  for(const button of $('historyDialog').querySelectorAll('.historyRow'))button.setAttribute('aria-pressed',String(button.dataset.version===String(row.version)&&button.dataset.source===source));
  historyMessage('선택한 버전과 현재 글을 비교한 뒤 복원할 수 있습니다.');
 }catch(e){if(historyActive(id,epoch))historyMessage(e.message);}
}
async function pinHistory(version,expectedCurrent=false){
 if(historyBusy||!historyId)return;
 const id=historyId,epoch=historyEpoch,label=$('historyLabel').value.trim()||'중요한 버전';
 historyBusy=true;
 try{
  await api('/manuscripts/'+id+'/checkpoints','POST',{version,label,...(expectedCurrent?{expected_current_version:historyBaseVersion}:{})});
  if(!historyActive(id,epoch))return;
  await refreshHistory({version});historyMessage('중요한 버전으로 보관했습니다. 자동 정리에서 제외됩니다.');
 }catch(e){if(historyActive(id,epoch))historyMessage(e.status===409?'다른 기기에서 글이 바뀌었습니다. 이 창을 닫고 다시 열어 주세요.':e.message);}
 finally{historyBusy=false;}
}
$('historyButton').onclick=async()=>{
 if(!current||saving||$('historyDialog').open)return;
 if(dirty&&!await save())return;
 historyId=current.id;historyBaseVersion=current.version;historySelected=null;historyEpoch++;historySelectionEpoch++;
 $('historyOldBody').value='';$('historyCurrentBody').value=$('body').value;
 $('historySelectedMeta').textContent='왼쪽에서 버전을 선택하세요.';$('historyLabel').value='';$('pinSelected').disabled=true;$('restoreHistory').disabled=true;
 $('checkpointList').replaceChildren();$('recentHistoryList').replaceChildren();$('recentHistory').open=false;
 historyMessage('복원 지점을 불러오는 중…');$('historyDialog').showModal();
 try{await refreshHistory();if(!$('checkpointList').children.length&&!$('recentHistoryList').children.length)historyMessage('아직 이전 버전이 없습니다.');else historyMessage('복원 지점이나 최근 자동저장을 선택해 비교하세요.');}
 catch(e){if($('historyDialog').open)historyMessage(e.message);}
};
$('historyClose').onclick=()=>{if(!historyBusy)$('historyDialog').close();};
$('historyDialog').addEventListener('cancel',e=>{if(historyBusy)e.preventDefault();});
$('historyDialog').addEventListener('close',()=>{historyEpoch++;historySelectionEpoch++;historyId=null;historySelected=null;});
$('pinCurrent').onclick=()=>void pinHistory(historyBaseVersion,true);
$('pinSelected').onclick=()=>{if(historySelected)void pinHistory(historySelected.version);};
$('restoreHistory').onclick=async()=>{
 if(historyBusy||!historySelected||!historyId)return;
 const selected=historySelected,id=historyId,epoch=historyEpoch;
 if(!confirm('선택한 버전으로 복원할까요? 현재 글은 “복원 전 글”로 따로 보관됩니다.'))return;
 historyBusy=true;$('restoreHistory').disabled=true;
 try{
  const saved=await api('/manuscripts/'+id+'/restore','POST',{version:historyBaseVersion,source_version:selected.version});
  if(!historyActive(id,epoch))return;
  docs=docs.map(doc=>doc.id===id?saved:doc);render(saved,true);$('historyDialog').close();
 }catch(e){if(historyActive(id,epoch))historyMessage(e.status===409?'다른 기기에서 글이 바뀌었습니다. 복원하지 않았습니다. 창을 닫고 다시 열어 주세요.':e.message);}
 finally{historyBusy=false;if(historyActive(id,epoch))$('restoreHistory').disabled=false;}
};

let recoveryMailMode='id',resetToken=null;
function openRecoveryMail(mode){
 recoveryMailMode=mode;
 $('recoveryMailHeading').textContent=mode==='id'?'아이디 찾기':'비밀번호 찾기';
 $('recoveryMailHelp').textContent=mode==='id'?'로그인 아이디는 가입한 이메일입니다. 주소를 입력하면 가입 여부를 메일로 안내합니다.':'가입한 이메일로 30분 동안 한 번 쓸 수 있는 재설정 링크를 보냅니다.';
 $('recoveryEmail').value=$('email').value;$('recoveryMailMessage').textContent='';
 $('recoveryMailDialog').showModal();$('recoveryEmail').focus();
}
$('recoverId').onclick=()=>openRecoveryMail('id');
$('forgotPassword').onclick=()=>openRecoveryMail('password');
$('recoveryMailClose').onclick=()=>$('recoveryMailDialog').close();
$('recoveryMailForm').onsubmit=async e=>{
 e.preventDefault();const button=$('recoveryMailSubmit');button.disabled=true;
 try{
  const path=recoveryMailMode==='id'?'/account/recover-id':'/password-reset/request';
  const result=await api(path,'POST',{email:$('recoveryEmail').value});
  $('recoveryMailMessage').textContent=result.message;
 }catch(error){$('recoveryMailMessage').textContent=error.message;}
 finally{button.disabled=false;}
};
const resetMatch=/^#reset=([A-Za-z0-9_-]{43})$/.exec(location.hash);
if(resetMatch){
 resetToken=resetMatch[1];history.replaceState(null,'',location.pathname+location.search);
 $('resetDialog').showModal();$('resetPassword').focus();
}
$('resetClose').onclick=()=>$('resetDialog').close();
$('resetForm').onsubmit=async e=>{
 e.preventDefault();const password=$('resetPassword').value,again=$('resetPasswordAgain').value;
 if(password!==again){$('resetMessage').textContent='새 비밀번호가 서로 다릅니다.';return;}
 const button=$('resetSubmit');button.disabled=true;
 try{
  await api('/password-reset/confirm','POST',{token:resetToken,new_password:password});
  resetToken=null;$('resetForm').reset();$('resetMessage').textContent='비밀번호를 바꿨습니다. 로그인해 주세요.';
  button.hidden=true;
 }catch(error){$('resetMessage').textContent=error.message;}
 finally{button.disabled=false;}
};
$('accountSettings').onclick=async()=>{
 if(saving||dirty&&!await save())return;
 $('changePasswordMessage').textContent='';$('deleteAccountMessage').textContent='';
 $('deleteAccountDetails').open=false;$('accountDialog').showModal();
};
$('accountClose').onclick=()=>$('accountDialog').close();
$('changePasswordForm').onsubmit=async e=>{
 e.preventDefault();const password=$('newPassword').value;
 if(password!==$('newPasswordAgain').value){$('changePasswordMessage').textContent='새 비밀번호가 서로 다릅니다.';return;}
 const button=$('changePasswordSubmit');button.disabled=true;
 try{
  const user=await api('/account/password','POST',{current_password:$('currentPassword').value,new_password:password});
  csrf=user.csrf;$('changePasswordForm').reset();
  $('changePasswordMessage').textContent='비밀번호를 바꿨습니다. 다른 기기에서는 다시 로그인해야 합니다.';
 }catch(error){$('changePasswordMessage').textContent=error.message;}
 finally{button.disabled=false;}
};
let deleteBusy=false;
$('deleteAccountForm').onsubmit=async e=>{
 e.preventDefault();
 if(deleteBusy||saving||dirty&&!await save()){
  $('deleteAccountMessage').textContent='원고가 아직 저장되지 않았습니다. 저장 상태를 확인해 주세요.';
  return;
 }
 $('deleteAccountMessage').textContent='';$('deleteWarningDialog').showModal();
};
$('deleteWarningCancel').onclick=()=>$('deleteWarningDialog').close();
$('deleteWarningDialog').addEventListener('cancel',e=>{if(deleteBusy)e.preventDefault();});
$('deleteWarningConfirm').onclick=async()=>{
 if(deleteBusy)return;
 deleteBusy=true;$('deleteWarningConfirm').disabled=true;$('deleteWarningCancel').disabled=true;
 let deleted=false;
 try{
  await api('/account/delete','POST',{password:$('deletePassword').value,confirmation:$('deleteConfirmation').value});
  deleted=true;
  try{YeobaekDrafts.clearAccount(draftEmail);}catch{}
  location.assign('/');
 }catch(error){$('deleteWarningDialog').close();$('deleteAccountMessage').textContent=error.message;}
 finally{if(!deleted){deleteBusy=false;$('deleteWarningConfirm').disabled=false;$('deleteWarningCancel').disabled=false;}}
};
