/* Shared production/demo A-B comparison view. User text is never HTML. */
window.YeobaekRecoveryView={render(container,a,b,onKeep,onLoad){
 container.replaceChildren();const grid=document.createElement('div');grid.className='recoveryGrid';
 for(const [label,data] of [['A · 서버에 저장된 글',a],['B · 이 기기에 남아 있는 글',b]]){const pane=document.createElement('section');const heading=document.createElement('h3');heading.textContent=label;const title=document.createElement('b');title.textContent=data.title||'제목 없는 원고';const text=document.createElement('textarea');text.readOnly=true;text.value=data.body;text.setAttribute('aria-label',label);pane.append(heading,title,text);grid.append(pane);}
 const actions=document.createElement('div');const keep=document.createElement('button');keep.textContent='A 유지하기';keep.onclick=onKeep;const load=document.createElement('button');load.textContent='B 불러오기';load.onclick=onLoad;actions.append(keep,load);container.append(grid,actions);
}};
