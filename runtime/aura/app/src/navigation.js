/** Predictable remote movement. Horizontal rows never spill sideways into another
 * row. Grids keep their column. Focus memory is scoped to each page and zone.
 */
const memories=new Map();
let pageKey='home';
let verticalIntent=null;
export function setPage(key){if(pageKey!==key)verticalIntent=null;pageKey=key;}
export function scope(){return [...document.querySelectorAll('[data-modal-scope]')].at(-1)||document.querySelector('#shell');}
export function visible(e){return Boolean(e&&!e.disabled&&!e.closest('[inert]')&&e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden');}
export function focusables(root=scope()){return [...root.querySelectorAll('[data-focus]')].filter(visible);}
const rememberKey=z=>`${pageKey}:${z.dataset.zone}`;
export function rememberFocus(e){
 const z=e.closest('[data-zone]');if(z){const items=zoneItems(z);memories.set(rememberKey(z),{id:e.id,index:items.indexOf(e)});}
 if(e.closest('#view'))memories.set(`${pageKey}:content`,{id:e.id});
 if(e.closest('#header'))memories.set(`${pageKey}:header`,{id:e.id});
}
export function lastContent(){return memories.get(`${pageKey}:content`)?.id;}
export function lastHeader(){return memories.get(`${pageKey}:header`)?.id;}
export function lastIn(zoneId){return memories.get(`${pageKey}:${zoneId}`)?.id;}
export function clearFocusMemory(){memories.clear();verticalIntent=null;}
export function scrollToFocus(e){
 // Scroll just the owning panes, never the entire document. A small safe area
 // leaves room for the focus outline. Instant key scrolling avoids queued jumps.
 let parent=e.parentElement;
 while(parent&&parent!==document.body){
  const style=getComputedStyle(parent),r=parent.getBoundingClientRect(),b=e.getBoundingClientRect();
  const pad=Math.max(10,Math.min(20,r.height/8));
  if(/auto|scroll/.test(style.overflowX)&&parent.scrollWidth>parent.clientWidth+1){
   if(b.left<r.left+pad)parent.scrollLeft-=r.left+pad-b.left;
   else if(b.right>r.right-pad)parent.scrollLeft+=b.right-(r.right-pad);
  }
  if(/auto|scroll/.test(style.overflowY)&&parent.scrollHeight>parent.clientHeight+1){
   if(b.top<r.top+pad)parent.scrollTop-=r.top+pad-b.top;
   else if(b.bottom>r.bottom-pad)parent.scrollTop+=b.bottom-(r.bottom-pad);
  }
  parent=parent.parentElement;
 }
}
export function focusId(id,fallback=true){
 const e=document.getElementById(id);
 if(visible(e)&&scope().contains(e)){e.focus({preventScroll:true});scrollToFocus(e);rememberFocus(e);return true;}
 if(fallback){const first=focusables()[0];if(first){first.focus({preventScroll:true});scrollToFocus(first);rememberFocus(first);}}
 return false;
}
function zoneItems(zone){return focusables(zone).filter(e=>e.closest('[data-zone]')===zone);}
function zones(){return [...scope().querySelectorAll('[data-zone]')].filter(z=>zoneItems(z).length);}
function rows(items){
 const result=[];
 for(const e of items){
  // Layout coordinates ignore focus transforms and work across nested flex
  // containers (the top navigation and utilities do not share an offsetParent).
  let top=e.offsetHeight/2,parent=e;while(parent){top+=parent.offsetTop;parent=parent.offsetParent;}
  let row=result.find(r=>Math.abs(r.top-top)<Math.max(10,Math.min(r.height,e.offsetHeight)*.4));
  if(!row){row={top,height:e.offsetHeight,items:[]};result.push(row);}row.items.push(e);
 }
 return result.sort((a,b)=>a.top-b.top).map(r=>r.items);
}
function enter(zone,index=0,restore=true){
 if(!zone)return;const items=zoneItems(zone),saved=memories.get(rememberKey(zone));
 const target=restore&&saved?items.find(e=>e.id===saved.id):null;
 focusId((target||items[Math.min(Math.max(index,0),items.length-1)])?.id,false);
}
export function move(key){
 const cur=document.activeElement,all=focusables();if(!all.includes(cur)){focusId(all[0]?.id);return;}
 let zone=cur.closest('[data-zone]');
 if(!zone){const index=all.indexOf(cur),delta=['ArrowLeft','ArrowUp'].includes(key)?-1:1;focusId(all[Math.max(0,Math.min(all.length-1,index+delta))]?.id);return;}
 const items=zoneItems(zone),i=items.indexOf(cur),vertical=key==='ArrowUp'||key==='ArrowDown',sign=['ArrowLeft','ArrowUp'].includes(key)?-1:1;
 const layout=zone.dataset.layout||'horizontal',list=zones();
 // Explicit exits are used for asymmetric panes (keyboard and result grid).
 const direction=key.slice(5).toLowerCase();
 const exit=()=>{
  const id=zone.dataset[direction];
  if(id){const dest=list.find(z=>z.dataset.zone===id);if(dest){enter(dest,0);return true;}}return false;
 };
 if(layout==='vertical'){
  if(vertical){if(items[i+sign])focusId(items[i+sign].id);else exit();}
  else exit();return;
 }
 if(layout==='grid'||layout==='horizontal'){
  const rr=rows(items),ri=rr.findIndex(r=>r.includes(cur)),col=rr[ri]?.indexOf(cur)||0;
  if(vertical){
   const next=rr[ri+sign];
   if(next){const preferred=verticalIntent?.id===cur.id&&verticalIntent?.zone===zone.dataset.zone?verticalIntent.column:col;const target=next[Math.min(preferred,next.length-1)];focusId(target.id);verticalIntent={id:target.id,zone:zone.dataset.zone,column:preferred};return;}
  }else{
   verticalIntent=null;const next=rr[ri]?.[col+sign];if(next){focusId(next.id);return;}exit();return;
  }
 }
 if(exit())return;
 if(zone.dataset.zone==='header'&&key==='ArrowDown'){
  if(focusId(lastContent(),false))return;enter(list.find(z=>z.dataset.zone!=='header'));return;
 }
 const nextZone=list[list.indexOf(zone)+sign];
 if(nextZone?.dataset.zone==='header'){
  if(!focusId(lastHeader(),false))enter(nextZone,0);return;
 }
 enter(nextZone,i);
}
export function trapTab(event){
 const list=focusables();if(!list.length)return;
 const index=list.indexOf(document.activeElement),n=index<0?(event.shiftKey?list.length-1:0):(index+(event.shiftKey?-1:1)+list.length)%list.length;
 event.preventDefault();focusId(list[n].id);
}
