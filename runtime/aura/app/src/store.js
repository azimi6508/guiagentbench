import {DEFAULT_SETTINGS,validateSettings,PROFILES,byId,CATALOG} from './data.js';

export const STORAGE_KEY='aura-tv.v3';
export let storageAvailable=true;
export let storageRecovered=false;
const MAX_ENTRIES=10000;
const isRecord=value=>Boolean(value)&&typeof value==='object'&&!Array.isArray(value);
const isId=id=>typeof id==='string'&&/^(?:[vap]-[a-z0-9-]+|[um]_[a-f0-9]{32}|r_[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$/.test(id);
const isTimestamp=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=1e14;

export const fresh=()=>({version:3,settings:{...DEFAULT_SETTINGS},profile:'alex',profiles:Object.fromEntries(PROFILES.map(p=>[p.id,{watchlist:[],history:{}}])),links:[]});

function historyEntry(id,entry){
 if(!isId(id)||!isRecord(entry))throw Error('Invalid playback position.');
 if(!['time','duration','updated'].every(key=>isTimestamp(entry[key]))||entry.duration<=0||entry.time>entry.duration)throw Error('Invalid playback history.');
 return {time:entry.time,duration:entry.duration,updated:entry.updated};
}

function mediaLink(link){
 if(!isRecord(link)||!isId(link.id)||!link.id.startsWith('r_')||typeof link.title!=='string'||!link.title.trim()||link.title.length>180||!['video','photo','audio'].includes(link.kind)||typeof link.url!=='string')throw Error('Invalid media link.');
 const url=new URL(link.url);
 if(!['https:','http:'].includes(url.protocol)||url.username||url.password)throw Error('Only HTTP(S) media links without credentials are supported.');
 const added=link.added===undefined?0:link.added;
 if(!isTimestamp(added))throw Error('Invalid media link date.');
 return {id:link.id,title:link.title.trim(),kind:link.kind,url:url.href,poster:link.kind==='photo'?url.href:'',name:link.title.trim(),source:'link',added,album:'Media links'};
}

/** Backup imports are validated completely before any state is replaced. */
export function validateState(raw){
 if(!isRecord(raw)||raw.version!==3||!PROFILES.some(p=>p.id===raw.profile))throw Error('Choose an AURA 3 preferences backup.');
 const settings=validateSettings(raw.settings,{strict:true}),profiles={};
 for(const p of PROFILES){
  const value=raw.profiles?.[p.id];
  if(!isRecord(value)||!Array.isArray(value.watchlist)||value.watchlist.length>MAX_ENTRIES||!isRecord(value.history)||Object.keys(value.history).length>MAX_ENTRIES)throw Error('Invalid profile data.');
  if(value.watchlist.some(id=>!isId(id)))throw Error('Invalid saved media.');
  const history={};
  for(const[id,entry]of Object.entries(value.history))history[id]=historyEntry(id,entry);
  profiles[p.id]={watchlist:[...new Set(value.watchlist)],history};
 }
 if(!Array.isArray(raw.links)||raw.links.length>MAX_ENTRIES)throw Error('Invalid media links.');
 const links=[],linkIds=new Set();
 for(const link of raw.links){
  const valid=mediaLink(link);
  if(linkIds.has(valid.id))throw Error('Invalid or duplicate media link.');
  linkIds.add(valid.id);links.push(valid);
 }
 return {version:3,settings,profiles,profile:raw.profile,links};
}

/** A damaged local field must not discard every profile and preference.
 * This recovery is only for the browser's own stored state; imported backups
 * always use the strict validator above.
 */
function recoverStoredState(raw){
 const next=fresh();
 if(!isRecord(raw)||raw.version!==3)return next;
 if(isRecord(raw.settings)){
  const known=Object.fromEntries(Object.keys(DEFAULT_SETTINGS).filter(key=>Object.hasOwn(raw.settings,key)).map(key=>[key,raw.settings[key]]));
  next.settings=validateSettings(known);
 }
 if(PROFILES.some(p=>p.id===raw.profile))next.profile=raw.profile;
 for(const p of PROFILES){
  const value=raw.profiles?.[p.id];
  if(!isRecord(value))continue;
  if(Array.isArray(value.watchlist))next.profiles[p.id].watchlist=[...new Set(value.watchlist.filter(isId))].slice(0,MAX_ENTRIES);
  if(isRecord(value.history))for(const[id,entry]of Object.entries(value.history).slice(0,MAX_ENTRIES)){
   try{next.profiles[p.id].history[id]=historyEntry(id,entry);}catch{/* Keep other valid positions. */}
  }
 }
 const ids=new Set();
 if(Array.isArray(raw.links))for(const link of raw.links.slice(0,MAX_ENTRIES)){
  try{const valid=mediaLink(link);if(!ids.has(valid.id)){ids.add(valid.id);next.links.push(valid);}}catch{/* Keep other valid media links. */}
 }
 return next;
}

let initial=fresh(),rewriteStoredState=false;
try{
 const current=localStorage.getItem(STORAGE_KEY);
 if(current){
  let raw;
  try{raw=JSON.parse(current);initial=validateState(raw);}
  catch{initial=recoverStoredState(raw);storageRecovered=true;rewriteStoredState=true;}
 }else{
  let old;
  try{old=JSON.parse(localStorage.getItem('aura-tv.v2')||localStorage.getItem('aura-tv.v1')||'null');}catch{/* Unreadable legacy preferences do not block a fresh launch. */}
  if(isRecord(old?.settings)){
   const known=Object.fromEntries(Object.keys(DEFAULT_SETTINGS).filter(key=>Object.hasOwn(old.settings,key)).map(key=>[key,old.settings[key]]));
   initial.settings=validateSettings({...known,audioPath:'direct'});
   if(PROFILES.some(p=>p.id===old.profile))initial.profile=old.profile;
   rewriteStoredState=true;
  }
 }
}catch{storageAvailable=false;}

export let state=initial;
export function save(){try{localStorage.setItem(STORAGE_KEY,JSON.stringify(state));storageAvailable=true;}catch{storageAvailable=false;}}
if(rewriteStoredState)save();

export function replaceState(next){state=validateState(next);save();}
export function setting(key,value){state.settings=validateSettings({...state.settings,[key]:value},{strict:true});save();}
export function setMany(patch){state.settings=validateSettings({...state.settings,...patch},{strict:true});save();}
export const profileData=()=>state.profiles[state.profile];
export const currentProfile=()=>PROFILES.find(p=>p.id===state.profile);
export const allowed=item=>Boolean(item);
export const visibleCatalog=()=>CATALOG.filter(x=>state.settings.showSamples||x.source!=='included');
export function toggleSaved(id){if(!isId(id)||!byId(id))return false;const p=profileData();p.watchlist=p.watchlist.includes(id)?p.watchlist.filter(x=>x!==id):[...p.watchlist,id];save();return p.watchlist.includes(id);}
export function remember(id,time,duration){
 if(!isId(id)||!state.settings.rememberHistory||!Number.isFinite(time)||!isTimestamp(duration)||duration<=0)return;
 const history=profileData().history;
 history[id]={time:Math.max(0,Math.min(duration,time)),duration,updated:Date.now()};
 if(Object.keys(history).length>MAX_ENTRIES){const oldest=Object.keys(history).sort((a,b)=>history[a].updated-history[b].updated)[0];delete history[oldest];}
 save();
}
export function forgetMedia(id){for(const p of Object.values(state.profiles)){p.watchlist=p.watchlist.filter(x=>x!==id);delete p.history[id];}state.links=state.links.filter(x=>x.id!==id);save();}
export function switchProfile(id){if(!PROFILES.some(p=>p.id===id))throw Error('Unknown profile.');state.profile=id;save();}
export function resetAll(){state=fresh();save();for(const key of ['aura-tv.v2','aura-tv.v1'])try{localStorage.removeItem(key);}catch{/* Only AURA keys are changed. */}}
