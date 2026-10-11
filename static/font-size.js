(() => {
 const sizes=[10,12,14,16,18], key='yeobaek.body-font-size.pt.v1';
 const body=document.getElementById('body'), toggle=document.getElementById('fontToggle'), panel=document.getElementById('fontPanel'), control=document.getElementById('fontControl');
 const buttons=Array.from(panel.querySelectorAll('button[data-size]'));
 function apply(size){
  if(!sizes.includes(size))size=12;
  body.dataset.fontSize=String(size);
  body.dispatchEvent(new Event('yeobaek-font-change'));
  buttons.forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.size)===size)));
  toggle.setAttribute('aria-label',`본문 글자 크기 조정, 현재 ${size}포인트`);
 }
 function close(){panel.hidden=true;toggle.setAttribute('aria-expanded','false');}
 let stored=12;try{stored=Number(localStorage.getItem(key));}catch{}
 apply(stored);
 toggle.addEventListener('click',()=>{const open=panel.hidden;panel.hidden=!open;toggle.setAttribute('aria-expanded',String(open));if(open)buttons.find(b=>b.getAttribute('aria-pressed')==='true').focus();});
 buttons.forEach(button=>button.addEventListener('click',()=>{const size=Number(button.dataset.size);apply(size);try{localStorage.setItem(key,String(size));}catch{}close();toggle.focus();}));
 document.addEventListener('click',event=>{if(!control.contains(event.target))close();});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!panel.hidden){close();toggle.focus();}});
})();
