"""Container integration smoke: fake Supertonic, no model downloads."""
import http.cookiejar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.request
import urllib.error
import wave
from urllib.parse import urlsplit, parse_qs
from werkzeug.security import generate_password_hash

entered = threading.Event()
release = threading.Event()
class Engine(BaseHTTPRequestHandler):
    def do_GET(self):
        data=json.dumps({'styles':[{'name':'M1'}]}).encode()
        self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if data['text']=='blocked':
            entered.set(); release.wait(30)
        wav=io.BytesIO()
        with wave.open(wav,'wb') as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(22050); f.writeframes(b'\0\0'*200)
        try:
            self.send_response(200); self.send_header('Content-Type','audio/wav'); self.end_headers(); self.wfile.write(wav.getvalue())
        except (BrokenPipeError, ConnectionResetError): pass
    def log_message(self, *args): pass
server=ThreadingHTTPServer(('0.0.0.0',0),Engine)
threading.Thread(target=server.serve_forever,daemon=True).start()
quality_entered=threading.Event(); quality_cancelled=threading.Event(); observed={}
class Whisper(BaseHTTPRequestHandler):
    def do_POST(self):
        parsed=urlsplit(self.path); task=parse_qs(parsed.query).get('task',[''])[0]
        if parsed.path=='/transcribe':
            self.rfile.read(int(self.headers.get('Content-Length','0')))
            observed['started']=task; quality_entered.set(); quality_cancelled.wait(50)
            status=422; payload={'error':'Controle geannuleerd'}
        elif parsed.path=='/cancel':
            observed['cancelled']=task; quality_cancelled.set(); status=200; payload={'cancelled':True}
        else: status=404; payload={}
        try:
            self.send_response(status); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps(payload).encode())
        except (BrokenPipeError,ConnectionResetError): pass
    def log_message(self, *args): pass
whisper=ThreadingHTTPServer(('0.0.0.0',0),Whisper)
threading.Thread(target=whisper.serve_forever,daemon=True).start()
name='versado-smoke-'+str(os.getpid())
def docker(*args): return subprocess.run(['docker',*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
with tempfile.TemporaryDirectory() as tmp:
    os.chmod(tmp,0o777)
    for path in ('tests','pronunciation'):
        os.mkdir(tmp+'/'+path); os.chmod(tmp+'/'+path,0o777)
    command=['run','-d','--name',name,'--add-host','host.docker.internal:host-gateway','-p','127.0.0.1:19056:5006','-e','SECRET_KEY='+'x'*40,'-e','PASSWORD_HASH='+generate_password_hash('test-password'),'-e',f'SUPERTONIC_URL=http://host.docker.internal:{server.server_port}','-e',f'WHISPER_URL=http://host.docker.internal:{whisper.server_port}','-v',tmp+'/tests:/data/tests','-v',tmp+'/pronunciation:/data/pronunciation','ghcr.io/rjgout/versado-audio-worker:latest']
    try:
        docker(*command)
        jar=http.cookiejar.CookieJar(); opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)); base='http://127.0.0.1:19056'
        def call(path,method='GET',data=None,csrf=None,raw=False):
            headers={'Content-Type':'application/json'}
            if csrf: headers['X-CSRF-Token']=csrf
            req=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else (b'' if method=='POST' else None),headers=headers,method=method)
            try:
                with opener.open(req,timeout=5) as res: return res.status,res.read() if raw else json.load(res)
            except urllib.error.HTTPError as err: return err.code,None
        def ready():
            for _ in range(60):
                try:
                    if call('/health')[0]==200: return
                except OSError: pass
                time.sleep(.5)
            raise RuntimeError('health endpoint did not start')
        def wait_status(jid,expected):
            for _ in range(80):
                result=call('/api/jobs')[1]
                row=next((j for j in result if j['id']==jid),None)
                if row and row['status'] in expected: return row
                time.sleep(.25)
            raise AssertionError(f'job {jid}: expected {expected}, got {row}')
        ready(); assert call('/api/rules')[0]==401
        status,login=call('/api/login','POST',{'password':'test-password'}); assert status==200; token=login['csrf']
        rule={'language':'nl','source':'bible','original':'Mozes','replacement':'Moses'}
        assert call('/api/rules','POST',rule)[0]==403
        assert call('/api/rules','POST',rule,token)[0]==201
        def create(text):
            status,job=call('/api/jobs','POST',{'engine':'supertonic','voice':'M1','source':'bible','text':text},token); assert status==202; return job['id']
        first=create('test'); done=wait_status(first,{'done'})
        wavpath=tmp+'/tests/'+done['audio']; assert os.path.isfile(wavpath)
        with wave.open(wavpath,'rb') as wav: assert wav.getnframes()>0
        blocked=create('blocked'); assert entered.wait(20)
        assert wait_status(blocked,{'running'})['status']=='running'
        queued=create('waiting'); assert wait_status(queued,{'queued'})['status']=='queued'
        docker('kill',name); release.set(); docker('start',name); ready()
        assert wait_status(blocked,{'failed'})['status']=='failed'
        assert wait_status(queued,{'done'})['status']=='done'
        status,audio=call('/api/jobs/'+first+'/audio',raw=True); assert status==200
        with wave.open(io.BytesIO(audio),'rb') as wav: assert wav.getnframes()>0
        status,rules=call('/api/rules'); assert status==200 and any(r['original']=='Mozes' for r in rules)
        jobs=call('/api/jobs')[1]; assert len([j for j in jobs if j['id'] in (first,blocked,queued)])==3
        assert not next(j for j in jobs if j['id']==blocked)['audio']
        assert os.path.isfile(wavpath)
        original_audio=open(wavpath,'rb').read()
        status,quality=call('/api/jobs/'+first+'/quality','POST',{'model':'base'},token); assert status==202
        assert quality_entered.wait(20) and observed['started']==quality['id']
        docker('kill',name); docker('start',name); ready()
        assert quality_cancelled.wait(20) and observed['cancelled']==quality['id']
        for _ in range(80):
            status,history=call('/api/jobs/'+first+'/quality')
            if status==200 and history[0]['status']=='failed': break
            time.sleep(.25)
        else: raise AssertionError('Onderbroken analyse niet veilig hersteld')
        with open(wavpath,'rb') as f: assert f.read()==original_audio
        with sqlite3.connect(tmp+'/pronunciation/audio-worker.sqlite3') as db:
            assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
        assert call('/api/logout','POST',csrf=token)[0]==200
        assert call('/api/rules')[0]==401
        print('Container smoke passed: fake engine, WAV persistence, deterministic interruption and queued recovery.')
    finally:
        release.set(); quality_cancelled.set(); server.shutdown(); whisper.shutdown()
        subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
