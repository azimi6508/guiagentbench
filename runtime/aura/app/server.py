#!/usr/bin/env python3
"""AURA TV local media server. Python 3.10+, no third-party dependencies.

Imports are streamed to a private data directory. Optional media roots are read-
only. This is a single-user, localhost application, not an Internet-facing server.
"""
from __future__ import annotations
import argparse
from functools import partial
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import hashlib
import io
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import stat
import threading
import time
import uuid
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
TYPES = {'.mp4':('video','video/mp4'), '.m4v':('video','video/mp4'),
 '.webm':('video','video/webm'), '.ogv':('video','video/ogg'), '.mov':('video','video/quicktime'),
 '.mkv':('video','video/x-matroska'), '.jpg':('photo','image/jpeg'), '.jpeg':('photo','image/jpeg'),
 '.png':('photo','image/png'), '.webp':('photo','image/webp'), '.gif':('photo','image/gif'),
 '.avif':('photo','image/avif'), '.bmp':('photo','image/bmp'), '.mp3':('audio','audio/mpeg'),
 '.m4a':('audio','audio/mp4'), '.wav':('audio','audio/wav'), '.ogg':('audio','audio/ogg'),
 '.flac':('audio','audio/flac'), '.opus':('audio','audio/ogg')}
ID_RE = re.compile(r'^(?:u|m)_[a-f0-9]{32}$')
MAX_UPLOAD = 8 * 1024**3

class Library:
    def __init__(self, directory: Path, roots=()):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.files = self.directory/'files'; self.files.mkdir(exist_ok=True)
        self.thumbs = self.directory/'thumbs'; self.thumbs.mkdir(exist_ok=True)
        self.db_path = self.directory/'library.sqlite3'
        self.lock = threading.RLock()
        self.roots = tuple(p.resolve() for p in roots)
        self.mounted = {}; self.scan_count = 0; self.scan_truncated = False
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS media (id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL, added REAL NOT NULL, metadata TEXT NOT NULL DEFAULT "{}")')
        # Interrupted imports are never catalog entries.
        for p in self.files.glob('*.part'):
            try: p.unlink()
            except OSError: pass
        self.rescan()
    @contextmanager
    def db(self):
        conn=sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory=sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()
    def rescan(self):
        found={}; count=0; truncated=False
        for root in self.roots:
            if not root.is_dir(): continue
            for parent, dirs, names in os.walk(root, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(parent)/d).is_symlink())
                for name in sorted(names):
                    path=Path(parent)/name
                    ext=path.suffix.lower()
                    if ext not in TYPES or name.startswith('.') or path.is_symlink(): continue
                    try:
                        if not path.resolve().is_relative_to(root): continue
                        st=path.stat()
                        if not stat.S_ISREG(st.st_mode): continue
                    except OSError: continue
                    ident='m_'+hashlib.sha256(str(path).encode()).hexdigest()[:32]
                    if ident in found: continue
                    kind,mime=TYPES[ext]
                    found[ident]={'id':ident,'name':name,'title':path.stem,'kind':kind,'mime':mime,
                        'size':st.st_size,'added':st.st_mtime,'source':'folder','album':path.parent.name,
                        'url':f'/media/{ident}', 'poster':f'/media/{ident}' if kind=='photo' else '',
                        'path':path}
                    count+=1
                    if count>=10000: truncated=True; break
                if truncated: break
            if truncated: break
        with self.lock: self.mounted=found; self.scan_count=count; self.scan_truncated=truncated
        return count
    def public_row(self,row):
        item=dict(row); meta=json.loads(item.pop('metadata'))
        item.update(meta)
        item.update({'source':'import','url':f'/media/{item["id"]}'})
        item.setdefault('title', Path(item['name']).stem)
        ident=item['id']
        item['poster']=f'/thumb/{ident}' if (self.thumbs/ident).is_file() else (item['url'] if item['kind']=='photo' else '')
        return item
    def list(self):
        with self.db() as db: items=[self.public_row(r) for r in db.execute('SELECT * FROM media ORDER BY added DESC')]
        with self.lock:
            items += [{k:v for k,v in item.items() if k!='path'} for item in self.mounted.values()]
        return items
    def resolve(self, ident, thumbnail=False):
        if not ID_RE.fullmatch(ident): return None
        if thumbnail:
            p=self.thumbs/ident
            return (p,'image/jpeg') if p.is_file() else None
        if ident.startswith('m_'):
            with self.lock: item=self.mounted.get(ident)
            if not item: return None
            p=item['path']
            # A file may have been replaced with a symlink after the scan.
            if p.is_symlink() or not any(p.resolve().is_relative_to(root) for root in self.roots): return None
            return (p,item['mime']) if p.is_file() else None
        with self.db() as db: row=db.execute('SELECT mime FROM media WHERE id=?',(ident,)).fetchone()
        p=self.files/ident
        return (p,row['mime']) if row and p.is_file() else None

class Server(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True
    def __init__(self, address, handler, library):
        self.library=library; self.token=secrets.token_urlsafe(32)
        super().__init__(address,handler)
        host, port=self.server_address[:2]
        self.hosts={f'127.0.0.1:{port}',f'localhost:{port}',f'[::1]:{port}'}
        if host not in ('0.0.0.0','::'): self.hosts.add(f'{host}:{port}')
    def handle_error(self,request,client_address):
        import sys
        if isinstance(sys.exc_info()[1],(BrokenPipeError,ConnectionResetError)): return
        super().handle_error(request,client_address)

class Handler(SimpleHTTPRequestHandler):
    server_version='AuraLocal/3.1'
    extensions_map={**SimpleHTTPRequestHandler.extensions_map,**{ext:mime for ext,(_,mime) in TYPES.items()},
                    '.js':'text/javascript','.json':'application/json','.vtt':'text/vtt','.svg':'image/svg+xml',
                    '.woff2':'font/woff2','.woff':'font/woff'}
    def end_headers(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Cross-Origin-Resource-Policy','same-origin')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data: https: http:; media-src 'self' blob: https: http:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header('Cache-Control','no-store')
        super().end_headers()
    def valid_host(self):
        return self.headers.get('Host','').lower() in self.server.hosts
    def authorized(self):
        if not self.valid_host(): self.error(403,'Unrecognized host. Open localhost on the configured port.'); return False
        origin=self.headers.get('Origin')
        if origin and origin != 'http://'+self.headers.get('Host',''):
            self.error(403,'Cross-origin changes are not allowed.'); return False
        if not secrets.compare_digest(self.headers.get('X-Aura-Token',''),self.server.token):
            self.error(403,'Session expired. Reconnect to AURA and try again.',code='session_expired'); return False
        return True
    def json_response(self, data, status=200):
        body=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)));self.end_headers()
        if self.command!='HEAD': self.wfile.write(body)
    def error(self,status,message,code=None):
        data={'error':message}
        if code: data['code']=code
        self.json_response(data,status)
    def body_size(self,limit):
        if self.headers.get('Transfer-Encoding'): raise ValueError('Chunked uploads are not accepted.')
        raw=self.headers.get('Content-Length','')
        if not raw.isdigit(): raise ValueError('Content-Length is required.')
        size=int(raw)
        if size<=0 or size>limit: raise ValueError(f'File must be between 1 byte and {limit} bytes.')
        return size
    def send_head(self):
        self.range_bounds=None
        if not self.valid_host(): self.send_error(403,'Unknown host');return None
        path=unquote(urlsplit(self.path).path)
        if path in ('/health','/api/bootstrap','/api/library'):
            if path=='/health': data={'status':'ok','app':'aura-tv','version':'3.1.0'}
            elif path=='/api/bootstrap': data={'version':'3.1.0','token':self.server.token,'maxUpload':MAX_UPLOAD,'folderCount':len(self.server.library.roots)}
            else: data={'items':self.server.library.list(),'folderCount':len(self.server.library.roots),'truncated':self.server.library.scan_truncated}
            payload=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(payload)));self.end_headers()
            return io.BytesIO(payload)
        if path.startswith(('/media/','/thumb/')):
            if not re.fullmatch(r'/(?:media|thumb)/(?:u|m)_[a-f0-9]{32}',path):
                self.send_error(404,'Media is no longer available');return None
            resolved=self.server.library.resolve(path.rsplit('/',1)[-1],path.startswith('/thumb/'))
            if not resolved:self.send_error(404,'Media is no longer available');return None
            return self.serve_file(*resolved)
        if path not in ('/','/index.html') and not path.startswith(('/src/','/assets/')):
            self.send_error(404);return None
        target=(ROOT/('index.html' if path=='/' else path.lstrip('/'))).resolve()
        if not target.is_relative_to(ROOT) or target.is_symlink():self.send_error(403);return None
        rel=target.relative_to(ROOT)
        if rel.as_posix()!='index.html' and rel.parts[0] not in ('src','assets'):self.send_error(404);return None
        if not target.is_file(): self.send_error(404);return None
        return self.serve_file(target,self.guess_type(str(target)))
    def serve_file(self,path,mime):
        self.range_bounds=None
        try: stream=path.open('rb');info=os.fstat(stream.fileno());size=info.st_size
        except OSError: self.send_error(404);return None
        etag=f'"{info.st_mtime_ns:x}-{size:x}"'
        modified=self.date_time_string(info.st_mtime)
        start,end,status=0,max(0,size-1),200
        requested=self.headers.get('Range')
        if requested and self.headers.get('If-Range') not in (None,etag,modified): requested=None
        if requested:
            # A malformed oversized integer must be a 416, not an uncaught
            # Python integer-conversion error that drops the media connection.
            match=re.fullmatch(r'bytes=([0-9]{0,20})-([0-9]{0,20})',requested.strip())
            valid=bool(match and (match[1] or match[2]) and size)
            if valid:
                if match[1]: start=int(match[1]);end=min(int(match[2]) if match[2] else size-1,size-1)
                else:
                    suffix=int(match[2]);start=max(0,size-suffix);end=size-1;valid=suffix>0
                valid=valid and 0<=start<=end<size
            if not valid:
                stream.close();self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return None
            status=206;self.range_bounds=(start,end)
        self.send_response(status);self.send_header('Content-Type',mime)
        self.send_header('ETag',etag);self.send_header('Last-Modified',modified)
        self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1 if size else 0))
        if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers();stream.seek(start);return stream
    def copyfile(self,source,output):
        remaining=None if self.range_bounds is None else self.range_bounds[1]-self.range_bounds[0]+1
        while remaining is None or remaining>0:
            buf=source.read(262144 if remaining is None else min(262144,remaining))
            if not buf:break
            output.write(buf)
            if remaining is not None:remaining-=len(buf)
    def do_PUT(self):
        if not self.authorized():return
        path=urlsplit(self.path).path
        lib=self.server.library
        try:
            if path=='/api/media':
                size=self.body_size(MAX_UPLOAD)
                name=unquote(self.headers.get('X-File-Name',''))
                name=name.replace('\\','/').rsplit('/',1)[-1]
                name=''.join(c for c in name if ord(c)>=32 and ord(c)!=127)
                suffix=Path(name).suffix
                if len(name)>240: name=name[:max(0,240-len(suffix))]+suffix
                if not name or Path(name).suffix.lower() not in TYPES:
                    self.error(415,'Choose a supported video, image, or audio file.');return
                kind,mime=TYPES[Path(name).suffix.lower()]
                ident='u_'+uuid.uuid4().hex;temp=lib.files/(ident+'.part');final=lib.files/ident
                self.connection.settimeout(90)
                committed=False
                try:
                    with temp.open('xb') as stream:
                        remaining=size
                        while remaining:
                            chunk=self.rfile.read(min(262144,remaining))
                            if not chunk:raise ValueError('Upload was interrupted; no file was added.')
                            stream.write(chunk);remaining-=len(chunk)
                    temp.replace(final)
                    with lib.db() as db:
                        db.execute('INSERT INTO media(id,name,kind,mime,size,added) VALUES(?,?,?,?,?,?)',(ident,name,kind,mime,size,time.time()))
                        row=db.execute('SELECT * FROM media WHERE id=?',(ident,)).fetchone()
                    committed=True
                    self.json_response({'item':lib.public_row(row)},201)
                except Exception:
                    temp.unlink(missing_ok=True)
                    if not committed:final.unlink(missing_ok=True)
                    raise
            elif (m:=re.fullmatch(r'/api/media/(u_[a-f0-9]{32})/(metadata|thumbnail)',path)):
                ident,what=m.groups()
                if not lib.resolve(ident):self.error(404,'Media not found.');return
                size=self.body_size(1024*1024 if what=='thumbnail' else 4096)
                body=self.rfile.read(size)
                if len(body)!=size:raise ValueError('Incomplete request.')
                if what=='thumbnail':
                    if not (body.startswith(b'\xff\xd8\xff') and body.endswith(b'\xff\xd9')):raise ValueError('Thumbnail must be a JPEG.')
                    with lib.lock:
                        if not lib.resolve(ident):self.error(404,'Media not found.');return
                        temp=lib.thumbs/(ident+'.'+uuid.uuid4().hex+'.tmp')
                        try: temp.write_bytes(body);temp.replace(lib.thumbs/ident)
                        finally: temp.unlink(missing_ok=True)
                else:
                    obj=json.loads(body);clean={}
                    if not isinstance(obj,dict):raise ValueError('Invalid metadata.')
                    for key in ('title','album'):
                        if key in obj:
                            if not isinstance(obj[key],str) or not obj[key].strip() or len(obj[key])>180:raise ValueError('Invalid '+key)
                            clean[key]=obj[key].strip()
                    for key in ('width','height','duration'):
                        if key in obj:
                            v=obj[key]
                            if type(v) not in (int,float) or not 0<=v<=10**8:raise ValueError('Invalid '+key)
                            clean[key]=v
                    with lib.lock:
                        with lib.db() as db:
                            row=db.execute('SELECT metadata FROM media WHERE id=?',(ident,)).fetchone()
                            if not row:self.error(404,'Media not found.');return
                            existing=json.loads(row[0]);existing.update(clean)
                            db.execute('UPDATE media SET metadata=? WHERE id=?',(json.dumps(existing),ident))
                self.json_response({'ok':True})
            else:self.error(404,'Unknown action.')
        except (ValueError,UnicodeError,json.JSONDecodeError) as exc:self.error(400,str(exc))
        except (OSError,sqlite3.Error) as exc:
            print('Import failed:',str(exc),flush=True);self.error(507,'Could not save the file. Check available disk space and permissions.')
    def do_POST(self):
        if not self.authorized():return
        if urlsplit(self.path).path=='/api/rescan':
            self.server.library.rescan();self.json_response({'items':self.server.library.list(),'folderCount':len(self.server.library.roots),'truncated':self.server.library.scan_truncated})
        else:self.error(404,'Unknown action.')
    def do_DELETE(self):
        if not self.authorized():return
        m=re.fullmatch(r'/api/media/(u_[a-f0-9]{32})',urlsplit(self.path).path)
        if not m:self.error(400,'Only imported files can be deleted. Connected folders are read-only.');return
        ident=m[1];lib=self.server.library
        try:
            with lib.lock:
                with lib.db() as db:
                    if not db.execute('SELECT 1 FROM media WHERE id=?',(ident,)).fetchone():self.error(404,'Media not found.');return
                    (lib.files/ident).unlink(missing_ok=True);(lib.thumbs/ident).unlink(missing_ok=True)
                    db.execute('DELETE FROM media WHERE id=?',(ident,))
            self.json_response({'ok':True})
        except (OSError,sqlite3.Error):self.error(500,'Could not delete this imported copy.')
    def log_message(self,fmt,*args):
        if urlsplit(getattr(self,'path','')).path=='/health': return
        print((fmt%args).encode('unicode_escape').decode('ascii'),flush=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default=os.environ.get('HOST','127.0.0.1'))
    parser.add_argument('--port',type=int,default=int(os.environ.get('PORT','8080')))
    parser.add_argument('--data-dir',type=Path,default=ROOT/'data')
    parser.add_argument('--media-dir',action='append',type=Path,default=[],help='Read-only video/photo/audio folder; repeat to add more.')
    args=parser.parse_args()
    for path in args.media_dir:
        if not path.expanduser().is_dir():parser.error(f'Media folder does not exist: {path}')
    try:
        lib=Library(args.data_dir.expanduser(),[p.expanduser() for p in args.media_dir])
        with Server((args.host,args.port),partial(Handler,directory=str(ROOT)),lib) as httpd:
            print(f'\nAURA TV 3.1 · http://localhost:{httpd.server_port}\nLibrary: {lib.directory}\n{len(lib.mounted)} connected media files. Press Ctrl+C to stop.\n',flush=True)
            httpd.serve_forever()
    except KeyboardInterrupt:print('\nAURA TV stopped.')
    except OSError as exc:parser.exit(1,f'Cannot start AURA: {exc}\n')
if __name__=='__main__':main()
