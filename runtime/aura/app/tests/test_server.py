"""Real loopback HTTP tests. No browser or mocks; temporary isolated media roots."""
import http.client,json,os,sys,tempfile,threading,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from server import Server,Handler,Library,MAX_UPLOAD
class QuietHandler(Handler):
 def log_message(self,*args):pass
class HTTPTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.mount=self.root/'originals';self.mount.mkdir()
  self.original=(ROOT/'assets/photos/coffee.jpg').read_bytes();(self.mount/'Coffee.jpg').write_bytes(self.original)
  self.lib=Library(self.root/'data',[self.mount]);self.server=Server(('127.0.0.1',0),QuietHandler,self.lib)
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.port=self.server.server_port
  self.token=self.request('GET','/api/bootstrap')[2]['token']
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
 def request(self,method,path,body=None,headers=None,auth=False,raw=False):
  h=headers or {};h=dict(h)
  if auth:h['X-Aura-Token']=self.token
  if isinstance(body,dict):body=json.dumps(body).encode();h['Content-Type']='application/json'
  conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10);conn.request(method,path,body,h);r=conn.getresponse();data=r.read();status=r.status;rh=dict(r.getheaders());conn.close()
  if not raw and 'application/json' in rh.get('Content-Type','') and data:data=json.loads(data)
  return status,rh,data
 def add(self,data=None,name='My photo.jpg'):
  s,h,b=self.request('PUT','/api/media',data if data is not None else self.original,{'X-File-Name':quote(name)},True);self.assertEqual(s,201,b);return b['item']
 def test_health(self):self.assertEqual(self.request('GET','/health')[2]['version'],'3.1.0')
 def test_modules_and_assets(self):
  for path in ['index.html','src/app.js','src/media.js','src/premium.css','assets/media/liftoff.webm','assets/media/liftoff.mp4','assets/media/liftoff.mp3','assets/photos/coffee.jpg']:
   s,h,b=self.request('GET','/'+path,raw=True);self.assertEqual(s,200,path);self.assertEqual(b,(ROOT/path).read_bytes())
 def test_headers(self):
  _,h,_=self.request('GET','/');self.assertEqual(h['X-Content-Type-Options'],'nosniff');self.assertEqual(h['Cross-Origin-Resource-Policy'],'same-origin');self.assertIn("frame-ancestors 'none'",h['Content-Security-Policy'])
 def test_private_paths_not_served(self):
  for path in ['/server.py','/README.md','/tests/test_server.py','/data/library.sqlite3','/src/../data/library.sqlite3','/src/%2e%2e/server.py','/assets/../../etc/passwd','/src/']:
   self.assertIn(self.request('GET',path)[0],(403,404),path)
 def test_host_check(self):self.assertEqual(self.request('GET','/api/bootstrap',headers={'Host':'evil.example'})[0],403)
 def test_upload_requires_token(self):self.assertEqual(self.request('PUT','/api/media',b'hi',{'X-File-Name':'a.jpg'})[0],403)
 def test_cross_origin_write_blocked(self):self.assertEqual(self.request('PUT','/api/media',b'hi',{'X-File-Name':'a.jpg','Origin':'https://example.org'},True)[0],403)
 def test_same_origin_upload(self):self.assertEqual(self.request('PUT','/api/media',self.original,{'X-File-Name':'a.jpg','Origin':f'http://127.0.0.1:{self.port}'},True)[0],201)
 def test_upload_roundtrip(self):
  item=self.add();s,h,b=self.request('GET',item['url'],raw=True);self.assertEqual(b,self.original);self.assertEqual(h['Content-Type'],'image/jpeg');self.assertEqual(item['source'],'import');self.assertIn(item['id'],[x['id'] for x in self.request('GET','/api/library')[2]['items']])
 def test_import_persists_new_library_instance(self):
  item=self.add();other=Library(self.root/'data',[self.mount]);self.assertIn(item['id'],[x['id'] for x in other.list()]);self.assertEqual(other.resolve(item['id'])[0].read_bytes(),self.original)
 def test_upload_unicode_and_path_sanitized(self):
  item=self.add(name='../../family/<img onerror=alert(1)> İstanbul.jpg');self.assertEqual(item['name'],'<img onerror=alert(1)> İstanbul.jpg');self.assertEqual((self.lib.files/item['id']).parent,self.lib.files)
 def test_long_name_keeps_extension(self):
  item=self.add(name='a'*247+'.jpg');self.assertEqual(len(item['name']),240);self.assertTrue(item['name'].endswith('.jpg'));self.assertEqual(item['kind'],'photo')
 def test_session_expiry_is_distinguishable_and_does_not_import(self):
  self.server.token='a-new-session';s,h,b=self.request('PUT','/api/media',self.original,{'X-File-Name':'a.jpg'},True)
  self.assertEqual(s,403);self.assertEqual(b['code'],'session_expired');self.assertEqual(len(self.lib.list()),1)
  self.token=self.request('GET','/api/bootstrap')[2]['token'];self.add();self.assertEqual(len(self.lib.list()),2)
 def test_media_mime_types(self):
  for name,mime in [('liftoff.webm','video/webm'),('liftoff.mp4','video/mp4'),('liftoff.ogg','audio/ogg'),('liftoff.mp3','audio/mpeg')]:
   s,h,b=self.request('HEAD','/assets/media/'+name,raw=True);self.assertEqual(s,200);self.assertEqual(h['Content-Type'],mime);self.assertEqual(b,b'')
 def test_reject_executable_types(self):
  for name in ['a.html','x.svg','run.py','script.js','photo.heic']:
   self.assertEqual(self.request('PUT','/api/media',b'payload',{'X-File-Name':name},True)[0],415)
 def test_size_limits(self):
  for size in ['0',str(MAX_UPLOAD+1)]:self.assertEqual(self.request('PUT','/api/media',b'',{'Content-Length':size,'X-File-Name':'a.jpg'},True)[0],400)
 def test_byte_range(self):
  item=self.add();s,h,b=self.request('GET',item['url'],headers={'Range':'bytes=17-333'},raw=True);self.assertEqual(s,206);self.assertEqual(b,self.original[17:334]);self.assertEqual(h['Content-Range'],f'bytes 17-333/{len(self.original)}')
 def test_suffix_and_open_range(self):
  item=self.add()
  for ran,expected in [('bytes=-100',self.original[-100:]),('bytes=100-',self.original[100:])]:
   s,h,b=self.request('GET',item['url'],headers={'Range':ran},raw=True);self.assertEqual(s,206);self.assertEqual(b,expected)
 def test_invalid_ranges(self):
  item=self.add()
  for ran in ['bytes=99999999-','bytes=44-3','bytes=-0','bytes=0-2,5-8','garbage','bytes='+'9'*5000+'-']:
   s,h,b=self.request('GET',item['url'],headers={'Range':ran},raw=True);self.assertEqual(s,416);self.assertEqual(b,b'')
 def test_if_range_honors_current_file(self):
  item=self.add();_,h,_=self.request('HEAD',item['url'],raw=True)
  for validator in (h['ETag'],h['Last-Modified']):
   s,rh,b=self.request('GET',item['url'],headers={'Range':'bytes=5-9','If-Range':validator},raw=True);self.assertEqual(s,206);self.assertEqual(b,self.original[5:10])
  s,rh,b=self.request('GET',item['url'],headers={'Range':'bytes=5-9','If-Range':'"older-file"'},raw=True);self.assertEqual(s,200);self.assertEqual(b,self.original)
 def test_partial_mp4_and_webm_are_exact(self):
  for name in ('liftoff.mp4','deep-field.webm'):
   original=(ROOT/'assets/media'/name).read_bytes()
   for ran,expected in [('bytes=0-1023',original[:1024]),('bytes=-512',original[-512:])]:
    s,h,b=self.request('GET','/assets/media/'+name,headers={'Range':ran},raw=True);self.assertEqual(s,206);self.assertEqual(b,expected)
 def test_media_route_rejects_extra_path_segments(self):
  item=self.add();self.assertEqual(self.request('GET','/media/extra/'+item['id'])[0],404)
 def test_head_range(self):
  item=self.add();s,h,b=self.request('HEAD',item['url'],headers={'Range':'bytes=5-9'},raw=True);self.assertEqual(s,206);self.assertEqual(h['Content-Length'],'5');self.assertEqual(b,b'')
 def test_metadata_updates(self):
  item=self.add();self.assertEqual(self.request('PUT',f'/api/media/{item["id"]}/metadata',{'title':'Family weekend','album':'2026','width':600,'height':400,'duration':3600.5},auth=True)[0],200)
  record=next(x for x in self.lib.list() if x['id']==item['id']);self.assertEqual(record['title'],'Family weekend');self.assertEqual(record['duration'],3600.5)
 def test_invalid_metadata_atomic(self):
  item=self.add();self.assertEqual(self.request('PUT',f'/api/media/{item["id"]}/metadata',{'title':'changed','duration':-1},auth=True)[0],400);self.assertEqual(next(x for x in self.lib.list() if x['id']==item['id'])['title'],'My photo')
 def test_metadata_cannot_override_source(self):
  item=self.add();self.request('PUT',f'/api/media/{item["id"]}/metadata',{'url':'javascript:alert(1)','id':'evil','source':'folder'},auth=True);record=next(x for x in self.lib.list() if x['id']==item['id']);self.assertEqual(record['url'],item['url']);self.assertEqual(record['source'],'import')
 def test_thumbnail(self):
  item=self.add();url=f'/api/media/{item["id"]}/thumbnail';self.assertEqual(self.request('PUT',url,b'not jpeg',auth=True)[0],400);self.assertEqual(self.request('PUT',url,self.original,auth=True)[0],200);self.assertEqual(self.request('GET',f'/thumb/{item["id"]}',raw=True)[2],self.original)
 def test_concurrent_thumbnail_writes_are_atomic(self):
  item=self.add();url=f'/api/media/{item["id"]}/thumbnail'
  with ThreadPoolExecutor(max_workers=4) as pool:
   results=list(pool.map(lambda _:self.request('PUT',url,self.original,auth=True)[0],range(8)))
  self.assertEqual(results,[200]*8);self.assertEqual(self.request('GET',f'/thumb/{item["id"]}',raw=True)[2],self.original);self.assertEqual(list(self.lib.thumbs.glob('*.tmp')),[])
 def test_deleted_media_cannot_receive_metadata_or_thumbnail(self):
  item=self.add();self.request('DELETE','/api/media/'+item['id'],auth=True)
  for tail,body in [('metadata',{'title':'Should not return'}),('thumbnail',self.original)]:
   self.assertEqual(self.request('PUT',f'/api/media/{item["id"]}/'+tail,body,auth=True)[0],404)
  self.assertFalse((self.lib.thumbs/item['id']).exists())
 def test_delete_only_copy(self):
  item=self.add();self.assertEqual(self.request('DELETE','/api/media/'+item['id'],auth=True)[0],200);self.assertEqual(self.request('GET',item['url'])[0],404);self.assertEqual((self.mount/'Coffee.jpg').read_bytes(),self.original)
 def test_mounted_folders_read_only(self):
  item=self.lib.list()[0];self.assertEqual(item['source'],'folder');self.assertNotIn('path',item);self.assertEqual(self.request('DELETE','/api/media/'+item['id'],auth=True)[0],400);self.assertEqual(self.request('PUT','/api/media/'+item['id']+'/metadata',{'title':'x'},auth=True)[0],404);self.assertTrue((self.mount/'Coffee.jpg').exists())
 def test_rescan(self):
  (self.mount/'new.png').write_bytes(b'new');s,h,b=self.request('POST','/api/rescan',auth=True);self.assertEqual(s,200);self.assertEqual(len(b['items']),2);self.assertEqual(b['folderCount'],1)
 def test_overlapping_roots_count_files_once(self):
  lib=Library(self.root/'other',[self.mount,self.mount]);self.assertEqual(lib.scan_count,1);self.assertEqual(len(lib.list()),1)
 @unittest.skipUnless(hasattr(os,'mkfifo'),'Named pipes are a POSIX feature')
 def test_media_named_pipe_not_cataloged(self):
  os.mkfifo(self.mount/'not-a-video.mp4');self.lib.rescan();self.assertEqual(len(self.lib.list()),1)
 def test_symlinks_not_followed(self):
  outside=self.root/'private.jpg';outside.write_bytes(b'private');(self.mount/'escape.jpg').symlink_to(outside);(self.mount/'hidden').symlink_to(self.root,target_is_directory=True);self.lib.rescan();self.assertEqual(len(self.lib.list()),1)
 def test_symlink_swap_blocked(self):
  item=self.lib.list()[0];original=self.mount/'Coffee.jpg';original.unlink();outside=self.root/'outside.jpg';outside.write_bytes(b'private');original.symlink_to(outside);self.assertEqual(self.request('GET',item['url'])[0],404)
 def test_missing_mounted_file(self):
  item=self.lib.list()[0];(self.mount/'Coffee.jpg').unlink();self.assertEqual(self.request('GET',item['url'])[0],404)
 def test_incomplete_import_cleanup_on_restart(self):
  p=self.lib.files/'interrupted.part';p.write_bytes(b'incomplete');other=Library(self.root/'data');self.assertFalse(p.exists());self.assertEqual(other.list(),[])
if __name__=='__main__':unittest.main(verbosity=2)
