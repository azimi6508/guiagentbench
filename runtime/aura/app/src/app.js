import {VERSION,CATALOG,BUILTINS,PROFILES,SCHEMA,RANGES,DEFAULT_SETTINGS,byId,art,replaceCatalog} from './data.js';
import {state,storageAvailable,storageRecovered,save,fresh,resetAll,setMany,replaceState,setting,profileData,currentProfile,visibleCatalog,toggleSaved,remember,switchProfile,validateState,forgetMedia} from './store.js';
import {icon} from './icons.js';
import {move,focusId,focusables,trapTab,setPage,lastIn,rememberFocus,clearFocusMemory} from './navigation.js';
import {AudioEngine} from './audio.js';
import {SETTINGS,definition,valueLabel,settingsPage,settingsPanel,contextPanel,refreshSetting,dialogForSetting,categoryDefaults} from './settings.js';
import {connect,heartbeat,reloadLibrary,rescanLibrary,deleteMedia,upload,probeFile,writeMetadata,api,kindOf,formatTime,formatBytes,parseSubtitles,mediaSources,serverReady,folderCount} from './media.js';

const $=selector=>document.querySelector(selector);
function mediaUUID(){if(crypto.randomUUID)return crypto.randomUUID();const a=crypto.getRandomValues(new Uint8Array(16));a[6]=(a[6]&15)|64;a[8]=(a[8]&63)|128;const h=[...a].map(n=>n.toString(16).padStart(2,'0')).join('');return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;}
const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const btn=(id,action,content,cls='btn',extra='')=>`<button id="${id}" data-focus data-action="${action}" class="${cls}" ${extra}>${content}</button>`;
const iconButton=(id,action,name,label,extra='')=>btn(id,action,icon(name),'icon-btn',`aria-label="${label}" title="${label}" ${extra}`);
const view=$('#view'),overlay=$('#overlay');
const kindName={video:'Video',photo:'Photo',audio:'Music'},kindIcon={video:'film',photo:'image',audio:'music'};
const pages={home:'Home',videos:'Videos',photos:'Photos',music:'Music',saved:'Saved',search:'Search',settings:'Settings'};
let route=state.settings.startupPage,settingsTab='picture',settingsFocusKey=null,query='',sourceFilter='all',albumFilter='all',savedFilter='all';
let remoteItems=[],pageHistory=[],dialogs=[],playerState=null,photoState=null,importJob=null;
let homeBackdrop=null,homeFeature=null,ambientTimer=null,ambientGeneration=0,ambientSource='';
let toastTimer=null,lastActivity=Date.now(),heldKeyAt=0,sleepDeadline=state.settings.sleepMinutes?Date.now()+state.settings.sleepMinutes*60000:null;
const audio=new AudioEngine(()=>state.settings,text=>toast(text));
const currentDialog=()=>dialogs.at(-1);
const clockString=(date=new Date())=>new Intl.DateTimeFormat('en-US',{hour:'numeric',minute:'2-digit',hour12:!state.settings.clock24}).format(date);
const dateString=()=>new Intl.DateTimeFormat('en-US',{weekday:'short',month:'short',day:'numeric'}).format(new Date());
const netLabel=()=>serverReady?'Library server connected':'Library server offline';
function netStatus(){return `<span id="net-status" class="net-status ${serverReady?'online':'offline'}" role="img" aria-label="${netLabel()}" title="${netLabel()}">${icon(serverReady?'wifi':'offline','sm')}</span>`;}
function updateStatus(){
 const net=$('#net-status');if(net&&net.classList.contains('online')!==serverReady)net.outerHTML=netStatus();
 const date=$('#header-date');if(date){date.textContent=dateString();date.hidden=!state.settings.showClock;}
}
function toast(text){$('#toast').textContent=text;$('#toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),4300);}
function handleError(error){console.error(error);toast(error.message||'This action could not be completed.');}

// The ambient layer crossfades between two images so artwork changes never flash.
function setAmbient(src,mode='full'){
 const root=$('#ambient');if(!root)return;
 root.dataset.mode=src?mode:'off';
 if(!src||src===ambientSource)return;
 ambientSource=src;const generation=++ambientGeneration;
 const [a,b]=root.querySelectorAll('img'),current=a.classList.contains('visible')?a:b,next=current===a?b:a;
 next.src=src;
 next.decode().then(()=>{if(generation!==ambientGeneration)return;next.classList.add('visible');current.classList.remove('visible');}).catch(()=>{});
}
function routeAmbient(){
 clearTimeout(ambientTimer);
 if(route==='home')setAmbient(homeBackdrop,'full');
 else if(route==='settings')setAmbient(null);
 else setAmbient(pageItems().find(x=>x.poster)?.poster||homeBackdrop||'assets/photos/deep-field.jpg','soft');
}
function focusAmbient(el){
 if(dialogs.length||!el.closest('#view'))return;
 if(route==='home'&&el.closest('.cinema-hero')){
  clearTimeout(ambientTimer);setAmbient(homeBackdrop,'full');
  if(homeFeature&&$('#hero-spotlight'))$('#hero-spotlight').innerHTML=spotlight(homeFeature,homeFeature.source==='included'?'THE AURA COLLECTION':'FROM YOUR LIBRARY');
  return;
 }
 if(!el.classList.contains('media-card'))return;
 const item=byId(el.dataset.id);if(!item)return;
 if(route==='home'&&$('#hero-spotlight')){$('#hero-spotlight').innerHTML=spotlight(item,'NOW SELECTED');$('#hero-spotlight').hidden=false;}
 if(!item.poster)return;
 clearTimeout(ambientTimer);
 ambientTimer=setTimeout(()=>setAmbient(item.poster,route==='home'?'full':'soft'),180);
}
function renderHeader(){
 $('#header').innerHTML=`<div class="topbar" data-zone="header" data-layout="horizontal"><div class="brand"><span class="brand-mark">A</span><span>AURA<small>YOUR WORLD, AT HOME</small></span></div><nav class="topnav" aria-label="Main navigation">${['home','videos','photos','music','saved'].map(id=>btn('nav-'+id,'navigate',pages[id],'nav-item '+(route===id?'active':''),`data-route="${id}" ${route===id?'aria-current="page"':''}`)).join('')}</nav><div class="utilities">${iconButton('nav-search','navigate','search','Search library',`data-route="search" ${route==='search'?'aria-current="page"':''}`)}${iconButton('nav-add','add-media','plus','Add media')}<span class="nav-separator"></span><span class="status-cluster">${netStatus()}<span class="clock-stack"><time id="header-clock" class="clock">${clockString()}</time><small id="header-date" class="header-date">${dateString()}</small></span></span>${iconButton('nav-quick','quick-settings','sliders','Quick settings')}${iconButton('nav-settings','navigate','settings','Settings',`data-route="settings" ${route==='settings'?'aria-current="page"':''}`)}${btn('nav-profile','profiles',currentProfile().initial,'avatar',`aria-label="Switch profile, ${currentProfile().name}" style="--profile-color:${currentProfile().color}"`)}</div></div>`;
 $('#footer').innerHTML=`<div class="remote-hints"><span><kbd>↑ ↓ ← →</kbd> Move</span><span><kbd>OK</kbd> Select</span><span><kbd>Back</kbd> Return</span><span class="optional"><kbd>M</kbd> Mute</span><span class="optional"><kbd>Q</kbd> Quick settings</span></div><div class="footer-label"><span class="status-dot"></span><span>Your library · ${currentProfile().name}</span></div>`;
}
function applySettings(){
 const s=state.settings,root=document.documentElement;
 const accents={lavender:['#c4c6ff','196,198,255'],mint:['#a2dac2','162,218,194'],amber:['#efc281','239,194,129'],blue:['#9dcaff','157,202,255']};
 root.style.setProperty('--accent',accents[s.accent][0]);root.style.setProperty('--accent-rgb',accents[s.accent][1]);
 const m={standard:[1,1,1],cinema:[.96,1.08,.9],vivid:[1.05,1.12,1.2]}[s.pictureMode];
 const temperature={neutral:'',warm:' sepia(.18) saturate(1.04)',cool:' sepia(.12) hue-rotate(165deg)'}[s.temperature];
 root.style.setProperty('--picture',`brightness(${s.brightness/100*m[0]}) contrast(${s.contrast/100*m[1]}) saturate(${s.saturation/100*m[2]})${temperature}`);
 root.style.setProperty('--caption-font',{small:'1.25rem',medium:'1.75rem',large:'2.5rem'}[s.captionSize]);
 root.style.setProperty('--caption-bg',{dark:'#000b',solid:'#000',clear:'transparent'}[s.captionBackground]);
 root.style.setProperty('--text-scale',s.largeText?'1.13':'1');
 root.classList.toggle('reduce-motion',s.reducedMotion);root.classList.toggle('high-contrast',s.highContrast);root.classList.toggle('large-text',s.largeText);
 root.dataset.theme=s.theme;root.dataset.focus=s.focusStyle;root.dataset.density=s.thumbnailSize;
 if($('#header-clock')){$('#header-clock').hidden=!s.showClock;$('#header-clock').textContent=clockString();}
 updateStatus();
 if($('#standby-clock'))$('#standby-clock').textContent=clockString();
 audio.update();
 if(playerState){playerState.el.playbackRate=s.playbackRate;playerState.el.style.objectFit=s.videoFit;updatePlayer();}
 if(photoState)fitPhoto();
}
const allMusic=items=>items.length>0&&items.every(x=>x.kind==='audio');
function card(item,prefix='card',square=false){
 const saved=profileData().watchlist.includes(item.id),history=profileData().history[item.id],progress=history?.duration>0?Math.max(0,Math.min(100,history.time/history.duration*100)):0;
 const subtitle=item.kind==='photo'?(item.width?`${item.width} × ${item.height}`:'Photograph'):(item.duration?formatTime(item.duration):kindName[item.kind]);
 return btn(`${prefix}-${item.id}`,'detail',`<div class="media-cover ${square?'square':''}">${item.poster?`<img class="picture" loading="lazy" src="${escapeHTML(item.poster)}" alt="">`:`<div class="cover-placeholder">${icon(kindIcon[item.kind])}</div>`}<span class="media-type">${icon(kindIcon[item.kind],'sm')}</span>${saved?`<span class="saved-mark">${icon('heart','sm')}</span>`:''}<span class="duration-badge">${subtitle}</span>${progress>1&&progress<98?`<span class="watch-progress"><i style="width:${progress}%"></i></span>`:''}<span class="card-hover-play">${icon(item.kind==='photo'?'image':'play')}</span></div><span class="media-title">${escapeHTML(item.title)}</span><span class="media-sub">${escapeHTML(item.album||sourceLabel(item))}</span>`,'media-card',`data-id="${item.id}" aria-label="${escapeHTML(item.title)}, ${kindName[item.kind]}"`);
}
function spotlight(item,label){
 if(!item)return '';
 const facts=[kindName[item.kind],item.duration?formatTime(item.duration):item.width?`${item.width} × ${item.height}`:'',item.album||sourceLabel(item)].filter(Boolean);
 return `<span>${label}</span><strong>${escapeHTML(item.title)}</strong><small>${escapeHTML(facts.join(' · '))}</small>`;
}
function sourceLabel(item){return {included:'AURA collection',import:'Imported to AURA',folder:'Connected folder',link:'Media link'}[item.source]||'Your media';}
function rail(title,items,id,subtitle=''){
 if(!items.length)return '';
 return `<section class="media-section"><div class="section-heading"><div><h2>${title}</h2>${subtitle?`<p>${subtitle}</p>`:''}</div><span>${String(items.length).padStart(2,'0')} ITEMS</span></div><div class="media-rail" data-zone="${id}" data-layout="horizontal" id="${id}">${items.slice(0,30).map(x=>card(x,id,allMusic(items))).join('')}</div></section>`;
}
function home(){
 const items=visibleCatalog(),owned=items.filter(x=>x.source!=='included'),feature=owned.find(x=>x.poster&&x.kind==='video')||owned.find(x=>x.poster)||items.find(x=>x.id==='v-liftoff');
 const featuredTitle=owned.length&&feature?.source!=='included'?feature.title:'Your world.\nOn the big screen.';
 homeBackdrop=feature?.poster||'assets/photos/liftoff.jpg';homeFeature=feature||null;
 const resumable=items.filter(x=>{const h=profileData().history[x.id];return x.kind!=='photo'&&h&&h.time>1&&h.time<h.duration-1;}).sort((a,b)=>profileData().history[b.id].updated-profileData().history[a.id].updated);
 return `<section class="cinema-hero"><div class="hero-editorial"><div class="hero-overline"><span></span>${owned.length?'AT HOME IN YOUR COLLECTION':'A MORE PERSONAL KIND OF TV'}</div><h1>${escapeHTML(featuredTitle).replace('\n','<br>')}</h1><p>${owned.length&&feature?.source!=='included'?escapeHTML(feature.description||'One of your favorites, ready for a bigger screen.'): 'The films you keep. The moments you capture.<br>Your videos, photos and music, beautifully together.'}</p><div class="actions" data-zone="hero" data-layout="horizontal">${owned.length&&feature?.source!=='included'?btn('hero-play','open-media',`${icon(feature.kind==='photo'?'image':'play')}${feature.kind==='photo'?'View photo':'Play now'}`,'btn primary',`data-id="${feature.id}"`):btn('hero-play','add-media',`${icon('plus')}Add your media`,'btn primary')}${btn('hero-explore','navigate',`${icon('grid')}Explore collection`,'btn glass','data-route="videos"')}</div><div class="hero-footnote">${owned.length?`${owned.length} personal items · Saved on your terms`:'LOCAL FIRST <i></i> NO ACCOUNT REQUIRED'}</div></div><div class="hero-index" id="hero-spotlight" aria-live="off" ${feature?'':'hidden'}>${spotlight(feature,feature?.source==='included'?'THE AURA COLLECTION':'FROM YOUR LIBRARY')}</div></section><div class="library-content home-library"><div class="collection-shortcuts" data-zone="collections" data-layout="horizontal">${[['videos','film','Your cinema','video'],['photos','image','Your moments','photo'],['music','music','Your soundtrack','audio'],['saved','heart','Your favorites','saved']].map(([r,i,t,k])=>btn('collection-'+r,'navigate',`<span class="shortcut-icon">${icon(i)}</span><span><strong>${t}</strong><small>${k==='saved'?profileData().watchlist.filter(id=>items.some(x=>x.id===id)).length:items.filter(x=>x.kind===k).length} ${k==='saved'?'saved items':k==='photo'?'photographs':k==='audio'?'tracks':'videos'}</small></span>${icon('right','sm')}`,'collection-shortcut',`data-route="${r}"`)).join('')}</div>${rail('Pick up where you left off',resumable,'continue','Your next moment is right here.')}${rail(owned.length?'Recently added':'A little inspiration',owned.length?owned.slice().sort((a,b)=>b.added-a.added).slice(0,12):items.filter(x=>x.kind==='video'),'recent',owned.length?'The newest additions to your world.':'Three short photographic motion studies, each with its own soundtrack.')}${rail('A bigger picture',items.filter(x=>x.kind==='photo'),'photos-rail','Photographs deserve more than a small screen.')}${rail('Set the mood',items.filter(x=>x.kind==='audio'),'music-rail','A soundtrack for being at home.')}<div class="library-bottom"><span>AURA</span><p>Your files. Your space. Your pace.</p></div></div>`;
}
function sorted(items){return items.slice().sort(state.settings.sortOrder==='title'?(a,b)=>a.title.localeCompare(b.title):state.settings.sortOrder==='duration'?(a,b)=>(b.duration||0)-(a.duration||0):(a,b)=>(b.added||0)-(a.added||0));}
function scopedPageItems(){
 let items=visibleCatalog();const kind={videos:'video',photos:'photo',music:'audio'}[route];
 if(kind)items=items.filter(x=>x.kind===kind);
 if(route==='saved'){items=items.filter(x=>profileData().watchlist.includes(x.id));if(savedFilter!=='all')items=items.filter(x=>x.kind===savedFilter);}
 if(sourceFilter!=='all')items=items.filter(x=>x.source===sourceFilter);
 return items;
}
function pageItems(){return sorted(scopedPageItems().filter(x=>albumFilter==='all'||x.album===albumFilter));}
function empty(title='A little room for something good.',description='Add your own videos, photos or music to get started.'){
 return `<div class="real-empty"><span class="empty-glyph">${icon(route==='photos'?'image':route==='music'?'music':route==='saved'?'heart':'folder')}</span><h2>${title}</h2><p>${description}</p><div data-zone="empty" data-layout="horizontal">${btn('empty-add','add-media',`${icon('plus')}Add media`,'btn primary')}</div></div>`;
}
function catalogPage(){
 const items=pageItems();
 const subtitles={videos:'A front-row seat to your own collection.',photos:'The everyday. The extraordinary. All worth a closer look.',music:'Find the soundtrack for right now.',saved:'The things you love, all in one place.'};
 return `<div class="library-content"><div class="library-heading"><div><div class="page-kicker">${route==='saved'?currentProfile().name.toUpperCase()+'’S COLLECTION':'YOUR PERSONAL COLLECTION'}</div><h1>${pages[route]}<span>${items.length}</span></h1><p>${subtitles[route]}</p></div><div class="actions" data-zone="page-actions" data-layout="horizontal">${route==='photos'&&items.length?btn('start-slideshow','start-slideshow',`${icon('play')}Slideshow`,'btn glass'):''}${btn('page-add','add-media',`${icon('plus')}Add media`,'btn primary')}</div></div><div class="library-toolbar" data-zone="filters" data-layout="horizontal">${[['all','All sources'],['import','Imported'],['folder','Connected'],['included','AURA collection'],['link','Links']].map(([id,label])=>btn('source-'+id,'source-filter',label,'chip '+(sourceFilter===id?'active':''),`data-value="${id}" aria-pressed="${sourceFilter===id}"`)).join('')}<span class="toolbar-spacer"></span>${btn('sort-library','sort-library',`${icon('down','sm')}${valueLabel('sortOrder')}`,'sort-button')}${btn('album-library','album-library',`${icon('folder','sm')}${albumFilter==='all'?'All collections':escapeHTML(albumFilter)}`,'sort-button')}</div>${route==='saved'?`<div class="kind-filters" data-zone="saved-kinds" data-layout="horizontal">${[['all','Everything'],['video','Videos'],['photo','Photos'],['audio','Music']].map(([id,label])=>btn('saved-'+id,'saved-kind',label,'chip '+(savedFilter===id?'active':''),`data-value="${id}"`)).join('')}</div>`:''}${items.length?`<div class="media-grid ${route==='photos'?'photo-grid':route==='music'?'music-grid':''}" data-zone="catalog" data-layout="grid">${items.map(x=>card(x,'card',allMusic(items))).join('')}</div>`:empty(route==='saved'?'Keep a little of what you love.':'Nothing here just yet.',route==='saved'?'Open an item and choose Save to add it to your favorites.':'Try another source or collection, or add your own media.')}</div>`;
}
function searchResults(){
 const q=query.trim().toLocaleLowerCase();
 const items=visibleCatalog().filter(x=>!q||[x.title,x.name,x.album].some(t=>String(t||'').toLocaleLowerCase().includes(q)));
 return `<div class="results-label"><strong>${q?`${items.length} ${items.length===1?'result':'results'}`:'Explore your library'}</strong><span>${items.length>200?`Showing the first 200 of ${items.length} · Refine your search`:q?escapeHTML(query):'Search videos, photos and music'}</span></div><div class="media-grid" data-zone="results" data-layout="grid" data-left="keyboard" data-up="header">${items.slice(0,200).map(x=>card(x,'result',allMusic(items))).join('')}</div>${!items.length?'<p class="search-no-results">No matches. Try a different title or collection.</p>':''}`;
}
function searchPage(){
 const keys='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'.split('');
 return `<div class="library-content"><div class="library-heading"><div><div class="page-kicker">FIND YOUR NEXT MOMENT</div><h1>Search</h1></div></div><div class="search-layout-v3"><div class="search-left"><div class="search-entry" data-zone="search-field" data-layout="horizontal" data-down="keyboard">${icon('search')}<input data-focus type="search" autocomplete="off" id="search-input" maxlength="120" value="${escapeHTML(query)}" placeholder="Titles, files, collections…" aria-label="Search media"></div><div class="remote-keyboard" data-zone="keyboard" data-layout="grid" data-up="search-field" data-right="results" data-down="keyboard-actions">${keys.map(k=>btn('key-'+k,'key',k,'key',`data-key="${k}"`)).join('')}</div><div class="keyboard-actions" data-zone="keyboard-actions" data-layout="horizontal" data-up="keyboard" data-right="results">${btn('key-space','key','Space','key wide','data-key="SPACE"')}${btn('key-delete','key','⌫','key','data-key="DELETE" aria-label="Delete character"')}${btn('key-clear','key','Clear','key','data-key="CLEAR"')}</div><p class="keyboard-hint">Use your remote, or type with your keyboard.</p></div><div id="search-results" class="search-results-v3">${searchResults()}</div></div></div>`;
}
function renderView(){
 setPage(route);view.classList.toggle('is-settings',route==='settings');
 view.innerHTML=route==='home'?home():route==='settings'?settingsPage(settingsTab):route==='search'?searchPage():catalogPage();
 applySettings();routeAmbient();
}
function renderAll(focus=null){renderHeader();renderView();if(focus)focusId(focus);}
function scrollSnapshot(){return {top:view.scrollTop,rails:[...view.querySelectorAll('.media-rail')].map(e=>[e.id,e.scrollLeft]),settings:$('#settings-rows')?.scrollTop||0};}
function restoreScroll(s){if(!s)return;view.scrollTop=s.top;for(const[id,left]of s.rails||[]){const e=document.getElementById(id);if(e)e.scrollLeft=left;}if($('#settings-rows'))$('#settings-rows').scrollTop=s.settings;}
function defaultFocus(){return route==='home'?'hero-play':route==='settings'?'settings-tab-'+settingsTab:route==='search'?'search-input':'source-'+sourceFilter;}
function navigate(next,{record=true}={}){
 if(!pages[next])return;
 if(dialogs.length)closeAll();
 if(route!==next&&record){pageHistory.push({route,focus:document.activeElement.id,scroll:scrollSnapshot(),sourceFilter,albumFilter,savedFilter,settingsTab});if(pageHistory.length>30)pageHistory.shift();}
 route=next;sourceFilter='all';albumFilter='all';savedFilter='all';view.scrollTop=0;audio.stopSample();renderAll(defaultFocus());
}
function back(){
 if(dialogs.length){
  if(currentDialog().kind==='import'&&importJob?.running){importJob.controller.abort();importJob.canceled=true;toast('Stopping import. Completed files are kept.');return;}
  if(currentDialog().kind==='photo'&&photoState.zoom>1){photoState.zoom=1;photoState.panX=photoState.panY=0;fitPhoto();return;}
  if(currentDialog().kind==='player'&&playerState.hidden){showPlayerControls();return;}
  closeModal();return;
 }
 if(route==='settings'&&document.activeElement.closest('#settings-rows')){focusId('settings-tab-'+settingsTab);return;}
 if(pageHistory.length){audio.stopSample();const s=pageHistory.pop();({route,sourceFilter,albumFilter,savedFilter,settingsTab}=s);renderAll();restoreScroll(s.scroll);focusId(s.focus);}
 else if(route!=='home')navigate('home',{record:false});else focusId('nav-home');
}
function setModal(html,kind,focus,cleanup=null){
 if(currentDialog()?.kind==='player')clearTimeout(playerState?.hideTimer);
 if(currentDialog()?.kind==='photo')clearTimeout(photoState?.timer);
 if(currentDialog())currentDialog().node.inert=true;
 const origin={focus:document.activeElement?.id,scroll:scrollSnapshot()};
 const node=document.createElement('div');node.className='dialog-layer';node.innerHTML=html;overlay.append(node);
 dialogs.push({node,kind,origin,cleanup});$('#shell').inert=true;focusId(focus);return node;
}
function closeModal(restore=true){
 const d=dialogs.pop();if(!d)return;
 d.cleanup?.();d.node.remove();
 if(currentDialog())currentDialog().node.inert=false;else $('#shell').inert=false;
 if(restore){restoreScroll(d.origin.scroll);focusId(d.origin.focus||defaultFocus());}
 if(currentDialog()?.kind==='player')schedulePlayerHide();
 if(currentDialog()?.kind==='photo')schedulePhoto();
}
function closeAll(){while(dialogs.length)closeModal(false);if(!focusables().includes(document.activeElement))focusId(defaultFocus());}
function refreshContent(){const snap=scrollSnapshot(),id=document.activeElement.id;renderView();restoreScroll(snap);if(!dialogs.length)focusId(id,false);}
function metadata(item){return `<div class="metadata"><span>${kindName[item.kind]}</span>${item.duration?`<i>·</i><span>${formatTime(item.duration)}</span>`:''}${item.width?`<i>·</i><span>${item.width} × ${item.height}</span>`:''}<span class="badge">${escapeHTML(sourceLabel(item))}</span></div>`;}
function detail(id){
 const item=byId(id);if(!item)return toast('This item is no longer in the library.');
 const saved=profileData().watchlist.includes(id);
 setModal(`<div class="modal-backdrop"><section class="media-detail" data-media-id="${escapeHTML(id)}" data-modal-scope role="dialog" aria-modal="true" aria-labelledby="detail-title"><div class="detail-art">${item.poster?`<img class="picture" src="${escapeHTML(item.poster)}" alt="">`:`<div class="detail-placeholder">${icon(kindIcon[item.kind])}</div>`}<div class="detail-art-shade"></div><div class="detail-close-zone" data-zone="detail-top" data-layout="horizontal" data-down="detail-actions">${iconButton('detail-close','close','close','Close details')}</div><div class="detail-headline"><div class="page-kicker">${escapeHTML(item.album||sourceLabel(item))}</div><h1 id="detail-title">${escapeHTML(item.title)}</h1>${metadata(item)}</div></div><div class="detail-information"><p>${escapeHTML(item.description||`${item.kind==='photo'?'A photograph':'A '+kindName[item.kind].toLowerCase()+' file'} from ${sourceLabel(item).toLowerCase()}. Open it to enjoy it on the big screen.`)}</p><div class="actions" data-zone="detail-actions" data-layout="horizontal" data-up="detail-top" data-down="detail-actions">${btn('detail-play','open-media',`${icon(item.kind==='photo'?'image':'play')}${item.kind==='photo'?'View photo':state.settings.resume&&profileData().history[id]?.time>1&&profileData().history[id].time<profileData().history[id].duration-1?'Resume':'Play now'}`,'btn primary',`data-id="${id}"`)}${btn('detail-save','save',`${icon(saved?'check':'plus')}<span>${saved?'Saved':'Save for later'}</span>`,'btn',`data-id="${id}" aria-pressed="${saved}"`)}${btn('detail-info','media-info',`${icon('info')}File details`,'btn ghost',`data-id="${id}"`)}${item.source==='import'||item.source==='link'?iconButton('detail-manage','manage-media','more','Manage media',`data-id="${id}"`):''}</div><div class="detail-credit">${escapeHTML(item.credit||item.name||'Your personal media')}</div></div></section></div>`,'detail','detail-play');
}
function confirmDialog(title,text,callback,label='Confirm'){
 const node=setModal(`<div class="modal-backdrop"><section class="modal compact-modal" data-modal-scope role="alertdialog" aria-modal="true" aria-labelledby="confirm-title"><div class="dialog-symbol">${icon('info')}</div><h2 id="confirm-title">${escapeHTML(title)}</h2><p>${escapeHTML(text)}</p><div class="actions" data-zone="confirm" data-layout="horizontal">${btn('confirm-cancel','close','Cancel','btn')}${btn('confirm-ok','confirm',label,'btn danger')}</div></section></div>`,'confirm','confirm-cancel');
 node.querySelector('#confirm-ok').addEventListener('click',()=>{closeModal();Promise.resolve().then(callback).catch(handleError);});
}
function chooseDialog(title,choices,current,onChoose){
 const node=setModal(`<div class="modal-backdrop"><section class="setting-dialog" data-modal-scope role="dialog" aria-modal="true" aria-labelledby="choose-title"><div class="setting-dialog-heading"><span class="context-overline">YOUR PREFERENCE</span><h2 id="choose-title">${escapeHTML(title)}</h2></div><div class="choice-list" data-zone="choices" data-layout="vertical" data-down="choice-footer">${choices.map((c,i)=>btn('option-'+i,'custom-choice',`<span><strong>${escapeHTML(c.label)}</strong>${c.description?`<small>${escapeHTML(c.description)}</small>`:''}</span>${current===c.value?icon('check'):'<i class="choice-circle"></i>'}`,'choice '+(current===c.value?'selected':''),`data-index="${i}" aria-pressed="${current===c.value}"`)).join('')}</div><div class="choice-cancel" data-zone="choice-footer" data-layout="horizontal" data-up="choices">${btn('choose-cancel','close','Cancel','btn ghost')}</div></section></div>`,'choice','option-'+Math.max(0,choices.findIndex(x=>x.value===current)));
 node.querySelectorAll('[data-action="custom-choice"]').forEach(e=>e.addEventListener('click',()=>{const c=choices[Number(e.dataset.index)];closeModal();onChoose(c.value);}));
}
function showProfiles(){
 setModal(`<div class="modal-backdrop"><section class="modal profile-modal" data-modal-scope role="dialog" aria-modal="true" aria-labelledby="profiles-title"><div data-zone="profiles-top" data-layout="horizontal">${iconButton('profiles-close','close','close','Close profiles')}</div><div class="page-kicker">MAKE YOURSELF AT HOME</div><h2 id="profiles-title">Who’s watching?</h2><p>One library. A little space of your own.</p><div class="profile-cards" data-zone="profiles" data-layout="horizontal">${PROFILES.map(p=>btn('profile-'+p.id,'switch-profile',`<span class="avatar" style="--profile-color:${p.color}">${p.initial}</span><h3>${p.name}</h3><p>${p.id===state.profile?'Watching now':'Your favorites & history'}</p>`,'profile-card '+(p.id===state.profile?'active':''),`data-profile="${p.id}"`)).join('')}</div></section></div>`,'profiles','profile-'+state.profile);
}
function mediaInfo(id){
 const item=byId(id);if(!item)return;
 const rows=[['File',item.name||item.title],['Source',sourceLabel(item)],['Type',item.mime||kindName[item.kind]],['Size',formatBytes(item.size)||(item.source==='included'?'Bundled media':'Not supplied by source')],['Dimensions',item.width?`${item.width} × ${item.height}`:'Read when opened'],['Duration',item.duration?formatTime(item.duration):'—'],['Collection',item.album||'Unsorted']];
 setModal(`<div class="modal-backdrop"><section class="modal info-modal" data-modal-scope role="dialog" aria-modal="true" aria-labelledby="info-title"><span class="context-overline">A CLOSER LOOK</span><h2 id="info-title">${escapeHTML(item.title)}</h2><dl class="file-facts">${rows.map(([k,v])=>`<div><dt>${k}</dt><dd>${escapeHTML(v)}</dd></div>`).join('')}</dl>${item.credit?`<p class="credit-note">${escapeHTML(item.credit)}</p>`:''}<div class="actions" data-zone="info-actions" data-layout="horizontal">${btn('info-done','close','Done','btn primary')}</div></section></div>`,'info','info-done');
}
function manageMedia(id){
 const item=byId(id);if(!item)return;
 chooseDialog('Manage '+item.title,[...(item.source==='import'?[{value:'rename',label:'Edit title & collection',description:'Change how this file appears in AURA.'}]:[]),{value:'delete',label:item.source==='link'?'Remove link':'Delete imported copy',description:item.source==='link'?'The remote file is not changed.':'Only the copy in AURA is deleted. Your original file is untouched.'}],null,value=>{
  if(value==='delete')confirmDialog(item.source==='link'?'Remove this link?':'Delete this imported copy?',item.source==='link'?'Remove the link and its saved playback positions.':'This removes the file from AURA for every profile. The original you imported is not changed.',async()=>{if(item.source==='import')await deleteMedia(id);forgetMedia(id);remoteItems=remoteItems.filter(x=>x.id!==id);replaceCatalog([...remoteItems,...state.links]);if(dialogs.some(d=>d.node.querySelector('.media-detail')?.dataset.mediaId===id))closeAll();refreshContent();toast('Removed from AURA.');},'Remove');
  else editMetadata(item);
 });
}
function editMetadata(item){
 const node=setModal(`<div class="modal-backdrop"><section class="modal compact-modal" data-modal-scope role="dialog" aria-modal="true" aria-labelledby="edit-title"><span class="context-overline">MAKE IT YOURS</span><h2 id="edit-title">Edit media details</h2><div class="form-fields" data-zone="edit-fields" data-layout="vertical" data-down="edit-actions"><label for="media-title">Title</label><input data-focus id="media-title" maxlength="180" value="${escapeHTML(item.title)}"><label for="media-album">Collection</label><input data-focus id="media-album" maxlength="180" value="${escapeHTML(item.album||'My collection')}"></div><p id="edit-error" role="status"></p><div class="actions" data-zone="edit-actions" data-layout="horizontal" data-up="edit-fields">${btn('edit-cancel','close','Cancel')}${btn('edit-save','custom-save','Save changes','btn primary')}</div></section></div>`,'edit','media-title');
 node.querySelector('#edit-save').addEventListener('click',async()=>{
  const submit=node.querySelector('#edit-save');if(submit.disabled)return;
  try{const title=node.querySelector('#media-title').value.trim(),album=node.querySelector('#media-album').value.trim();if(!title||!album)throw Error('Enter a title and a collection.');submit.disabled=true;await api(`/api/media/${item.id}/metadata`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,album})});await syncLibrary();if(node.isConnected){closeAll();refreshContent();detail(item.id);}else refreshContent();toast('Media details saved.');}
  catch(e){node.querySelector('#edit-error').textContent=e.message;}
  finally{submit.disabled=false;}
 });
}

// Native media playback is the default. Enhanced processing is opt-in, and
// cross-origin links always use native audio to avoid CORS-silenced Web Audio.
function openMedia(id,slideshow=false){
 const item=byId(id);if(!item)return toast('That file is no longer available.');
 if(item.kind==='photo'){openPhoto(id,slideshow);return;}
 openPlayer(item);
}
function queueFor(item){let items=['videos','music','photos','saved'].includes(route)?pageItems():visibleCatalog();items=items.filter(x=>x.kind===item.kind);return items.some(x=>x.id===item.id)?items:[item];}
function openPlayer(item){
 audio.stopSample();
 const queue=queueFor(item);
 const html=`<section class="player player-v3" data-modal-scope role="dialog" aria-modal="true" aria-labelledby="player-title" tabindex="-1"><div class="media-stage" id="media-stage"></div><div class="player-top" data-zone="player-top" data-layout="horizontal" data-down="timeline">${iconButton('player-close','close','back','Back to library')}<span class="player-top-spacer"></span><span class="player-quality" id="player-quality"></span><time class="player-clock" id="player-clock">${clockString()}</time></div><div id="playback-notice" class="playback-notice" hidden role="status"></div><div id="captions" class="captions" aria-live="off"></div><div class="player-bottom"><div class="player-heading"><span class="player-label" id="player-label"></span><h1 id="player-title"></h1></div><div class="player-status"><span id="player-status">Opening media…</span><span id="player-ends" class="player-ends"></span><span class="player-status-spacer"></span><span id="player-audio-status"></span></div><div class="player-progress" data-zone="timeline" data-layout="horizontal" data-up="player-top" data-down="player-buttons"><time id="player-time">0:00</time><input data-focus type="range" id="player-seek" min="0" max="1" step="any" data-step="10" value="0" aria-label="Playback position"><time id="player-duration">—</time></div><div class="player-controls" data-zone="player-buttons" data-layout="horizontal" data-up="timeline" data-down="player-buttons">${iconButton('player-previous','player-previous','previous','Previous item')}${iconButton('player-rewind','seek-back','rewind','Back 10 seconds')}${iconButton('player-toggle','play-toggle','play','Play')}${iconButton('player-forward','seek-forward','forward','Forward 10 seconds')}${iconButton('player-next','player-next','next','Next item')}<span class="control-spacer"></span>${iconButton('player-volume','player-volume','volume','Volume')}${btn('player-subs','subtitles',icon('cc'),'icon-btn','aria-label="Subtitles"')}${btn('player-fit','player-fit','Fit','player-text-button','aria-label="Video framing"')}${btn('player-speed','cycle-speed','1×','player-text-button','aria-label="Playback speed"')}${iconButton('player-more','player-options','more','Playback options')}${iconButton('player-fullscreen','fullscreen','fullscreen','Fullscreen')}</div></div></section>`;
 const node=setModal(html,'player','player-toggle',()=>{
  const p=playerState;if(!p)return;clearTimeout(p.hideTimer);remember(p.item.id,p.el.currentTime,p.el.duration);p.el.pause();audio.detach(p.el);p.el.removeAttribute('src');p.el.load();playerState=null;refreshContent();
 });
 playerState={node,queue,item,el:null,hidden:false,lastFocus:'player-toggle',hideTimer:null,lastSave:0,cues:[],subtitleName:'',loop:false};
 loadPlayerItem(item);
}
function loadPlayerItem(item,resumeOverride=null,playOverride=null){
 const p=playerState;if(!p)return;
 const sameItem=p.el&&p.item.id===item.id;
 if(p.el){remember(p.item.id,p.el.currentTime,p.el.duration);p.el.pause();audio.detach(p.el);p.el.removeAttribute('src');p.el.load();}
 p.item=item;if(!sameItem){p.cues=[];p.subtitleName='';}p.lastSave=0;
 $('#player-title').textContent=item.title;$('#player-label').textContent=sourceLabel(item)+' / '+kindName[item.kind];
 $('#player-quality').textContent=item.width?`${item.width} × ${item.height}`:item.kind==='audio'?'AUDIO':'';
 $('#playback-notice').hidden=true;$('#captions').textContent='';
 p.node.querySelector('.player').classList.toggle('is-audio',item.kind==='audio');
 const stage=$('#media-stage');stage.innerHTML=item.kind==='audio'?`<div class="music-stage"><img class="music-backdrop" src="${escapeHTML(item.poster||'assets/photos/deep-field.jpg')}" alt=""><div class="music-album"><img src="${escapeHTML(item.poster||'assets/photos/deep-field.jpg')}" alt=""><span class="record-pin"></span></div><div class="music-title"><span><i class="eq-bars" aria-hidden="true"><b></b><b></b><b></b><b></b></i>NOW PLAYING</span><h2>${escapeHTML(item.title)}</h2><p>${escapeHTML(item.album||sourceLabel(item))}</p></div></div>`:'';
 const el=document.createElement(item.kind==='audio'?'audio':'video');el.id='media-element';el.className='picture';el.preload='auto';el.playsInline=true;if(item.poster&&item.kind==='video')el.poster=item.poster;stage.prepend(el);p.el=el;
 p.sources=mediaSources(item,el);p.sourceIndex=0;p.loadGeneration=(p.loadGeneration||0)+1;
 p.wantsPlay=playOverride??(state.settings.autoplay||resumeOverride!==null);
 el.src=p.sources[0].url;el.playbackRate=state.settings.playbackRate;el.style.objectFit=state.settings.videoFit;
 p.enhanced=audio.attach(el,item.source==='link');
 const history=profileData().history[item.id];
 let seek=resumeOverride??(state.settings.resume&&history&&history.time<history.duration-1?history.time:0);
 el.addEventListener('loadedmetadata',()=>{if(playerState!==p||p.el!==el)return;if(seek>0&&Number.isFinite(el.duration))el.currentTime=Math.min(el.duration-.1,seek);if(el.videoWidth){item.width=el.videoWidth;item.height=el.videoHeight;$('#player-quality').textContent=`${el.videoWidth} × ${el.videoHeight}`;}if(Number.isFinite(el.duration))item.duration=el.duration;updatePlayer();});
 for(const event of ['timeupdate','loadeddata','play','pause','seeked','waiting','canplay'])el.addEventListener(event,()=>{
  if(playerState!==p||p.el!==el)return;if(['loadeddata','canplay'].includes(event)&&!el.error)$('#playback-notice').hidden=true;updatePlayer();
  if(event==='pause')showPlayerControls();if(event==='play')schedulePlayerHide();
 });
 el.addEventListener('ended',()=>{
  if(playerState!==p||p.el!==el)return;updatePlayer();
  if(state.settings.repeatMode==='one'){el.currentTime=0;safePlay();}
  else if(state.settings.playNext||state.settings.repeatMode==='all')nextPlayer(1,true);
  else showPlayerControls();
 });
 el.addEventListener('error',()=>{
  if(playerState!==p||p.el!==el)return;
  if([2,3,4].includes(el.error?.code)&&p.sourceIndex+1<p.sources.length){
   seek=Number.isFinite(el.currentTime)&&el.currentTime>0?el.currentTime:seek;
   p.sourceIndex++;p.loadGeneration++;el.src=p.sources[p.sourceIndex].url;el.load();el.playbackRate=state.settings.playbackRate;
   $('#playback-notice').textContent='Opening an alternate media format…';$('#playback-notice').hidden=false;
   if(p.wantsPlay)safePlay();else updatePlayer();return;
  }
  const messages={1:'Playback was interrupted.',2:'This media could not be reached. Check the file or connection.',3:'The browser could not decode this media. Try MP4 with H.264/AAC or WebM with VP8/VP9 and Opus.',4:'This format or link is not playable in this browser. Use a direct media file, not a website link.'};
  $('#playback-notice').textContent=messages[el.error?.code]||'Unable to open this media.';$('#playback-notice').hidden=false;showPlayerControls();updatePlayer();
 });
 if(p.wantsPlay)safePlay();else updatePlayer();
}
async function safePlay(){
 const p=playerState;if(!p)return;const el=p.el,generation=p.loadGeneration;p.wantsPlay=true;
 if(state.settings.audioPath==='enhanced'&&p.item.source!=='link'){
  const unlocked=await audio.unlock();if(playerState!==p||p.el!==el||p.loadGeneration!==generation||!p.wantsPlay)return;
  if(unlocked&&!p.enhanced)p.enhanced=audio.attach(el,false);
 }
 try{await el.play();if(playerState===p&&p.el===el&&p.loadGeneration===generation&&$('#playback-notice'))$('#playback-notice').hidden=true;}
 catch(e){if(playerState===p&&p.el===el&&p.loadGeneration===generation&&e.name!=='AbortError'&&!el.error){$('#playback-notice').textContent=e.name==='NotAllowedError'?'Press Play to begin. Your browser needs permission to play sound.':'Could not start this media. Check its format or source.';$('#playback-notice').hidden=false;showPlayerControls();}}
}
function updatePlayer(){
 const p=playerState;if(!p||!p.el)return;const el=p.el,s=state.settings,d=el.duration;
 const play=$('#player-toggle');if(!play)return;
 play.innerHTML=icon(el.paused?'play':'pause');play.setAttribute('aria-label',el.paused?'Play':'Pause');
 $('#player-status').textContent=el.error?'Playback unavailable':el.readyState<2?'Loading…':el.ended?'Finished':el.paused?'Paused':'Playing';
 $('#player-time').textContent=formatTime(el.currentTime);$('#player-duration').textContent=formatTime(d);
 const remaining=(d-el.currentTime)/(el.playbackRate||1);
 $('#player-ends').textContent=Number.isFinite(remaining)&&remaining>0&&!el.error?`Ends at ${clockString(new Date(Date.now()+remaining*1000))}`:'';
 const seek=$('#player-seek');seek.max=Number.isFinite(d)?d:1;seek.disabled=!Number.isFinite(d)||d<=0;seek.value=el.currentTime;seek.style.setProperty('--seek',`${Number.isFinite(d)?el.currentTime/d*100:0}%`);seek.setAttribute('aria-valuetext',formatTime(el.currentTime)+' of '+formatTime(d));
 $('#player-audio-status').textContent=s.muted?'Muted · M to unmute':s.volume===0?'Volume 0 · + to increase':`${s.volume}% · ${p.enhanced?'Enhanced':'Direct'} sound`;
 $('#player-volume').innerHTML=icon(s.muted?'mute':'volume');$('#player-speed').textContent=s.playbackRate+'×';$('#player-fit').textContent=s.videoFit==='contain'?'Fit':'Fill';$('#player-fit').hidden=p.item.kind==='audio';$('#player-subs').hidden=p.item.kind==='audio';
 const ci=p.queue.findIndex(x=>x.id===p.item.id);$('#player-previous').disabled=ci<=0&&state.settings.repeatMode!=='all';$('#player-next').disabled=ci>=p.queue.length-1&&state.settings.repeatMode!=='all';
 const lines=p.cues.filter(c=>el.currentTime>=c.start&&el.currentTime<c.end).map(c=>c.text);$('#captions').textContent=s.captions?lines.join('\n'):'';$('#captions').hidden=!s.captions||!lines.length;
 p.node.querySelector('.player').classList.toggle('is-paused',el.paused);
 if(Date.now()-p.lastSave>2000&&el.readyState>=2){p.lastSave=Date.now();remember(p.item.id,el.currentTime,d);}
}
function togglePlayback(){if(!playerState)return;if(playerState.el.paused){if(playerState.el.ended)playerState.el.currentTime=0;safePlay();}else {playerState.wantsPlay=false;playerState.el.pause();}}
function seekBy(delta){const el=playerState?.el;if(el&&Number.isFinite(el.duration)){el.currentTime=Math.max(0,Math.min(el.duration,el.currentTime+delta));updatePlayer();}}
function nextPlayer(delta,automatic=false){
 const p=playerState;if(!p)return;let i=p.queue.findIndex(x=>x.id===p.item.id)+delta;
 if(i<0||i>=p.queue.length){if(state.settings.repeatMode==='all')i=(i+p.queue.length)%p.queue.length;else {if(automatic)showPlayerControls();return;}}
 loadPlayerItem(p.queue[i],0);showPlayerControls();
}
function schedulePlayerHide(){
 const p=playerState;if(!p)return;clearTimeout(p.hideTimer);
 if(!state.settings.controlsTimeout||p.el?.paused||currentDialog()?.kind!=='player')return;
 p.hideTimer=setTimeout(()=>{
  if(playerState!==p||p.el.paused||currentDialog()?.kind!=='player')return;
  if(document.activeElement.id==='player-seek'){schedulePlayerHide();return;}
  p.lastFocus=document.activeElement.id||'player-toggle';p.hidden=true;
  p.node.querySelector('.player').classList.add('controls-hidden');p.node.querySelector('.player-top').inert=true;p.node.querySelector('.player-bottom').inert=true;p.node.querySelector('.player').focus({preventScroll:true});
 },state.settings.controlsTimeout*1000);
}
function showPlayerControls(){
 const p=playerState;if(!p)return;
 p.node.querySelector('.player').classList.remove('controls-hidden');p.node.querySelector('.player-top').inert=false;p.node.querySelector('.player-bottom').inert=false;
 const hidden=p.hidden;p.hidden=false;if(hidden&&currentDialog()?.kind==='player')focusId(p.lastFocus||'player-toggle');schedulePlayerHide();
}
function subtitleDialog(){
 const p=playerState;if(!p)return;const mediaId=p.item.id;
 const node=setModal(`<div class="modal-backdrop"><section class="modal compact-modal" data-modal-scope role="dialog" aria-modal="true" aria-labelledby="sub-title"><span class="context-overline">FOLLOW EVERY WORD</span><h2 id="sub-title">Subtitles</h2><p>${p.subtitleName?'Loaded: '+escapeHTML(p.subtitleName):'Open an SRT or WebVTT subtitle file for this video. Files stay in this viewing session.'}</p><input type="file" id="subtitle-file" accept=".srt,.vtt,text/vtt" hidden><div class="subtitle-actions" data-zone="subtitle-actions" data-layout="vertical">${btn('subtitle-open','subtitle-open',`${icon('folder')}Open subtitle file`,'btn primary')}${btn('subtitle-toggle','subtitle-toggle',state.settings.captions?'Turn subtitles off':'Turn subtitles on','btn')}${btn('subtitle-clear','subtitle-clear','Remove subtitles','btn ghost')}${btn('subtitle-done','close','Done','btn ghost')}</div><p id="subtitle-message" role="status"></p></section></div>`,'subtitles','subtitle-open');
 node.querySelector('#subtitle-file').addEventListener('change',async e=>{
  const file=e.target.files[0];if(!file)return;
  try{if(file.size>2*1024**2)throw Error('Choose a subtitle file smaller than 2 MB.');const text=await file.text();if(!node.isConnected||playerState!==p||p.item.id!==mediaId)return;const cues=parseSubtitles(text);if(!cues.length)throw Error('No valid timed subtitles were found.');p.cues=cues;p.subtitleName=file.name;changeSetting('captions',true);node.querySelector('#subtitle-message').textContent=`${file.name} · ${cues.length} subtitle cues loaded.`;$('#subtitle-toggle').textContent='Turn subtitles off';updatePlayer();}
  catch(err){node.querySelector('#subtitle-message').textContent=err.message;}
 });
}
function playerOptions(){
 chooseDialog('Playback options',[{value:'audio',label:'Audio processing',description:playerState.enhanced?'Enhanced local sound':'Direct browser sound'},{value:'repeat',label:'Repeat',description:valueLabel('repeatMode')},{value:'info',label:'File details',description:'Source, format and dimensions'}],null,v=>{
  if(v==='audio')chooseDialog('Audio processing',[{value:'direct',label:'Direct',description:'Recommended. The browser plays the original audio.'},{value:'enhanced',label:'Enhanced',description:'Local media only. Uses your equalizer, balance and mono settings.'}],state.settings.audioPath,mode=>{const p=playerState;if(!p)return;const t=p.el.currentTime,playing=!p.el.paused;changeSetting('audioPath',mode);loadPlayerItem(p.item,t,playing);});
  else if(v==='repeat')openSetting('repeatMode');else if(playerState)mediaInfo(playerState.item.id);
 });
}

// Photo playback never rewrites the original. Rotation, zoom and pan are views.
function openPhoto(id,slideshow=false){
 const item=byId(id),queue=queueFor(item);
 const node=setModal(`<section class="photo-viewer" data-modal-scope role="dialog" aria-modal="true" aria-labelledby="photo-title"><div class="photo-top" data-zone="photo-top" data-layout="horizontal" data-down="photo-stage-zone">${iconButton('photo-close','close','back','Back to library')}<div><span id="photo-count"></span><h1 id="photo-title"></h1></div><span id="photo-resolution"></span></div><div class="photo-stage-wrap" data-zone="photo-stage-zone" data-layout="horizontal" data-up="photo-top" data-down="photo-tools"><div id="photo-stage" tabindex="0" data-focus role="group" aria-label="Photo. Left and right change photo. Down opens photo controls."><img id="photo-image" class="picture" alt="" draggable="false"><div id="photo-error" hidden role="status"></div></div></div><div class="photo-bottom"><div class="photo-toolbar" data-zone="photo-tools" data-layout="horizontal" data-up="photo-stage-zone" data-down="photo-tools">${iconButton('photo-prev','photo-prev','previous','Previous photo')}${btn('photo-play','photo-play',`${icon('play')}Slideshow`,'photo-tool')}${iconButton('photo-next','photo-next','next','Next photo')}<span class="photo-divider"></span>${btn('photo-rotate','photo-rotate',`${icon('rotate')}Rotate`,'photo-tool')}${btn('photo-zoom','photo-zoom',`${icon('zoom')}<span id="photo-zoom-label">Zoom</span>`,'photo-tool')}${btn('photo-fit','photo-fit','Fit','photo-tool')}${iconButton('photo-save','photo-save','heart','Save photo')}${iconButton('photo-info','photo-info','info','Photo information')}${iconButton('photo-fullscreen','fullscreen','fullscreen','Fullscreen')}</div><p class="photo-hint" id="photo-hint">← → Previous / next &nbsp; · &nbsp; ↓ Photo controls &nbsp; · &nbsp; Space Slideshow</p></div></section>`,'photo','photo-stage',()=>{clearTimeout(photoState?.timer);photoState=null;refreshContent();});
 photoState={node,queue,index:Math.max(0,queue.findIndex(x=>x.id===id)),zoom:1,rotation:0,panX:0,panY:0,playing:slideshow,timer:null,generation:0};
 loadPhoto();
}
function loadPhoto(){
 const p=photoState;if(!p)return;clearTimeout(p.timer);const item=p.queue[p.index];p.zoom=1;p.rotation=0;p.panX=p.panY=0;p.generation++;
 const generation=p.generation,img=$('#photo-image');
 img.style.opacity=0;$('#photo-error').hidden=true;$('#photo-title').textContent=item.title;$('#photo-count').textContent=`${String(p.index+1).padStart(2,'0')} / ${String(p.queue.length).padStart(2,'0')} · ${item.album||'Photos'}`;
 img.onload=()=>{if(photoState!==p||p.generation!==generation)return;item.width=img.naturalWidth;item.height=img.naturalHeight;$('#photo-resolution').textContent=`${img.naturalWidth} × ${img.naturalHeight}`;fitPhoto();img.style.opacity=1;for(const animation of img.getAnimations())animation.currentTime=0;schedulePhoto();};
 img.onerror=()=>{if(photoState!==p||p.generation!==generation)return;$('#photo-error').textContent='This photograph could not be opened. Try a JPEG, PNG, WebP or another browser-supported image.';$('#photo-error').hidden=false;clearTimeout(p.timer);p.playing=false;updatePhotoControls();};
 img.src=item.url;img.alt=item.title;updatePhotoControls();
}
function fitPhoto(){
 const p=photoState,img=$('#photo-image'),stage=$('#photo-stage');if(!p||!img?.naturalWidth||!stage)return;
 const w=img.naturalWidth,h=img.naturalHeight,rect=stage.getBoundingClientRect(),rotated=p.rotation%180!==0;
 const iw=rotated?h:w,ih=rotated?w:h,scale=state.settings.photoFit==='cover'?Math.max(rect.width/iw,rect.height/ih):Math.min(rect.width/iw,rect.height/ih);
 img.style.width=w*scale+'px';img.style.height=h*scale+'px';
 const maxX=Math.max(0,(iw*scale*p.zoom-rect.width)/2),maxY=Math.max(0,(ih*scale*p.zoom-rect.height)/2);
 p.panX=Math.max(-maxX,Math.min(maxX,p.panX));p.panY=Math.max(-maxY,Math.min(maxY,p.panY));
 img.style.transform=`translate(${p.panX}px,${p.panY}px) rotate(${p.rotation}deg) scale(${p.zoom})`;
 updatePhotoControls();
}
function updatePhotoControls(){
 const p=photoState;if(!p)return;const item=p.queue[p.index],viewer=p.node.querySelector('.photo-viewer');
 if(viewer.classList.contains('slideshow-active')!==p.playing){viewer.classList.toggle('slideshow-active',p.playing);if($('#photo-image')?.naturalWidth){fitPhoto();return;}}
 $('#photo-play').innerHTML=icon(p.playing?'pause':'play')+(p.playing?'Pause slideshow':'Slideshow');$('#photo-play').setAttribute('aria-pressed',String(p.playing));
 $('#photo-zoom-label').textContent=p.zoom===1?'Zoom':p.zoom+'×';$('#photo-fit').textContent=state.settings.photoFit==='contain'?'Fit':'Fill';
 const saved=profileData().watchlist.includes(item.id);$('#photo-save').classList.toggle('active',saved);$('#photo-save').setAttribute('aria-pressed',String(saved));
 $('#photo-hint').textContent=p.zoom>1?'↑ ↓ ← → Pan while the photo is focused · Back resets zoom':'← → Previous / next · ↓ Photo controls · Space Slideshow';
}
function schedulePhoto(){const p=photoState;if(!p)return;clearTimeout(p.timer);if(p.playing)p.timer=setTimeout(()=>{if(photoState!==p)return;if(currentDialog()?.kind!=='photo'){schedulePhoto();return;}changePhoto(1,true);},state.settings.photoInterval*1000);}
function changePhoto(delta,automatic=false){
 const p=photoState;if(!p)return;let i=p.index+delta;
 if(i<0||i>=p.queue.length){if(automatic&&!state.settings.photoRepeat){p.playing=false;updatePhotoControls();return;}i=(i+p.queue.length)%p.queue.length;}
 p.index=i;loadPhoto();
}
function toggleSlideshow(){if(!photoState)return;photoState.playing=!photoState.playing;updatePhotoControls();schedulePhoto();}

function addMedia(){
 if(currentDialog()?.kind==='import')return;
 setModal(`<div class="modal-backdrop"><section class="import-dialog" data-modal-scope role="dialog" aria-modal="true" aria-labelledby="add-title"><div class="import-art"><img src="assets/photos/deep-field.jpg" alt=""><div><span>AURA / YOUR LIBRARY</span><h2>A whole world.<br>Entirely yours.</h2><p>Bring the things you love<br>to a screen worth sharing.</p></div></div><div class="import-main"><div class="import-heading"><div><span class="context-overline">MAKE YOURSELF AT HOME</span><h2 id="add-title">Add to your library</h2></div>${iconButton('add-close','close','close','Close import')}</div><p class="import-intro">Choose videos, photographs or music. Imported copies stay on this computer, ready for your next visit.</p><input id="media-files" type="file" multiple accept="video/*,image/*,audio/*,.mkv,.m4v,.flac,.opus" hidden><input id="media-folder" type="file" multiple webkitdirectory hidden><div class="import-options" data-zone="import-options" data-layout="vertical" data-down="import-footer">${btn('choose-files','choose-files',`<span class="source-symbol">${icon('folder')}</span><span><strong>Choose files</strong><small>Videos, images and music from your device</small></span>${icon('right')}`,'import-option')}${btn('choose-folder','choose-folder',`<span class="source-symbol">${icon('grid')}</span><span><strong>Import a folder</strong><small>Keep folder names as collections</small></span>${icon('right')}`,'import-option')}${btn('add-link','add-link',`<span class="source-symbol">${icon('link')}</span><span><strong>Open a media link</strong><small>A direct video, image or audio URL</small></span>${icon('right')}`,'import-option')}</div><div id="import-status" class="import-status" aria-live="polite"><span class="privacy-dot"></span>Nothing is sent to a cloud service.</div><div id="import-progress" hidden><div class="transfer-track"><i id="transfer-fill"></i></div><span id="transfer-caption"></span></div><div id="import-errors" class="import-errors" role="status"></div><div class="import-footer" data-zone="import-footer" data-layout="horizontal" data-up="import-options"><span>Or drop files anywhere in AURA</span>${btn('import-stop','cancel-import','Stop import','btn ghost','hidden')}${btn('import-done','close','Done','btn ghost')}</div></div></section></div>`,'import','choose-files');
}
async function importFiles(files){
 if(importJob?.running)return toast('Finish the current import first.');
 const accepted=[...files].filter(kindOf),skipped=files.length-accepted.length;
 if(!accepted.length){toast('Choose supported video, image or audio files.');return;}
 if(!serverReady){try{await connect();}catch(e){toast('The local server is not connected. Start server.py, then try again.');return;}}
 if(currentDialog()?.kind!=='import')addMedia();
 const job=importJob={running:true,canceled:false,controller:new AbortController(),complete:0,errors:[]};
 $('#import-progress').hidden=false;$('#import-stop').hidden=false;$('#import-done').disabled=true;$('#add-close').disabled=true;
 for(const el of document.querySelectorAll('.import-option'))el.disabled=true;
 focusId('import-stop');
 for(let i=0;i<accepted.length&&!job.canceled;i++){
  const file=accepted[i];$('#import-status').textContent=`Importing ${i+1} of ${accepted.length} · ${file.name}`;$('#transfer-caption').textContent=formatBytes(file.size);$('#transfer-fill').style.width='0%';
  try{
   const item=await upload(file,progress=>{if($('#transfer-fill'))$('#transfer-fill').style.width=Math.round(progress*100)+'%';},job.controller.signal);job.complete++;
   const details=await probeFile(file,job.controller.signal);if(details.warning)job.errors.push(`${file.name}: saved, but a preview could not be decoded. Playback depends on browser format support.`);
   const path=file.webkitRelativePath?.split('/'),album=path?.length>1?path.at(-2):'My collection';
   try{await writeMetadata(item.id,details,album);}catch(e){job.errors.push(`${file.name}: added, but the thumbnail or details could not be saved.`);}
  }catch(e){if(e.name==='AbortError'){job.canceled=true;break;}job.errors.push(file.name+': '+e.message);}
 }
 job.running=false;await syncLibrary().catch(()=>{});refreshContent();
 if($('#import-status')){
  $('#import-status').textContent=`${job.complete} ${job.complete===1?'item':'items'} added${job.canceled?' · Import stopped':''}${skipped?` · ${skipped} unsupported files skipped`:''}.`;
  $('#import-errors').textContent=job.errors.join('\n');$('#import-stop').hidden=true;$('#import-done').disabled=false;$('#add-close').disabled=false;
  for(const el of document.querySelectorAll('.import-option'))el.disabled=false;
  focusId('import-done');
 }
 toast(`${job.complete} ${job.complete===1?'item':'items'} added to your library.`);
}
function addLink(){
 const node=setModal(`<div class="modal-backdrop"><section class="modal link-modal" data-modal-scope role="dialog" aria-modal="true" aria-labelledby="link-title"><span class="context-overline">SOMETHING WORTH WATCHING</span><h2 id="link-title">Open a media link</h2><p>Use a direct MP4, WebM, image or audio URL. Website pages, DRM services and YouTube links cannot be played here.</p><div class="form-fields" data-zone="link-fields" data-layout="vertical" data-down="link-types"><label for="media-url">Direct media URL</label><input data-focus id="media-url" type="url" placeholder="https://example.com/video.mp4" autocomplete="off"><label for="link-name">Title</label><input data-focus id="link-name" maxlength="180" placeholder="Give it a name"></div><div class="link-types" data-zone="link-types" data-layout="horizontal" data-up="link-fields" data-down="link-actions">${[['video','Video'],['photo','Photo'],['audio','Music']].map(([id,label])=>btn('link-type-'+id,'link-type',label,'chip '+(id==='video'?'active':''),`data-kind="${id}" aria-pressed="${id==='video'}"`)).join('')}</div><p id="link-error" role="status"></p><div class="actions" data-zone="link-actions" data-layout="horizontal" data-up="link-types">${btn('link-cancel','close','Cancel')}${btn('link-submit','custom-link','Add to library','btn primary')}</div><p class="small-note">Links are fetched by your browser. The provider sees your connection; the media is not copied to AURA.</p></section></div>`,'link','media-url');
 let kind='video';node.querySelectorAll('[data-action="link-type"]').forEach(e=>e.addEventListener('click',()=>{kind=e.dataset.kind;node.querySelectorAll('[data-action="link-type"]').forEach(b=>{b.classList.toggle('active',b===e);b.setAttribute('aria-pressed',String(b===e));});}));
 node.querySelector('#link-submit').addEventListener('click',()=>{
  try{const url=new URL(node.querySelector('#media-url').value.trim());if(!['http:','https:'].includes(url.protocol)||url.username||url.password)throw Error('Enter an HTTP or HTTPS media URL without credentials.');
   const title=(node.querySelector('#link-name').value.trim()||decodeURIComponent(url.pathname.split('/').at(-1))||'Media link').slice(0,180),id='r_'+mediaUUID();
   state.links.push({id,title,kind,url:url.href,poster:kind==='photo'?url.href:'',source:'link',added:Date.now()/1000,album:'Media links',name:title});save();replaceCatalog([...remoteItems,...state.links]);closeAll();navigate({video:'videos',photo:'photos',audio:'music'}[kind]);detail(id);toast('Link added.');
  }catch(e){node.querySelector('#link-error').textContent=e.message;}
 });
}
async function syncLibrary(){const result=await reloadLibrary();remoteItems=result.items;replaceCatalog([...remoteItems,...state.links]);if(result.truncated)toast('Showing the first 10,000 connected files. Use smaller media folders for the rest.');}

function selectCategory(tab,enter=false){
 if(!SETTINGS.some(c=>c.id===tab))return;
 if(tab!==settingsTab){settingsTab=tab;settingsFocusKey=null;audio.stopSample();$('#settings-panel').innerHTML=settingsPanel(tab);$('#settings-context').innerHTML=contextPanel(tab);view.querySelectorAll('.category').forEach(el=>{const selected=el.dataset.tab===tab;el.classList.toggle('selected',selected);if(selected)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});}
 if(enter){const saved=lastIn('settings-rows-'+tab);if(!saved||!$('#settings-rows').contains(document.getElementById(saved)))focusId($('#settings-rows [data-focus]')?.id);else focusId(saved);}
}
function updateContext(key=null){if(route!=='settings'||!$('#settings-context'))return;if(key)settingsFocusKey=key;$('#settings-context').innerHTML=contextPanel(settingsTab,settingsFocusKey);}
function changeSetting(key,value){
 setting(key,value);if(key==='sleepMinutes')sleepDeadline=value?Date.now()+value*60000:null;if(key==='idleMinutes')lastActivity=Date.now();
 applySettings();refreshSetting(key);updateContext();refreshQuick();
 const range=$('#adjust-range');if(range?.dataset.setting===key){range.value=state.settings[key];range.style.setProperty('--range-progress',`${(Number(range.value)-Number(range.min))/(Number(range.max)-Number(range.min))*100}%`);$('#adjust-value').textContent=valueLabel(key);range.setAttribute('aria-valuetext',valueLabel(key));}
 if(key==='photoInterval'||key==='photoRepeat')schedulePhoto();if(key==='controlsTimeout')schedulePlayerHide();
 if(!storageAvailable)toast('Preferences apply for this session. Browser storage is unavailable.');
}
function openSetting(key){
 if(!definition(key))return;
 if(SCHEMA[key]==='boolean'){changeSetting(key,!state.settings[key]);return;}
 const d=dialogForSetting(key);setModal(d.html,'setting',d.focus);applySettings();
}
function settingsRemote(key,active){
 const categories=[...document.querySelectorAll('.category')];
 if(active.classList.contains('category')){const i=categories.indexOf(active);if(key==='ArrowUp')focusId(i?categories[i-1].id:'settings-back');else if(key==='ArrowDown'&&categories[i+1])focusId(categories[i+1].id);else if(key==='ArrowRight')selectCategory(settingsTab,true);return true;}
 if(active.closest('#settings-rows')){const rows=focusables($('#settings-rows')),i=rows.indexOf(active);if(key==='ArrowLeft')focusId('settings-tab-'+settingsTab);else if(key==='ArrowRight')active.click();else if(key==='ArrowUp'&&rows[i-1])focusId(rows[i-1].id);else if(key==='ArrowDown'&&rows[i+1])focusId(rows[i+1].id);return true;}
 if(active.id==='settings-back'){if(key==='ArrowDown')focusId('settings-tab-'+settingsTab);else if(key==='ArrowUp')focusId('nav-settings');return true;}
 if(active.closest('#header')&&key==='ArrowDown'){focusId('settings-tab-'+settingsTab);return true;}return false;
}
function showVolume(){const s=state.settings,osd=$('#volume-osd');osd.innerHTML=`<strong aria-label="${s.muted?'Muted':`Volume ${s.volume}%`}">${s.muted?'Mute':s.volume}</strong><span class="volume-osd-track" aria-hidden="true"><i style="height:${s.muted?0:s.volume}%"></i></span>${icon(s.muted?'mute':'volume')}`;osd.classList.toggle('muted',s.muted);osd.classList.add('visible');clearTimeout(showVolume.timer);showVolume.timer=setTimeout(()=>osd.classList.remove('visible'),1700);}
function adjustVolume(delta){setMany({volume:Math.max(0,Math.min(100,state.settings.volume+delta)),...(delta>0?{muted:false}:{})});applySettings();refreshSetting('volume');refreshSetting('muted');updateContext();refreshQuick();showVolume();}

const QUICK_TILES=[['pictureMode','display','Picture mode'],['volume','volume','Volume'],['muted','mute','Mute'],['soundMode','spark','Sound mode'],['captions','cc','Subtitles'],['sleepMinutes','moon','Sleep timer']];
function quickTile([key,name,label]){
 const bool=SCHEMA[key]==='boolean',on=bool&&state.settings[key];
 return btn('quick-'+key,'quick-setting',`<span class="quick-icon">${icon(name)}</span><span class="quick-text"><small>${label}</small><strong>${valueLabel(key)}</strong></span>`,'quick-tile'+(on?' on':''),`data-setting="${key}" ${bool?`role="switch" aria-checked="${on}"`:'aria-haspopup="dialog"'}`);
}
function quickSettings(){
 if(currentDialog()?.kind==='quick'){back();return;}
 setModal(`<div class="modal-backdrop quick-backdrop"><section class="quick-panel" data-modal-scope role="dialog" aria-modal="true" aria-labelledby="quick-title"><div class="quick-heading"><div><span class="context-overline">${escapeHTML(currentProfile().name)} · ${dateString()}</span><h2 id="quick-title">Quick settings</h2></div><time class="quick-clock" id="quick-clock">${clockString()}</time></div><div class="quick-grid" data-zone="quick-tiles" data-layout="grid" data-down="quick-actions">${QUICK_TILES.map(quickTile).join('')}</div><div class="quick-actions" data-zone="quick-actions" data-layout="vertical" data-up="quick-tiles">${btn('quick-fullscreen','fullscreen',`${icon('fullscreen')}<span>${document.fullscreenElement?'Exit fullscreen':'Fullscreen'}</span>`,'quick-row')}${btn('quick-standby','standby',`${icon('power')}<span>Standby</span>`,'quick-row')}${btn('quick-all','navigate',`${icon('settings')}<span>All settings</span>${icon('right','sm')}`,'quick-row','data-route="settings"')}</div><p class="quick-hint"><kbd>Q</kbd> or <kbd>Back</kbd> to close</p></section></div>`,'quick','quick-pictureMode');
}
function refreshQuick(){
 for(const el of document.querySelectorAll('.quick-tile')){
  const key=el.dataset.setting;el.querySelector('strong').textContent=valueLabel(key);
  if(SCHEMA[key]==='boolean'){el.classList.toggle('on',state.settings[key]);el.setAttribute('aria-checked',String(state.settings[key]));}
 }
}
async function fullscreen(){try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch(e){toast('Fullscreen is unavailable here. Use the browser’s fullscreen command.');}}
function showStandby(){
 if(importJob?.running)return;closeAll();audio.stopSample();changeSetting('sleepMinutes',0);
 const own=visibleCatalog().filter(x=>x.kind==='photo'&&x.poster),photos=own.length?own:BUILTINS.filter(x=>x.kind==='photo'),photo=photos[Math.floor(Math.random()*photos.length)];
 setModal(`<section class="standby" data-modal-scope role="dialog" aria-modal="true" aria-label="Standby"><img class="standby-photo picture" src="${escapeHTML(photo.poster)}" alt=""><div class="standby-shade"></div><div class="standby-content"><time class="standby-clock" id="standby-clock">${clockString()}</time><p class="standby-date" id="standby-date">${dateString()}</p><p>A little pause. Your world will be here.</p><div data-zone="standby" data-layout="horizontal">${btn('wake','close',`${icon('power')}Welcome back`,'btn primary')}</div><p class="standby-note">Press any button to wake · Your computer is still running.</p></div><div class="standby-caption"><div class="brand"><span class="brand-mark">A</span>AURA</div><span>${escapeHTML(photo.title)}</span></div></section>`,'standby','wake');
}
function about(){setModal(`<div class="modal-backdrop"><section class="modal info-modal" data-modal-scope role="dialog" aria-modal="true" aria-labelledby="about-title"><div class="brand"><span class="brand-mark">A</span>AURA</div><h2 id="about-title">Your world, at home.</h2><p>AURA TV ${VERSION} · Open-source local media app.</p><p>Videos, photographs and music from your own library. Preferences and favorites are saved in this browser; imported files are saved by the local server. No analytics, accounts or subscription service.</p><p>The included collection contains three short photographic motion studies, five photographs and three original instrumental tracks. They are not full movies or live channels.</p><p class="credit-note">Photography: SpaceX; NASA; NASA / ESA / STScI; Rachel Michetti / Pikolo Espresso Bar; Stefan van der Walt. See THIRD_PARTY_NOTICES.md for source and license details. Original application and music: MIT license.</p><div class="actions" data-zone="about" data-layout="horizontal">${btn('about-close','close','Done','btn primary')}</div></section></div>`,'about','about-close');}
function exportState(){const url=URL.createObjectURL(new Blob([JSON.stringify(state,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='aura-tv-preferences.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);toast('Preferences backup requested. Media files are not included.');}
function restoreDialog(){const node=setModal(`<div class="modal-backdrop"><section class="modal compact-modal" data-modal-scope role="dialog" aria-modal="true" aria-labelledby="restore-title"><h2 id="restore-title">Restore preferences</h2><p>Replace preferences, favorites, media links and playback history for all profiles. Your imported media files are not changed.</p><input id="backup-file" type="file" accept=".json" hidden><div data-zone="restore" data-layout="horizontal" class="actions">${btn('restore-file','restore-file','Choose backup','btn primary')}${btn('restore-cancel','close','Cancel')}</div><p id="restore-message" role="status"></p></section></div>`,'restore','restore-file');node.querySelector('#backup-file').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>20*1024**2)throw Error('Choose a preferences backup smaller than 20 MB.');const text=await file.text();if(!node.isConnected)return;const next=validateState(JSON.parse(text));replaceState(next);replaceCatalog([...remoteItems,...state.links]);sleepDeadline=state.settings.sleepMinutes?Date.now()+state.settings.sleepMinutes*60000:null;closeAll();navigate('home');toast('Preferences restored.');}catch(err){node.querySelector('#restore-message').textContent='Not restored: '+err.message;}});}

async function dispatch(el){
 const action=el.dataset.action;if(!action||el.disabled)return;
 switch(action){
  case 'navigate':navigate(el.dataset.route);break;
  case 'back':back();break;
  case 'close':back();break;
  case 'detail':detail(el.dataset.id);break;
  case 'open-media':openMedia(el.dataset.id);break;
  case 'media-info':mediaInfo(el.dataset.id);break;
  case 'manage-media':manageMedia(el.dataset.id);break;
  case 'save':{const saved=toggleSaved(el.dataset.id);el.innerHTML=icon(saved?'check':'plus')+`<span>${saved?'Saved':'Save for later'}</span>`;el.setAttribute('aria-pressed',String(saved));refreshContent();toast(saved?'Added to your favorites.':'Removed from favorites.');break;}
  case 'source-filter':sourceFilter=el.dataset.value;refreshContent();focusId(el.id);break;
  case 'saved-kind':savedFilter=el.dataset.value;refreshContent();focusId(el.id);break;
  case 'sort-library':chooseDialog('Sort your library',SCHEMA.sortOrder.map(value=>({value,label:valueLabel('sortOrder',value)})),state.settings.sortOrder,v=>{changeSetting('sortOrder',v);refreshContent();});break;
  case 'album-library':{const albums=[...new Set(scopedPageItems().map(x=>x.album).filter(Boolean))].sort((a,b)=>a.localeCompare(b));chooseDialog('Choose a collection',[{value:'all',label:'All collections'},...albums.map(v=>({value:v,label:v}))],albumFilter,v=>{albumFilter=v;refreshContent();});break;}
  case 'key':{const key=el.dataset.key;if(key==='CLEAR')query='';else if(key==='DELETE')query=query.slice(0,-1);else if(query.length<120)query+=key==='SPACE'?' ':key;$('#search-input').value=query;$('#search-results').innerHTML=searchResults();break;}
  case 'add-media':addMedia();break;
  case 'quick-settings':quickSettings();break;
  case 'quick-setting':openSetting(el.dataset.setting);break;
  case 'choose-files':$('#media-files').click();break;
  case 'choose-folder':$('#media-folder').click();break;
  case 'add-link':addLink();break;
  case 'cancel-import':if(importJob){importJob.canceled=true;importJob.controller.abort();}break;
  case 'rescan':{await rescanLibrary();await syncLibrary();refreshContent();toast(folderCount?'Connected folders refreshed.':'No connected folders. Use Add media to import files.');break;}
  case 'profiles':showProfiles();break;
  case 'switch-profile':switchProfile(el.dataset.profile);closeAll();if(route==='settings')renderAll('settings-profile-'+state.profile);else navigate('home',{record:false});toast('Welcome, '+currentProfile().name+'.');break;
  case 'settings-tab':selectCategory(el.dataset.tab,true);break;
  case 'open-setting':openSetting(el.dataset.setting);break;
  case 'choose-setting':{const key=el.dataset.setting,value=SCHEMA[key].find(v=>String(v)===el.dataset.value);changeSetting(key,value);closeModal();break;}
  case 'reset-category':{const tab=settingsTab;confirmDialog('Reset '+SETTINGS.find(c=>c.id===tab).title.toLowerCase()+'?','Only this category returns to its defaults. Your files and other preferences are kept.',()=>{const patch=categoryDefaults(tab);setMany(patch);audio.stopSample();if('sleepMinutes' in patch)sleepDeadline=patch.sleepMinutes?Date.now()+patch.sleepMinutes*60000:null;if('idleMinutes' in patch)lastActivity=Date.now();if('controlsTimeout' in patch)schedulePlayerHide();if('photoInterval' in patch)schedulePhoto();refreshContent();applySettings();focusId('category-reset');},'Reset category');break;}
  case 'sound-sample':{const active=await audio.sample();const e=$('#sound-sample strong');if(e)e.textContent=active?'Stop sound sample':'Play sound sample';break;}
  case 'fullscreen':await fullscreen();break;
  case 'standby':showStandby();break;
  case 'about':about();break;
  case 'export':exportState();break;
  case 'import':restoreDialog();break;
  case 'restore-file':$('#backup-file').click();break;
  case 'clear-history':confirmDialog('Clear history?','Only '+currentProfile().name+'’s playback positions are removed. Files remain in your library.',()=>{profileData().history={};save();refreshContent();focusId('system-clear-history');},'Clear history');break;
  case 'clear-saved':confirmDialog('Clear favorites?','Only '+currentProfile().name+'’s favorites are cleared. Files remain in your library.',()=>{profileData().watchlist=[];save();refreshContent();focusId('system-clear-saved');},'Clear favorites');break;
  case 'factory-reset':confirmDialog('Reset AURA preferences?','Clear this browser’s preferences, favorites, links and history. Imported files and connected folders are not deleted.',()=>{resetAll();replaceCatalog([...remoteItems,...state.links]);closeAll();sleepDeadline=null;pageHistory=[];clearFocusMemory();navigate('home',{record:false});toast('Preferences reset. Your imported files are safe.');},'Reset preferences');break;
  case 'play-toggle':togglePlayback();break;
  case 'seek-back':seekBy(-10);break;
  case 'seek-forward':seekBy(10);break;
  case 'player-previous':nextPlayer(-1);break;
  case 'player-next':nextPlayer(1);break;
  case 'player-volume':openSetting('volume');break;
  case 'player-fit':changeSetting('videoFit',state.settings.videoFit==='contain'?'cover':'contain');break;
  case 'cycle-speed':{const opts=SCHEMA.playbackRate;changeSetting('playbackRate',opts[(opts.indexOf(state.settings.playbackRate)+1)%opts.length]);break;}
  case 'player-options':playerOptions();break;
  case 'subtitles':subtitleDialog();break;
  case 'subtitle-open':$('#subtitle-file').click();break;
  case 'subtitle-toggle':changeSetting('captions',!state.settings.captions);el.textContent=state.settings.captions?'Turn subtitles off':'Turn subtitles on';break;
  case 'subtitle-clear':playerState.cues=[];playerState.subtitleName='';$('#subtitle-message').textContent='Subtitles removed.';updatePlayer();break;
  case 'start-slideshow':if(pageItems().length)openPhoto(pageItems()[0].id,true);break;
  case 'photo-prev':changePhoto(-1);break;
  case 'photo-next':changePhoto(1);break;
  case 'photo-play':toggleSlideshow();break;
  case 'photo-rotate':photoState.rotation=(photoState.rotation+90)%360;fitPhoto();break;
  case 'photo-zoom':{const opts=[1,1.5,2,3];photoState.zoom=opts[(opts.indexOf(photoState.zoom)+1)%opts.length];fitPhoto();focusId('photo-stage');break;}
  case 'photo-fit':changeSetting('photoFit',state.settings.photoFit==='contain'?'cover':'contain');break;
  case 'photo-save':toggleSaved(photoState.queue[photoState.index].id);updatePhotoControls();break;
  case 'photo-info':mediaInfo(photoState.queue[photoState.index].id);break;
 }
}

// One delegated remote handler. Destructive actions reject key repeats.
document.addEventListener('pointerdown',e=>{lastActivity=Date.now();if(e.isTrusted)audio.unlock();},true);
document.addEventListener('pointermove',()=>{lastActivity=Date.now();if(currentDialog()?.kind==='player')showPlayerControls();});
document.addEventListener('click',e=>{if(currentDialog()?.kind==='standby'&&!e.target.closest('[data-action]')){back();return;}if(currentDialog()?.kind==='player'){showPlayerControls();if(e.target.id==='media-element'){togglePlayback();return;}}const el=e.target.closest('[data-action]');if(el)dispatch(el).catch(handleError);});
document.addEventListener('focusin',e=>{
 const el=e.target;if(!el.matches('[data-focus]'))return;rememberFocus(el);audio.navigation();focusAmbient(el);
 if(route==='settings'&&!dialogs.length){if(el.classList.contains('category'))selectCategory(el.dataset.tab);if(el.dataset.setting)updateContext(el.dataset.setting);}
});
document.addEventListener('input',e=>{const el=e.target;if(el.id==='search-input'){query=el.value.slice(0,120);$('#search-results').innerHTML=searchResults();}else if(el.id==='adjust-range')changeSetting(el.dataset.setting,Number(el.value));else if(el.id==='player-seek'&&playerState){playerState.el.currentTime=Number(el.value);updatePlayer();}});
document.addEventListener('change',e=>{if(['media-files','media-folder'].includes(e.target.id)&&e.target.files.length){const files=[...e.target.files];e.target.value='';importFiles(files).catch(handleError);}});
document.addEventListener('dragover',e=>{if(e.dataTransfer?.types.includes('Files')){e.preventDefault();document.body.classList.add('file-drag');}});
document.addEventListener('dragleave',e=>{if(!e.relatedTarget)document.body.classList.remove('file-drag');});
document.addEventListener('drop',e=>{document.body.classList.remove('file-drag');if(e.dataTransfer?.files.length){e.preventDefault();if(playerState||photoState){toast('Close playback before importing files.');return;}importFiles([...e.dataTransfer.files]).catch(handleError);}});
document.addEventListener('keydown',event=>{
 if(event.ctrlKey||event.metaKey||event.altKey)return;
 const codes={13:'Enter',37:'ArrowLeft',38:'ArrowUp',39:'ArrowRight',40:'ArrowDown',461:'BrowserBack',10009:'BrowserBack',415:'MediaPlay',19:'MediaPause',413:'MediaStop'};
 const key=event.key&&event.key!=='Unidentified'?event.key:codes[event.keyCode];if(!key)return;
 const active=document.activeElement,isText=active?.matches('input:not([type="range"]):not([type="file"]),textarea');lastActivity=Date.now();if(event.isTrusted)audio.unlock();
 if(event.repeat){if(['Enter',' ','Escape','BrowserBack','Backspace'].includes(key)&&!isText){event.preventDefault();return;}if(key.startsWith('Arrow')&&Date.now()-heldKeyAt<90){event.preventDefault();return;}}heldKeyAt=Date.now();
 if(key==='Tab'){trapTab(event);return;}
 if(currentDialog()?.kind==='standby'&&!['Shift','Control','Alt','Meta','CapsLock'].includes(key)){event.preventDefault();back();return;}
 if(currentDialog()?.kind==='player'){
  if(playerState.hidden&&['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Enter'].includes(key)){event.preventDefault();showPlayerControls();return;}
  if(key.startsWith('Arrow')||key==='Enter')showPlayerControls();
 }
 if(key.startsWith('Arrow')){
  if(isText&&['ArrowLeft','ArrowRight'].includes(key))return;
  event.preventDefault();
  if(active.id==='photo-stage'){
   if(photoState.zoom>1){const d=70;if(key==='ArrowLeft')photoState.panX+=d;if(key==='ArrowRight')photoState.panX-=d;if(key==='ArrowUp')photoState.panY+=d;if(key==='ArrowDown')photoState.panY-=d;fitPhoto();}
   else if(key==='ArrowLeft')changePhoto(-1);else if(key==='ArrowRight')changePhoto(1);else move(key);return;
  }
  if(active?.matches('input[type="range"]')&&['ArrowLeft','ArrowRight'].includes(key)){
   active.value=Math.max(Number(active.min),Math.min(Number(active.max),Number(active.value)+(key==='ArrowLeft'?-1:1)*(Number(active.dataset.step||active.step)||1)));active.dispatchEvent(new Event('input',{bubbles:true}));return;
  }
  if(route==='settings'&&!dialogs.length&&settingsRemote(key,active))return;
  move(key);return;
 }
 if(['Escape','BrowserBack','GoBack'].includes(key)||(key==='Backspace'&&!isText)){event.preventDefault();back();return;}
 if(isText){if(key==='Enter'&&active.id==='search-input'){event.preventDefault();focusId('key-A');}return;}
 if(key==='Enter'){event.preventDefault();if(active.id==='photo-stage'){focusId('photo-play');return;}if(active.matches('button'))active.click();return;}
 if(['m','M','AudioVolumeMute'].includes(key)){event.preventDefault();changeSetting('muted',!state.settings.muted);showVolume();return;}
 if(['+','=','AudioVolumeUp'].includes(key)){event.preventDefault();adjustVolume(5);return;}
 if(['-','_','AudioVolumeDown'].includes(key)){event.preventDefault();adjustVolume(-5);return;}
 if(['q','Q'].includes(key)&&(!dialogs.length||['player','photo','quick'].includes(currentDialog().kind))){event.preventDefault();quickSettings();return;}
 if(key===' '&&currentDialog()?.kind!=='player'&&currentDialog()?.kind!=='photo')return;
 if([' ','MediaPlayPause','MediaPlay','MediaPause'].includes(key)){
  if(currentDialog()?.kind==='photo'){event.preventDefault();toggleSlideshow();}
  else if(playerState){event.preventDefault();if(key==='MediaPlay')safePlay();else if(key==='MediaPause'){playerState.wantsPlay=false;playerState.el.pause();}else togglePlayback();}return;
 }
 if(key==='MediaTrackNext'){event.preventDefault();if(photoState)changePhoto(1);else nextPlayer(1);return;}
 if(key==='MediaTrackPrevious'){event.preventDefault();if(photoState)changePhoto(-1);else nextPlayer(-1);return;}
 if(key==='MediaStop'&&(playerState||photoState)){event.preventDefault();closeAll();return;}
 if(!dialogs.length){if(['s','S'].includes(key)){event.preventDefault();navigate('settings');}else if(key==='/'){event.preventDefault();navigate('search');}else if(key==='Home'&&!active.matches('input')){event.preventDefault();navigate('home');}else if(['o','O'].includes(key)){event.preventDefault();addMedia();}}
});
window.addEventListener('resize',()=>{if(photoState)fitPhoto();});
view.addEventListener('scroll',()=>document.body.classList.toggle('view-scrolled',view.scrollTop>120),{passive:true});
document.addEventListener('fullscreenchange',()=>{const label=$('#system-fullscreen .setting-text strong');if(label)label.textContent=document.fullscreenElement?'Exit fullscreen':'Enter fullscreen';const quick=$('#quick-fullscreen span');if(quick)quick.textContent=document.fullscreenElement?'Exit fullscreen':'Fullscreen';if(photoState)fitPhoto();});
window.addEventListener('beforeunload',()=>{if(playerState)remember(playerState.item.id,playerState.el.currentTime,playerState.el.duration);});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&playerState)remember(playerState.item.id,playerState.el.currentTime,playerState.el.duration);});
setInterval(()=>{
 const now=clockString();
 for(const id of ['header-clock','standby-clock','player-clock','quick-clock']){const el=document.getElementById(id);if(el&&el.textContent!==now)el.textContent=now;}
 if($('#standby-date'))$('#standby-date').textContent=dateString();
 updateStatus();
 if(sleepDeadline&&Date.now()>=sleepDeadline)showStandby();
 const busy=playerState&&!playerState.el.paused||photoState?.playing||importJob?.running;
 if(busy)lastActivity=Date.now();
 if(state.settings.idleMinutes&&!busy&&currentDialog()?.kind!=='standby'&&Date.now()-lastActivity>=state.settings.idleMinutes*60000)showStandby();
 if(route==='settings'&&settingsTab==='sound'&&!dialogs.length){
  const level=audio.level();document.querySelectorAll('.sound-bars i').forEach((bar,i)=>bar.style.height=(8+Math.min(85,level*650)*(0.4+Math.abs(Math.sin(i*.8))))+'%');
  if($('#sound-sample strong')&&audio.sampleUntil<Date.now())$('#sound-sample strong').textContent='Play sound sample';
 }
},350);
$('#boot')?.addEventListener('animationend',e=>{if(e.animationName==='boot-out')e.currentTarget.remove();});
replaceCatalog([...state.links]);renderAll(defaultFocus());
if(storageRecovered)toast('Some saved preferences were repaired. Your valid favorites and history were kept.');
connect().then(result=>{remoteItems=result.items;replaceCatalog([...remoteItems,...state.links]);refreshContent();if(result.truncated)toast('The connected library is limited to 10,000 files.');}).catch(()=>toast('Local media server unavailable. AURA will reconnect when server.py is running.'));
setInterval(async()=>{
 if(document.hidden)return;
 const wasReady=serverReady,alive=await heartbeat();
 if(alive&&!wasReady){
  try{const result=await connect();remoteItems=result.items;replaceCatalog([...remoteItems,...state.links]);refreshContent();toast('Reconnected to your library.');}catch{/* The next heartbeat retries. */}
 }
 updateStatus();
},15000);
