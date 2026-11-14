/** Client transport/format regression checks. Browser decoding is covered by
 * the HTTP browser suite; these mocks exercise failures without a live server.
 */
import test,{afterEach} from 'node:test';
import assert from 'node:assert/strict';

const realFetch=globalThis.fetch,realXHR=globalThis.XMLHttpRequest;
let serial=0;
const media=()=>import(`../src/media.js?transport-test=${++serial}`);
const json=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
const bootstrap=(token='initial')=>({token,maxUpload:8*1024**3,folderCount:1});
afterEach(()=>{globalThis.fetch=realFetch;if(realXHR===undefined)delete globalThis.XMLHttpRequest;else globalThis.XMLHttpRequest=realXHR;});

test('connection stays unavailable if the library read fails',async()=>{
 const m=await media();
 globalThis.fetch=async path=>path==='/api/bootstrap'?json(bootstrap()):json({error:'Database unavailable'},503);
 await assert.rejects(m.connect(),/Database unavailable/);assert.equal(m.serverReady,false);
 globalThis.fetch=async path=>json(path==='/api/bootstrap'?bootstrap():{items:[],folderCount:2});
 assert.deepEqual((await m.connect()).items,[]);assert.equal(m.serverReady,true);assert.equal(m.folderCount,2);
});

test('unrelated HTML server and malformed library are rejected',async()=>{
 const m=await media();
 globalThis.fetch=async()=>new Response('<html>A different service</html>');
 await assert.rejects(m.connect(),/unreadable/);assert.equal(m.serverReady,false);
 globalThis.fetch=async path=>json(path==='/api/bootstrap'?bootstrap():{other:[]});
 await assert.rejects(m.connect(),/library could not be read/);assert.equal(m.serverReady,false);
});

test('concurrent connects share one bootstrap and catalog request',async()=>{
 const m=await media(),calls=[];
 globalThis.fetch=async path=>{calls.push(path);return json(path==='/api/bootstrap'?bootstrap():{items:[]});};
 await Promise.all([m.connect(),m.connect(),m.connect()]);
 assert.deepEqual(calls,['/api/bootstrap','/api/library']);
});

test('expired session refreshes once and preserves Headers and request body',async()=>{
 const m=await media(),writes=[],calls=[];let token='initial';
 globalThis.fetch=async(path,options)=>{
  calls.push(path);
  if(path==='/api/bootstrap')return json(bootstrap(token));
  if(path==='/api/library')return json({items:[]});
  writes.push(options);return options.headers.get('X-Aura-Token')===token?json({ok:true}):json({error:'Session expired.',code:'session_expired'},403);
 };
 await m.connect();token='restarted';
 assert.deepEqual(await m.api('/api/media/u_test/metadata',{method:'put',headers:new Headers({'Content-Type':'application/json'}),body:'{"title":"A new title"}'}),{ok:true});
 assert.equal(writes.length,2);assert.equal(writes[1].headers.get('X-Aura-Token'),'restarted');assert.equal(writes[1].headers.get('Content-Type'),'application/json');assert.equal(writes[1].body,'{"title":"A new title"}');assert.equal(calls.filter(x=>x==='/api/bootstrap').length,2);
});

test('cross-origin rejection is not retried and ambiguous network failures never replay writes',async()=>{
 const m=await media();let writes=0;
 globalThis.fetch=async path=>json(path==='/api/bootstrap'?bootstrap():{items:[]});await m.connect();
 globalThis.fetch=async()=>{writes++;return json({error:'Cross-origin changes are not allowed.'},403);};
 await assert.rejects(m.deleteMedia('u_test'),/Cross-origin/);assert.equal(writes,1);
 globalThis.fetch=async()=>{writes++;throw new TypeError('Network failure');};
 await assert.rejects(m.deleteMedia('u_test'),/Connection lost/);assert.equal(writes,2);assert.equal(m.serverReady,false);
});

test('pre-aborted API calls make no fetch request',async()=>{
 const m=await media(),controller=new AbortController();controller.abort();let calls=0;
 globalThis.fetch=async()=>{calls++;return json({items:[]});};
 await assert.rejects(m.api('/api/library',{signal:controller.signal}),{name:'AbortError'});assert.equal(calls,0);
});

function fakeXHR(handler){
 const instances=[];
 globalThis.XMLHttpRequest=class{
  constructor(){this.upload={};this.headers={};instances.push(this);}
  open(method,path){this.method=method;this.path=path;}
  setRequestHeader(key,value){this.headers[key]=value;}
  send(file){queueMicrotask(()=>handler(this,file));}
  abort(){this.wasAborted=true;this.onabort?.();}
 };
 return instances;
}

test('upload reconnects an expired token once without duplicating a saved file',async()=>{
 const m=await media();let token='old',saved=0;
 globalThis.fetch=async path=>json(path==='/api/bootstrap'?bootstrap(token):{items:[]});await m.connect();token='new';
 const instances=fakeXHR(xhr=>{
  if(xhr.headers['X-Aura-Token']!==token){xhr.status=403;xhr.responseText=JSON.stringify({error:'Session expired.',code:'session_expired'});}
  else{saved++;xhr.status=201;xhr.responseText=JSON.stringify({item:{id:'u_added',name:'movie.mp4'}});}
  xhr.onload();
 });
 const item=await m.upload({name:'movie.mp4',size:123});assert.equal(item.id,'u_added');assert.equal(saved,1);assert.equal(instances.length,2);
 for(const xhr of instances){assert.equal(xhr.onload,null);assert.equal(xhr.onabort,null);assert.equal(xhr.upload.onprogress,null);}
});

test('completed upload detaches abort listener; canceled upload rejects promptly',async()=>{
 const m=await media();globalThis.fetch=async path=>json(path==='/api/bootstrap'?bootstrap():{items:[]});await m.connect();
 const controller=new AbortController(),instances=fakeXHR(xhr=>{xhr.status=201;xhr.responseText='{"item":{"id":"u_done"}}';xhr.onload();});
 await m.upload({name:'photo.jpg',size:1},()=>{},controller.signal);controller.abort();assert.equal(instances[0].wasAborted,undefined);
 const secondController=new AbortController();fakeXHR(()=>{});const pending=m.upload({name:'photo.jpg',size:1},()=>{},secondController.signal);secondController.abort();await assert.rejects(pending,{name:'AbortError'});
});

test('an unreadable successful upload response is not retried',async()=>{
 const m=await media();globalThis.fetch=async path=>json(path==='/api/bootstrap'?bootstrap():{items:[]});await m.connect();
 const instances=fakeXHR(xhr=>{xhr.status=201;xhr.responseText='not json';xhr.onload();});
 await assert.rejects(m.upload({name:'video.mp4',size:4}),/Refresh the library before retrying/);assert.equal(instances.length,1);
});

test('source selection prefers supported codecs and keeps distinct fallback URLs',async()=>{
 const m=await media(),item={sources:[{url:'study.webm',type:'video/webm'},{url:'study.mp4',type:'video/mp4'},{url:'study.mp4',type:'video/mp4'}]};
 const result=m.mediaSources(item,{canPlayType:type=>type==='video/mp4'?'probably':''});assert.deepEqual(result.map(s=>s.url),['study.mp4','study.webm']);
 assert.deepEqual(m.mediaSources({url:'/media/user_file',mime:'video/mp4'},{}),[{url:'/media/user_file',type:'video/mp4'}]);
});

test('subtitles accept whitespace separators and decode entities as plain text',async()=>{
 const m=await media(),cues=m.parseSubtitles('WEBVTT\r\n\r\n00:01.000 --> 00:03.000\r\n<b>Tom &amp; Jerry</b> &#x1F642;\r\n \t\r\n00:04.000 --> 00:05.000\r\n&lt;tag&gt;');
 assert.equal(cues.length,2);assert.equal(cues[0].text,'Tom & Jerry 🙂');assert.equal(cues[1].text,'<tag>');
});

test('subtitle comments, invalid timestamps and empty cues are not displayed',async()=>{
 const m=await media();assert.deepEqual(m.parseSubtitles('WEBVTT\n\nNOTE example\n00:01.000 --> 00:03.000\nThis is a comment\n\n00:61.000 --> 01:03.000\nInvalid seconds\n\n00:04.000 --> 00:05.000\n<b></b>'),[]);
});
