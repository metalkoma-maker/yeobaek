/* Private browser drafts. No server transfer. Each tab has an independent slot.
   A full snapshot starts a draft; later edits append small durable patches. */
window.YeobaekDrafts=(()=>{
 const prefix='yeobaek.draft.v1:',tab=crypto.randomUUID(),active=new Map();
 const namespace=email=>prefix+encodeURIComponent(email)+':';
 const ownKey=(email,id)=>namespace(email)+id+':'+tab;
 const patchPrefix=key=>key+':patch:';
 function keysFor(key){const found=[];for(let i=0;i<localStorage.length;i++){const name=localStorage.key(i);if(name.startsWith(patchPrefix(key)))found.push(name);}return found.sort((a,b)=>Number(a.slice(patchPrefix(key).length))-Number(b.slice(patchPrefix(key).length)));}
 function read(key){
  const raw=localStorage.getItem(key);if(!raw)return null;
  const base=JSON.parse(raw),patches=[];let data={...base};
  for(const name of keysFor(key)){
   const value=localStorage.getItem(name),patch=JSON.parse(value);
   patches.push({name,value});
   if(patch.sequence<=(base.through||0))continue;
   if(patch.sequence!==(data.through||0)+1)throw Error('임시 저장 기록이 연속되지 않습니다.');
   data={...data,body:data.body.slice(0,patch.start)+patch.insert+data.body.slice(patch.start+patch.remove),title:patch.title,version:patch.version,time:patch.time,through:patch.sequence};
  }
  return {key,raw,data,patches};
 }
 function list(email,excludeOwn=false){
  if(!email)return [];const ns=namespace(email),out=[];
  for(let i=0;i<localStorage.length;i++){
   const key=localStorage.key(i);
   if(!key.startsWith(ns)||key.includes(':patch:')||(excludeOwn&&key.endsWith(':'+tab)))continue;
   try{const item=read(key),data=item.data;if(typeof data.id==='string'&&typeof data.title==='string'&&typeof data.body==='string'&&Number.isInteger(data.version)&&Number.isFinite(data.time))out.push(item);}catch{}
  }
  return out.sort((a,b)=>b.data.time-a.data.time);
 }
 function diff(before,after){
  let start=0;while(start<before.length&&start<after.length&&before.charCodeAt(start)===after.charCodeAt(start))start++;
  let end=0;while(end<before.length-start&&end<after.length-start&&before.charCodeAt(before.length-end-1)===after.charCodeAt(after.length-end-1))end++;
  return {start,remove:before.length-start-end,insert:after.slice(start,after.length-end)};
 }
 function compact(key,entry){
  if(active.get(key)!==entry||entry.patches<200)return;
  try{
   localStorage.setItem(key,JSON.stringify({...entry.data,through:entry.sequence}));
   for(const name of keysFor(key))if(Number(name.slice(patchPrefix(key).length))<=entry.sequence)localStorage.removeItem(name);
   entry.patches=0;
  }catch{/* The existing snapshot and patches still recover the draft. */}
 }
 function put(email,data){
  const key=ownKey(email,data.id);let entry=active.get(key);
  if(!entry){
   const snapshot={...data,through:0};localStorage.setItem(key,JSON.stringify(snapshot));
   entry={data:snapshot,sequence:0,patches:0,timer:null};active.set(key,entry);return;
  }
  const sequence=entry.sequence+1,change=diff(entry.data.body,data.body);
  const patch={...change,sequence,title:data.title,version:data.version,time:data.time};
  localStorage.setItem(patchPrefix(key)+sequence,JSON.stringify(patch));
  entry.data={...data,through:sequence};entry.sequence=sequence;entry.patches++;
  clearTimeout(entry.timer);if(entry.patches>=200)entry.timer=setTimeout(()=>compact(key,entry),2000);
 }
 function clearOwn(email,id,title,body){
  const key=ownKey(email,id);let item;try{item=read(key);}catch{return;}
  if(!item||item.data.title!==title||item.data.body!==body)return;
  localStorage.removeItem(key);for(const {name} of item.patches)localStorage.removeItem(name);
  const entry=active.get(key);if(entry)clearTimeout(entry.timer);active.delete(key);
 }
 function removeUnchanged(item){
  if(localStorage.getItem(item.key)!==item.raw||keysFor(item.key).length!==(item.patches||[]).length||item.patches?.some(p=>localStorage.getItem(p.name)!==p.value))return;
  localStorage.removeItem(item.key);for(const {name} of item.patches||[])localStorage.removeItem(name);
 }
 function clearAccount(email){
  if(!email)return;const ns=namespace(email),keys=[];
  for(let i=0;i<localStorage.length;i++){const key=localStorage.key(i);if(key.startsWith(ns))keys.push(key);}
  for(const key of keys)localStorage.removeItem(key);
  for(const [key,entry] of active)if(key.startsWith(ns)){clearTimeout(entry.timer);active.delete(key);}
 }
 return {list,put,clearOwn,removeUnchanged,clearAccount,isOwn:item=>item.key.endsWith(':'+tab)};
})();
