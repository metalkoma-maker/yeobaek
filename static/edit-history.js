/* Session-only editing history. Strings are retained as references, not diffed
   or serialized on every keystroke. Consecutive edits replace one group's tail. */
window.YeobaekEditHistory=class {
 constructor(state){this.reset(state);}
 reset(state){this.state=state;this.undoStack=[];this.redoStack=[];this.pending=null;this.composition=null;this.group=null;this.units=0;}
 before(state,type){this.pending={state,type};}
 beginComposition(state){this.composition=state;this.pending=null;this.group=null;}
 endComposition(after){const before=this.composition;this.composition=null;this.pending=null;if(before)this.record(before,after,'composition');}
 record(before,after,type,now=performance.now()){
  this.state=after;
  if(before.title===after.title&&before.body===after.body)return;
  const mergeable=['insertText','deleteContentBackward','deleteContentForward'].includes(type);
  const last=this.undoStack.at(-1),group=this.group;
  const joined=mergeable&&group&&group.type===type&&group.field===after.field&&now-group.time<1000&&last&&
   before.start===last.after.start&&before.end===last.after.end;
  const size=s=>s.title.length+s.body.length;
  if(joined){this.units-=size(last.after);last.after=after;this.units+=size(after);}
  else{this.undoStack.push({before,after});this.units+=size(before)+size(after);}
  this.redoStack=[];this.group=mergeable?{type,field:after.field,time:now}:null;
  // Keep at least the most recent transaction even for a very large manuscript.
  while(this.undoStack.length>1&&(this.undoStack.length>100||this.units>4000000)){
   const old=this.undoStack.shift();this.units-=size(old.before)+size(old.after);
  }
 }
 input(after,type){
  const before=this.pending?.state||this.state;type=this.pending?.type||type||'replacement';this.pending=null;
  if(this.composition){this.state=after;return;}
  this.record(before,after,type);
 }
 move(redo){
  const source=redo?this.redoStack:this.undoStack,target=redo?this.undoStack:this.redoStack;
  const entry=source.pop();if(!entry)return null;
  target.push(entry);this.group=null;this.pending=null;this.state=redo?entry.after:entry.before;
  // Recompute only on explicit undo/redo, never during repeated input.
  this.units=this.undoStack.reduce((n,e)=>n+e.before.title.length+e.before.body.length+e.after.title.length+e.after.body.length,0);
  return this.state;
 }
};
