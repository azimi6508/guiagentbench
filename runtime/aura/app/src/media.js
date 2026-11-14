/** Local library transport. Files stay on the local Python service.
 * Preview decoding is optional and never prevents a completed import.
 */
let token='';
let sessionRequest=null;
let connectionRequest=null;
export let serverReady=false;
export let folderCount=0;
export let maxUpload=8*1024**3;

const aborted=()=>new DOMException('Import canceled.','AbortError');
const errorWithStatus=(message,status=0,code='')=>Object.assign(Error(message),{status,code});

async function requestJSON(path,options={}){
 const controller=new AbortController(),originalSignal=options.signal;
 let timedOut=false;
 const abort=()=>controller.abort();
 if(originalSignal?.aborted)throw aborted();
 originalSignal?.addEventListener('abort',abort,{once:true});
 const timer=setTimeout(()=>{timedOut=true;controller.abort();},path==='/api/rescan'?90000:15000);
 const method=(options.method||'GET').toUpperCase(),headers=new Headers(options.headers);
 if(!['GET','HEAD'].includes(method))headers.set('X-Aura-Token',token);
 try{
  const response=await fetch(path,{...options,method,headers,signal:controller.signal,cache:'no-store'});
  let payload;
  try{payload=await response.json();}
  catch(error){
   if(controller.signal.aborted)throw error;
   throw errorWithStatus('The local media server returned an unreadable response. Start server.py and try again.',response.status);
  }
  if(!payload||typeof payload!=='object'||Array.isArray(payload))throw errorWithStatus('The local media server returned an invalid response.',response.status);
  if(!response.ok)throw errorWithStatus(payload.error||`Request failed (${response.status}).`,response.status,payload.code||'');
  return payload;
 }catch(error){
  if(originalSignal?.aborted)throw aborted();
  if(timedOut){serverReady=false;throw Error('The local media server took too long to respond. Check that server.py is running and try again.');}
  if(error.status)throw error;
  serverReady=false;
  throw Error('Connection lost. Check that the local server is running, then try again.');
 }finally{
  clearTimeout(timer);originalSignal?.removeEventListener('abort',abort);
 }
}

async function establishSession(){
 if(!sessionRequest)sessionRequest=(async()=>{
  const info=await requestJSON('/api/bootstrap');
  if(typeof info.token!=='string'||!info.token||!Number.isSafeInteger(info.maxUpload)||info.maxUpload<=0||!Number.isInteger(info.folderCount)||info.folderCount<0){
   serverReady=false;throw Error('The local media service is not ready. Start server.py and try again.');
  }
  token=info.token;maxUpload=info.maxUpload;folderCount=info.folderCount;
  return info;
 })().finally(()=>{sessionRequest=null;});
 return sessionRequest;
}

function sessionExpired(error){
 return error.status===403&&(error.code==='session_expired'||/^Session expired\./.test(error.message));
}

export async function api(path,options={}){
 const isWrite=!['GET','HEAD'].includes((options.method||'GET').toUpperCase());
 if(isWrite&&!token)await establishSession();
 try{return await requestJSON(path,options);}
 catch(error){
  // A rejected token means the operation did not run. Refresh it once after a
  // server restart; never replay a write after an ambiguous network failure.
  if(!isWrite||!sessionExpired(error))throw error;
  await establishSession();
  return requestJSON(path,options);
 }
}

function libraryPayload(result){
 if(!Array.isArray(result.items)){
  serverReady=false;throw Error('The local library could not be read. Check the server and try again.');
 }
 if(Number.isInteger(result.folderCount)&&result.folderCount>=0)folderCount=result.folderCount;
 serverReady=true;
 return result;
}

export async function connect(){
 if(!connectionRequest)connectionRequest=(async()=>{
  try{await establishSession();return libraryPayload(await requestJSON('/api/library'));}
  catch(error){serverReady=false;throw error;}
 })().finally(()=>{connectionRequest=null;});
 return connectionRequest;
}
export async function heartbeat(){
 try{
  const response=await fetch('/health',{cache:'no-store',signal:AbortSignal.timeout(5000)});
  if(!response.ok)throw Error('Unhealthy');
  return true;
 }catch{serverReady=false;return false;}
}
export const reloadLibrary=async()=>libraryPayload(await api('/api/library'));
export const rescanLibrary=async()=>libraryPayload(await api('/api/rescan',{method:'POST'}));
export const deleteMedia=id=>api('/api/media/'+id,{method:'DELETE'});

export function kindOf(file){
 const ext=typeof file?.name==='string'?file.name.split('.').pop().toLowerCase():'';
 if(['jpg','jpeg','png','webp','gif','avif','bmp'].includes(ext))return 'photo';
 if(['mp4','m4v','webm','ogv','mov','mkv'].includes(ext))return 'video';
 if(['mp3','m4a','wav','ogg','flac','opus'].includes(ext))return 'audio';
 return null;
}

function sendUpload(file,onProgress,signal){
 return new Promise((resolve,reject)=>{
  if(signal?.aborted)return reject(aborted());
  const xhr=new XMLHttpRequest();
  let stallTimer,settled=false;
  const cancel=()=>xhr.abort();
  const finish=(error,item)=>{
   if(settled)return;
   settled=true;clearTimeout(stallTimer);signal?.removeEventListener('abort',cancel);
   xhr.onload=xhr.onerror=xhr.onabort=xhr.ontimeout=null;xhr.upload.onprogress=null;
   error?reject(error):resolve(item);
  };
  const resetStallTimer=()=>{
   clearTimeout(stallTimer);
   stallTimer=setTimeout(()=>{
    serverReady=false;finish(Error('Import stalled. Check the local server and available disk space, then try again.'));xhr.abort();
   },90000);
  };
  xhr.open('PUT','/api/media');
  xhr.setRequestHeader('X-Aura-Token',token);xhr.setRequestHeader('X-File-Name',encodeURIComponent(file.name));
  xhr.setRequestHeader('Content-Type','application/octet-stream');
  xhr.upload.onprogress=event=>{resetStallTimer();if(event.lengthComputable)onProgress(Math.min(1,event.loaded/event.total));};
  xhr.onload=()=>{
   let data;
   try{data=JSON.parse(xhr.responseText);}catch{finish(Error('The server returned an unreadable response. Refresh the library before retrying the import.'));return;}
   if(xhr.status<200||xhr.status>=300){finish(errorWithStatus(data?.error||'Import failed.',xhr.status,data?.code||''));return;}
   if(!data?.item?.id){finish(Error('The server did not confirm this import. Refresh the library before trying again.'));return;}
   finish(null,data.item);
  };
  xhr.onerror=()=>{serverReady=false;finish(Error('Connection lost. Check that the local server is running.'));};
  xhr.ontimeout=()=>{serverReady=false;finish(Error('Import timed out. Check that the local server is running.'));};
  xhr.onabort=()=>finish(aborted());
  signal?.addEventListener('abort',cancel,{once:true});
  resetStallTimer();
  try{xhr.send(file);}catch(error){finish(error);}
 });
}

export async function upload(file,onProgress=()=>{},signal){
 if(signal?.aborted)throw aborted();
 if(!kindOf(file))throw Error('This file type is not supported.');
 if(!serverReady)await connect();
 if(signal?.aborted)throw aborted();
 if(!file.size||file.size>maxUpload)throw Error(`Choose a non-empty file no larger than ${formatBytes(maxUpload)}.`);
 try{return await sendUpload(file,onProgress,signal);}
 catch(error){
  if(!sessionExpired(error)||signal?.aborted)throw error;
  await establishSession();
  return sendUpload(file,onProgress,signal);
 }
}

function waitForMedia(el,event,begin,{signal,timeout=7000}={}){
 return new Promise((resolve,reject)=>{
  if(signal?.aborted){reject(aborted());return;}
  let timer;
  const finish=error=>{
   clearTimeout(timer);el.removeEventListener(event,ready);el.removeEventListener('error',failed);signal?.removeEventListener('abort',cancel);
   error?reject(error):resolve();
  };
  const ready=()=>finish(),failed=()=>finish(Error('A preview could not be decoded.')),cancel=()=>finish(aborted());
  el.addEventListener(event,ready,{once:true});el.addEventListener('error',failed,{once:true});signal?.addEventListener('abort',cancel,{once:true});
  timer=setTimeout(()=>finish(Error('Media preview timed out.')),timeout);
  try{begin();}catch(error){finish(error);}
 });
}

export async function probeFile(file,signal){
 if(signal?.aborted)throw aborted();
 const kind=kindOf(file);
 if(!kind)return {warning:'This file type is not supported.'};
 const url=URL.createObjectURL(file),el=document.createElement(kind==='photo'?'img':kind==='audio'?'audio':'video'),result={};
 try{
  if(kind==='photo'){
   await waitForMedia(el,'load',()=>{el.src=url;},{signal});
   result.width=el.naturalWidth;result.height=el.naturalHeight;
  }else{
   el.preload=kind==='video'?'auto':'metadata';el.muted=true;el.playsInline=true;
   await waitForMedia(el,'loadedmetadata',()=>{el.src=url;},{signal});
   if(Number.isFinite(el.duration))result.duration=el.duration;
   if(kind==='video'){
    result.width=el.videoWidth;result.height=el.videoHeight;
    const time=Number.isFinite(el.duration)&&el.duration>0?Math.min(el.duration*.15,4):0;
    if(time>0)await waitForMedia(el,'seeked',()=>{el.currentTime=time;},{signal,timeout:4000});
    else if(el.readyState<2)await waitForMedia(el,'loadeddata',()=>{},{signal,timeout:4000});
   }
  }
  if(kind!=='audio'&&result.width&&result.height){
   const canvas=document.createElement('canvas'),scale=Math.min(1,640/result.width,400/result.height);
   canvas.width=Math.max(1,Math.round(result.width*scale));canvas.height=Math.max(1,Math.round(result.height*scale));
   const context=canvas.getContext('2d');
   if(context){context.drawImage(el,0,0,canvas.width,canvas.height);result.thumbnail=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.82));}
  }
  if(signal?.aborted)throw aborted();
 }catch(error){if(error.name==='AbortError')throw error;result.warning=error.message;}
 finally{
  el.removeAttribute('src');if(el.load)el.load();URL.revokeObjectURL(url);
 }
 return result;
}

export async function writeMetadata(id,details,album){
 const{thumbnail,warning,...meta}=details;if(album)meta.album=album.slice(0,180);
 if(Object.keys(meta).length)await api(`/api/media/${id}/metadata`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(meta)});
 if(thumbnail)await api(`/api/media/${id}/thumbnail`,{method:'PUT',headers:{'Content-Type':'image/jpeg'},body:thumbnail});
}

/** Prefer declared sources a browser can decode, retaining unknown sources as
 * fallbacks because canPlayType is advisory. Imported files keep their own URL.
 */
export function mediaSources(item,element){
 const declared=Array.isArray(item.sources)&&item.sources.length?item.sources:[{url:item.url,type:item.mime||''}];
 const seen=new Set();
 const sources=declared.filter(source=>{
  if(!source||typeof source.url!=='string'||!source.url||seen.has(source.url))return false;
  seen.add(source.url);return true;
 }).map((source,index)=>({...source,index,supported:!!(source.type&&element?.canPlayType?.(source.type))}));
 return sources.sort((a,b)=>Number(b.supported)-Number(a.supported)||a.index-b.index).map(({index,supported,...source})=>source);
}

export function formatTime(t){if(!Number.isFinite(t)||t<0)return '—';const n=Math.floor(t),s=String(n%60).padStart(2,'0'),m=Math.floor(n/60);return m>=60?`${Math.floor(m/60)}:${String(m%60).padStart(2,'0')}:${s}`:`${m}:${s}`;}
export function formatBytes(bytes){if(!Number.isFinite(bytes)||bytes<0)return '';const units=['B','KB','MB','GB','TB'];let i=0;while(bytes>=1024&&i<units.length-1){bytes/=1024;i++;}return `${bytes.toFixed(i>1?1:0)} ${units[i]}`;}

export function parseSubtitles(text){
 // SRT/WebVTT text is always rendered with textContent, never as HTML.
 if(typeof text!=='string')return [];
 const blocks=text.replace(/^\uFEFF/,'').replace(/\r\n?/g,'\n').split(/\n[\t ]*\n+/),cues=[];
 const seconds=value=>{
  const parts=value.replace(',','.').split(':').map(Number),secs=parts.at(-1),minutes=parts.at(-2);
  if(parts.some(part=>!Number.isFinite(part))||secs>=60||minutes>=60)return NaN;
  return parts.length===3?parts[0]*3600+minutes*60+secs:minutes*60+secs;
 };
 const entities={amp:'&',lt:'<',gt:'>',quot:'"',apos:"'",nbsp:' ',lrm:'\u200e',rlm:'\u200f'};
 const cueText=value=>value.replace(/<[^>]*>/g,'').replace(/&(#x[\da-f]+|#\d+|amp|lt|gt|quot|apos|nbsp|lrm|rlm);/gi,(whole,name)=>{
  if(name[0]!=='#')return entities[name.toLowerCase()]??whole;
  const number=name[1].toLowerCase()==='x'?parseInt(name.slice(2),16):Number(name.slice(1));
  return number>0&&number<=0x10ffff&&!(number>=0xd800&&number<=0xdfff)?String.fromCodePoint(number):whole;
 }).trim().slice(0,2000);
 for(const block of blocks){
  const lines=block.trim().split('\n');if(/^(?:NOTE(?:\s|$)|STYLE$|REGION$)/.test(lines[0]))continue;
  const i=lines.findIndex(line=>line.includes('-->'));if(i<0)continue;
  const match=lines[i].match(/^\s*((?:\d+:)?\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d+:)?\d{2}:\d{2}[.,]\d{1,3})(?:\s|$)/);if(!match)continue;
  const start=seconds(match[1]),end=seconds(match[2]),content=cueText(lines.slice(i+1).join('\n'));
  if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start||!content)continue;
  cues.push({start,end,text:content});
  if(cues.length>=10000)break;
 }
 return cues.sort((a,b)=>a.start-b.start);
}
