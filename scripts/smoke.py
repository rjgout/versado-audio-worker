"""Smoke the built image without starting or downloading any TTS engine."""
import http.cookiejar
import json
import os
import subprocess
import tempfile
import time
import urllib.request
import urllib.error
from werkzeug.security import generate_password_hash

name = 'versado-smoke-' + str(os.getpid())
def docker(*args): return subprocess.run(['docker', *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
with tempfile.TemporaryDirectory() as tmp:
    os.chmod(tmp, 0o777)
    for path in ('tests', 'pronunciation'):
        os.mkdir(tmp+'/'+path, 0o777)
        os.chmod(tmp+'/'+path, 0o777)
    command=['run','-d','--name',name,'-p','127.0.0.1:19056:5006','-e','SECRET_KEY='+'x'*40,'-e','PASSWORD_HASH='+generate_password_hash('test-password'),'-v',tmp+'/tests:/data/tests','-v',tmp+'/pronunciation:/data/pronunciation','ghcr.io/rjgout/versado-audio-worker:latest']
    try:
        docker(*command)
        jar=http.cookiejar.CookieJar(); opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)); base='http://127.0.0.1:19056'
        def call(path, method='GET', data=None, csrf=None):
            headers={'Content-Type':'application/json'}
            if csrf: headers['X-CSRF-Token']=csrf
            req=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else (b'' if method=='POST' else None),headers=headers,method=method)
            try:
                with opener.open(req,timeout=5) as res: return res.status,json.load(res)
            except urllib.error.HTTPError as err: return err.code,None
        for _ in range(40):
            try:
                if call('/health')[0]==200: break
            except OSError: time.sleep(.5)
        else: raise RuntimeError('health endpoint did not start')
        assert call('/api/rules')[0]==401
        status, login=call('/api/login','POST',{'password':'test-password'}); assert status==200
        token=login['csrf']
        assert call('/api/rules','POST',{'language':'nl','source':'bible','original':'Mozes','replacement':'Moses'})[0]==403
        status,_=call('/api/rules','POST',{'language':'nl','source':'bible','original':'Mozes','replacement':'Moses'},token); assert status==201
        status,job=call('/api/jobs','POST',{'engine':'supertonic','voice':'M1','source':'bible','text':'Mozes'},token); assert status==202
        docker('restart',name)
        for _ in range(40):
            try:
                if call('/health')[0]==200: break
            except OSError: time.sleep(.5)
        status,rules=call('/api/rules'); assert status==200 and any(r['original']=='Mozes' for r in rules)
        status,jobs=call('/api/jobs'); assert status==200 and any(j['id']==job['id'] for j in jobs)
        assert call('/api/logout','POST',csrf=token)[0]==200
        assert call('/api/rules')[0]==401
        print('Container smoke checks passed; TTS engines are not used.')
    finally:
        subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
