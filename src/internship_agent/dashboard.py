"""Private IPv4 loopback UI. Access secret is printed only to the local terminal.

Not a public deployment server. Same-account filesystem/terminal access is trusted.
"""
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlsplit

MAX_BODY=16384
ASSETS={'/':('dashboard_ui.html','text/html; charset=utf-8'),
        '/dashboard_ui.css':('dashboard_ui.css','text/css; charset=utf-8'),
        '/dashboard_ui.js':('dashboard_ui.js','text/javascript; charset=utf-8'),
        '/browser_assistance_ui.js':('browser_assistance_ui.js','text/javascript; charset=utf-8')}

class DashboardServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=False
    def __init__(self,root,*,port=8765,secret=None,sandbox_assistance=False):
        self.sandbox_assistance=sandbox_assistance
        self.root=Path(root).resolve()
        self.secret=secret or secrets.token_urlsafe(32)
        self.sessions={}
        self.session_lock=threading.Lock()
        self.failures=deque(maxlen=100)
        # One concurrent mutator, bounded queue refusal; no hidden background work.
        self.writer=threading.Lock()
        super().__init__(('127.0.0.1',port),Handler)
    @property
    def origin(self):return f'http://127.0.0.1:{self.server_port}'

class Handler(BaseHTTPRequestHandler):
    server_version='InternshipLocal'
    def log_message(self,*args):pass  # Never log request URLs, bodies or secret material.
    def setup(self):
        super().setup();self.connection.settimeout(10)
    def send(self,status,value,*,mime='application/json; charset=utf-8',extra=None):
        body=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=True).encode()
        self.send_response(status)
        for name,val in {'Content-Type':mime,'Content-Length':str(len(body)),
            'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
            'Referrer-Policy':'no-referrer','X-Frame-Options':'DENY',
            'Cross-Origin-Resource-Policy':'same-origin',
            'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
            'Connection':'close',**(extra or {})}.items():self.send_header(name,val)
        self.end_headers();self.wfile.write(body);self.close_connection=True
    def error(self,status,message):self.send(status,{'error':message})
    def boundary(self,mutation=False):
        expected=f'127.0.0.1:{self.server.server_port}'
        hosts=self.headers.get_all('Host',[])
        if hosts!=[expected]:return False
        for header in ('Origin','Referer'):
            values=self.headers.get_all(header,[])
            if len(values)>1:return False
            if values:
                value=urlsplit(values[0])
                if value.scheme!='http' or value.netloc!=expected or value.username or value.password:return False
                if header=='Origin' and (value.path or value.query or value.fragment):return False
        if mutation and self.headers.get('Origin')!=self.server.origin:return False
        if self.headers.get('Sec-Fetch-Site') not in (None,'same-origin','none'):return False
        return True
    def session(self):
        try:
            cookie=SimpleCookie();cookie.load(self.headers.get('Cookie',''))
            sid=cookie['ia_session'].value
        except (KeyError,ValueError):return None,None
        with self.server.session_lock:
            row=self.server.sessions.get(sid)
            if not row or row['expires']<=time.monotonic():
                self.server.sessions.pop(sid,None);return None,None
            return sid,dict(row)
    def do_GET(self):
        try:self.get()
        except Exception:self.error(400,'Request unavailable; check local inputs and retry.')
    def get(self):
        if not self.boundary():return self.error(403,'Foreign request refused')
        url=urlsplit(self.path)
        if len(self.path)>4096:return self.error(413,'Request too large')
        if url.path in ASSETS and not url.query:
            name,mime=ASSETS[url.path]
            return self.send(200,Path(__file__).with_name(name).read_bytes(),mime=mime)
        sid,session=self.session()
        if not session:return self.error(401,'Unlock this local session first')
        if url.path=='/api/assistance' or url.path.startswith('/sandbox/application/'):
            if not self.server.sandbox_assistance:return self.error(403,'Sandbox assistance is not enabled')
            def read_assistance():
                adapter=self.assistance(sid)
                if url.path.startswith('/sandbox/application/'):
                    if url.query:return self.error(400,'Only the exact fixture URL is permitted')
                    adapter.review(url.path.removeprefix('/sandbox/application/'))
                    return self.send(200,Path(__file__).with_name('browser_assistance_fixture.html').read_bytes(),mime='text/html; charset=utf-8')
                query=parse_qs(url.query,max_num_fields=2)
                if any(len(v)!=1 for v in query.values()):return self.error(400,'Duplicate fields')
                if set(query)=={'job_id'}:return self.send(200,{'plans':adapter.list_for_job(query['job_id'][0])})
                if set(query)=={'id'}:return self.send(200,adapter.review(query['id'][0]))
                return self.error(400,'A plan or job ID is required')
            try:return read_assistance()
            except (ValueError,OSError,sqlite3.Error,KeyError,TypeError):return self.error(400,'Sandbox plan unavailable; inspect current approval and reconciliation state')
        if url.path=='/api/session':return self.send(200,{'csrf':session['csrf']})
        if url.path.startswith('/api/'):
            route=url.path[5:]
            if route not in {'overview','jobs','job','review','operations'}:return self.error(404,'Not found')
            parsed=parse_qs(url.query,keep_blank_values=True,max_num_fields=12)
            if any(len(v)!=1 for v in parsed.values()):return self.error(400,'Duplicate query fields')
            from .dashboard_data import DashboardData
            return self.data_call(lambda:DashboardData(self.server.root).get(route,{k:v[0] for k,v in parsed.items()}))
        return self.error(404,'Not found')
    def data_call(self,call):
        try:return self.send(200,call())
        except (ValueError,KeyError,TypeError,FileNotFoundError):return self.error(400,'Local data unavailable or changed. Review inputs, recover or prepare again.')
        except (sqlite3.Error,OSError):return self.error(409,'Local storage busy or unavailable. Stop competing writers; inspect backup and recovery.')
        except Exception:return self.error(500,'Local operation failed. No external action was performed.')
    def do_POST(self):
        try:self.post()
        except Exception:self.error(400,'Invalid request; no raw details logged.')
    def post(self):
        if not self.boundary(True):return self.error(403,'Foreign request refused')
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1:return self.error(400,'Explicit body length required')
        try:length=int(self.headers['Content-Length'])
        except ValueError:return self.error(400,'Invalid body length')
        if not 0<=length<=MAX_BODY:return self.error(413,'Request too large')
        if self.headers.get('Content-Type')!='application/json':return self.error(415,'JSON required')
        def unique(pairs):
            value={}
            for key,item in pairs:
                if key in value:raise ValueError('Duplicate field')
                value[key]=item
            return value
        payload=json.loads(self.rfile.read(length),object_pairs_hook=unique)
        if not isinstance(payload,dict):return self.error(400,'JSON object required')
        if self.path=='/login':
            now=time.monotonic()
            with self.server.session_lock:
                while self.server.failures and self.server.failures[0]<now-60:self.server.failures.popleft()
                if len(self.server.failures)>=20:return self.error(429,'Too many attempts; wait a minute')
                if not isinstance(payload.get('secret'),str) or not hmac.compare_digest(payload['secret'].encode(),self.server.secret.encode()):
                    self.server.failures.append(now);return self.error(401,'Access secret incorrect')
                self.server.sessions={k:v for k,v in self.server.sessions.items() if v['expires']>now}
                if len(self.server.sessions)>=16:return self.error(429,'Session limit reached; restart the local server')
                sid=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
                self.server.sessions[sid]={'csrf':csrf,'expires':now+3600}
            # HTTP loopback: Secure cannot be relied on on plain HTTP; never remotely bind.
            return self.send(200,{'csrf':csrf},extra={'Set-Cookie':f'ia_session={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600'})
        sid,session=self.session()
        if not session:return self.error(401,'Session expired; unlock again')
        with self.server.session_lock:
            current=self.server.sessions.get(sid)
            if not current or not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),current['csrf']):return self.error(403,'Stale or missing confirmation token; refresh session')
            csrf=secrets.token_urlsafe(32);current['csrf']=csrf
        # Rotate even on a refused action. Client obtains current token through /api/session.
        if self.path=='/logout':
            with self.server.session_lock:self.server.sessions.pop(sid,None)
            return self.send(200,{},extra={'Set-Cookie':'ia_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'})
        if self.path=='/api/assistance':
            if not self.server.sandbox_assistance:return self.error(403,'Sandbox assistance is not enabled')
            action=payload.get('action')
            if not isinstance(action,str) or payload.get('confirm')!=action:return self.error(400,'Explicit per-action confirmation required')
            if not self.server.writer.acquire(blocking=False):return self.error(409,'An operation is running; inspect before retrying')
            try:
                adapter=self.assistance(sid)
                if action=='create':return self.data_call(lambda:adapter.create(payload.get('id'),payload.get('review_token'),payload.get('challenge','none')))
                return self.data_call(lambda:adapter.act(payload.get('plan_id'),action,payload.get('token'),payload))
            finally:self.server.writer.release()
        from .dashboard_data import DashboardData
        if self.path=='/api/document':
            try:
                body,name=DashboardData(self.server.root).document(payload.get('id'),payload.get('review_token'),payload.get('kind'))
                return self.send(200,body,mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document',extra={'Content-Disposition':f'attachment; filename="{name}"'})
            except (ValueError,KeyError,TypeError,OSError,sqlite3.Error):return self.error(400,'Document unavailable or revision changed; review again')
        if self.path!='/api/action':return self.error(404,'Not found')
        if not self.server.writer.acquire(blocking=False):return self.error(409,'An operation is already running. Wait, inspect status, then retry.')
        try:return self.data_call(lambda:DashboardData(self.server.root).action(payload.get('action'),payload))
        finally:self.server.writer.release()
    def assistance(self,sid):
        from hashlib import sha256
        from .browser_assistance import Assistance
        return Assistance(self.server.root,self.server.origin,sha256(sid.encode()).hexdigest(),enabled=self.server.sandbox_assistance)
    def do_PUT(self):self.error(405,'Method not allowed')
    do_DELETE=do_PUT
    do_PATCH=do_PUT
    do_HEAD=do_PUT
    do_OPTIONS=do_PUT

def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description='Private IPv4 loopback dashboard; no external integration activation')
    p.add_argument('--root',default=str(Path.cwd()))
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--sandbox-assistance',action='store_true',help='Enable fictional loopback fixture only; never an employer adapter')
    args=p.parse_args(argv)
    server=DashboardServer(args.root,port=args.port,sandbox_assistance=args.sandbox_assistance)
    print(f'Local dashboard: {server.origin}\nAccess secret (paste into unlock form; never into URL): {server.secret}',flush=True)
    print('Keep this terminal private. Ctrl+C stops the server and invalidates all sessions.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
