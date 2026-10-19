/* Private browser drafts. No server transfer. Each tab has an independent slot. */
window.YeobaekDrafts=(()=>{
 const prefix='yeobaek.draft.v1:',tab=crypto.randomUUID();
 const namespace=email=>prefix+encodeURIComponent(email)+':';
 function list(email,excludeOwn=false){if(!email)return [];const ns=namespace(email),out=[];for(let i=0;i<localStorage.length;i++){const key=localStorage.key(i);if(!key.startsWith(ns)||(excludeOwn&&key.endsWith(':'+tab)))continue;try{const raw=localStorage.getItem(key),data=JSON.parse(raw);if(typeof data.id==='string'&&typeof data.title==='string'&&typeof data.body==='string'&&Number.isInteger(data.version)&&Number.isFinite(data.time))out.push({key,raw,data});}catch{}}return out.sort((a,b)=>b.data.time-a.data.time);}
 function put(email,data){localStorage.setItem(namespace(email)+data.id+':'+tab,JSON.stringify(data));}
 function clearOwn(email,id,title,body){const key=namespace(email)+id+':'+tab,raw=localStorage.getItem(key);if(!raw)return;const data=JSON.parse(raw);if(data.title===title&&data.body===body)localStorage.removeItem(key);}
 function removeUnchanged(item){if(localStorage.getItem(item.key)===item.raw)localStorage.removeItem(item.key);}
 function clearAccount(email){if(!email)return;const ns=namespace(email),keys=[];for(let i=0;i<localStorage.length;i++){const key=localStorage.key(i);if(key.startsWith(ns))keys.push(key);}for(const key of keys)localStorage.removeItem(key);}
 return {list,put,clearOwn,removeUnchanged,clearAccount,isOwn:item=>item.key.endsWith(':'+tab)};
})();
