"""Developer-only about:blank harness. Not an HTTP end-to-end test.

The managed browser blocks loopback origins. Exact app modules and bundled
assets are mounted here with explicitly mocked Storage and library transport.
Nothing in this helper is served by the app; there is no runtime test mode.
"""
import base64, json, mimetypes, re
from browser_support import wait_for
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def uri(path,mime=None):
 return 'data:'+(mime or mimetypes.guess_type(path)[0] or 'application/octet-stream')+';base64,'+base64.b64encode(path.read_bytes()).decode()

_cache=None
def bundle():
 global _cache
 if _cache:return _cache
 scripts=[]
 for name in ['data','store','icons','navigation','audio','settings','media','app']:
  text=(ROOT/f'src/{name}.js').read_text()
  text=re.sub(r'^import .*?;\s*$', '', text, flags=re.M)
  text=re.sub(r'\bexport (?=(?:const|let|function|async|class))','',text)
  
  if name=='data':
   filenames=re.findall(r"url:'assets/[^']*/([^']+)'",text)
   text+='\nBUILTINS.forEach((item,i)=>item.name='+json.dumps(filenames)+'[i]);'
  scripts.append(text)
 code='\n'.join(scripts)
 for path in (ROOT/'assets').rglob('*'):
  if path.is_file():code=code.replace(str(path.relative_to(ROOT)),uri(path))
 code+='\nwindow.__verify={getState:()=>structuredClone(state),audio,getPlayer:()=>playerState,getPhoto:()=>photoState,setting:changeSetting,navigate,getRoute:()=>route,dialogs:()=>dialogs.map(d=>d.kind),getCatalog:()=>CATALOG,refresh:()=>syncLibrary(),setSleep:d=>sleepDeadline=d,setIdle:d=>lastActivity=d};'
 _cache=code
 return code

def mount(page,initial=None,old=None,items=None):
 html=(ROOT/'index.html').read_text()
 html=re.sub(r'<link[^>]+>','',html)
 html=re.sub(r'<script[^>]+>.*?</script>','',html,flags=re.S)
 page.goto('about:blank');page.set_content(html)
 for name in ['styles','premium']:page.add_style_tag(content=(ROOT/f'src/{name}.css').read_text())
 payload={}
 if initial:payload['aura-tv.v3']=json.dumps(initial)
 if old:payload['aura-tv.v2']=json.dumps(old)
 page.evaluate('''data=>{ const values=new Map(Object.entries(data.storage));
 Object.defineProperty(window,'localStorage',{configurable:true,value:{
 getItem:k=>values.has(k)?values.get(k):null,
 setItem:(k,v)=>values.set(k,String(v)),removeItem:k=>values.delete(k),clear:()=>values.clear()
 }}); window.__transport={items:data.items,requests:[]};
 window.fetch=async(path,options={})=>{window.__transport.requests.push({path,method:options.method||'GET',body:options.body});
 let out=path==='/api/bootstrap'?{token:'harness-token',maxUpload:8*1024**3,folderCount:0}:{items:window.__transport.items,folderCount:0,truncated:false};
 if(options.method==='DELETE'){window.__transport.items=window.__transport.items.filter(x=>!path.endsWith(x.id));out={ok:true};}
 if(path.endsWith('/metadata')){const id=path.split('/')[3];Object.assign(window.__transport.items.find(x=>x.id===id)||{},JSON.parse(options.body));out={ok:true};}
 return new Response(JSON.stringify(out),{status:200,headers:{'Content-Type':'application/json'}});
 }; }''',{'storage':payload,'items':items or []})
 page.add_script_tag(content=bundle(),type='module')
 wait_for(page,'document.querySelector("#nav-home") !== null')
 page.evaluate('Promise.all([...document.images].map(i=>i.decode().catch(()=>{})))')
 page.wait_for_timeout(100)

def mock_uploads(page):
 """Exercise real browser File/Blob decoding with only the network/storage mocked."""
 page.evaluate('''()=>{window.__transport.delay=15;window.XMLHttpRequest=class {
 constructor(){this.upload={};this.headers={};this.canceled=false;}
 open(method,path){this.method=method;this.path=path;}
 setRequestHeader(k,v){this.headers[k]=v;}
 async send(file){await new Promise(r=>setTimeout(r,window.__transport.delay));if(this.canceled)return;
 const id='u_'+String(window.__transport.items.length+1).padStart(32,'0');
 const kind=file.type.startsWith('image/')?'photo':file.type.startsWith('audio/')?'audio':'video';
 const item={id,name:file.name,title:file.name.replace(/\\.[^.]+$/,''),kind,mime:file.type,size:file.size,added:Date.now()/1000,source:'import',album:'My collection',url:URL.createObjectURL(file)};
 item.poster=kind==='photo'?item.url:'';window.__transport.items.push(item);this.status=201;this.responseText=JSON.stringify({item});this.upload.onprogress?.({lengthComputable:true,loaded:file.size,total:file.size});this.onload?.();
 }
 abort(){this.canceled=true;this.onabort?.();}
 };}''')
