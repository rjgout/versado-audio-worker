"""Private, single-request whisper.cpp CLI service. Never downloads models."""
import hashlib
import fcntl
import json
import os
import signal
import shutil
import re
import time
from pathlib import Path
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

MODELS = {
    'tiny':'be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21',
    'base':'60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe',
    'small':'1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b',
}
LOCK=threading.Lock()
STATE_LOCK=threading.Lock()
TASKS={}

def cancel_task(task_id):
    with STATE_LOCK:
        now=time.monotonic()
        for key,value in list(TASKS.items()):
            if value.get('finished') and now-value['finished']>3600: TASKS.pop(key,None)
        task=TASKS.setdefault(task_id, {'cancelled':False, 'process':None, 'finished':None})
        task['cancelled']=True
        if task.get('process') is None: task['finished']=now
        proc=task.get('process')
        if proc and proc.poll() is None:
            try: os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError: pass

def run_command(args, task, timeout):
    with STATE_LOCK:
        if task['cancelled']: raise ValueError('Controle geannuleerd')
        proc=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,start_new_session=True)
        task['process']=proc
    try:
        try: _,stderr=proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL); proc.communicate()
            raise
        if task['cancelled']: raise ValueError('Controle geannuleerd')
        if proc.returncode: raise subprocess.CalledProcessError(proc.returncode,args,stderr=stderr)
    finally:
        with STATE_LOCK: task['process']=None

MAX_AUDIO=100*1024*1024
MODEL_DIR=Path(os.getenv('WHISPER_MODEL_DIR','/models'))
THREADS=max(1,min(4,int(os.getenv('WHISPER_THREADS','2'))))
TIMEOUT=max(60,min(28800,int(os.getenv('WHISPER_TIMEOUT','7200'))))


def validate_model(name):
    if name not in MODELS: raise ValueError('Onbekend model')
    path=MODEL_DIR / ('ggml-'+name+'.bin')
    if not path.is_file(): raise ValueError('Whisper-model ontbreekt')
    digest=hashlib.sha256()
    with path.open('rb') as model:
        for chunk in iter(lambda:model.read(1024*1024),b''): digest.update(chunk)
    if digest.hexdigest()!=MODELS[name]: raise ValueError('Whisper-model heeft een ongeldige checksum')
    return path


def transcribe(audio, model, language, task=None):
    task = task if task is not None else {'cancelled':False,'process':None}
    path=validate_model(model)
    if language not in ('nl','en','de','fr','es'): raise ValueError('Taal wordt niet ondersteund')
    with tempfile.TemporaryDirectory(prefix='whisper-') as tmp:
        src=Path(tmp)/'input.wav'; wav=Path(tmp)/'converted.wav'; output=Path(tmp)/'result'
        if isinstance(audio,bytes): src.write_bytes(audio)
        else: src=Path(audio)
        run_command(['ffmpeg','-nostdin','-v','error','-i',str(src),'-ar','16000','-ac','1','-c:a','pcm_s16le',str(wav)],task,300)
        run_command(['whisper-cli','-ng','-m',str(path),'-t',str(THREADS),'-l',language,'-f',str(wav),'-oj','-of',str(output),'-np'],task,TIMEOUT)
        result=json.loads(output.with_suffix('.json').read_text(encoding='utf-8'))
        segments=[{'text':x.get('text','').strip(),'start_ms':x.get('offsets',{}).get('from'),'end_ms':x.get('offsets',{}).get('to')} for x in result.get('transcription',[]) if x.get('text','').strip()]
        transcript=' '.join(x['text'] for x in segments)
        return {'text':transcript,'segments':segments,'model':model,'model_sha256':MODELS[model],'whisper_commit':'a8d002cfd879315632a579e73f0148d06959de36','threads':THREADS,'language':language}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body):
        data=json.dumps(body,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        url=urlsplit(self.path)
        if url.path!='/health': return self.reply(404,{'error':'Niet gevonden'})
        model=parse_qs(url.query).get('model',[None])[0]
        binary=shutil.which('whisper-cli') is not None
        result={'status':'ok','binary_available':binary,'model':model,'model_present':None,'checksum_valid':None,'ready':False}
        if model is not None:
            if model not in MODELS: return self.reply(400,{'error':'Onbekend model'})
            try: result['model_present']=(MODEL_DIR/('ggml-'+model+'.bin')).is_file()
            except PermissionError:
                result['error']='Onvoldoende rechten voor de modelmap.'
                return self.reply(200,result)
            if result['model_present']:
                try: validate_model(model); result['checksum_valid']=True
                except (ValueError,OSError): result['checksum_valid']=False
            result['ready']=binary and result['checksum_valid'] is True
        self.reply(200,result)
    def do_POST(self):
        path=urlsplit(self.path)
        params=parse_qs(path.query)
        task_id=params.get('task',[''])[0]
        if path.path=='/cancel':
            if not re.fullmatch('[0-9a-f]{32}',task_id): return self.reply(400,{'error':'Ongeldige taak'})
            cancel_task(task_id); return self.reply(200,{'cancelled':True})
        if path.path!='/transcribe': return self.reply(404,{'error':'Niet gevonden'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0 < length <= MAX_AUDIO: raise ValueError('Ongeldige audiogrootte')
            model=params.get('model',['base'])[0]; language=params.get('language',['nl'])[0]
            if not re.fullmatch('[0-9a-f]{32}',task_id): raise ValueError('Ongeldige taak')
            if not LOCK.acquire(blocking=False): return self.reply(429,{'error':'Whisper is bezig'})
            with STATE_LOCK: task=TASKS.setdefault(task_id, {'cancelled':False,'process':None,'finished':None})
            try:
                if task['cancelled']: raise ValueError('Controle geannuleerd')
                with tempfile.NamedTemporaryFile(prefix='whisper-upload-',suffix='.wav') as upload:
                    remaining=length
                    while remaining:
                        if task['cancelled']: raise ValueError('Controle geannuleerd')
                        data=self.rfile.read(min(65536,remaining))
                        if not data: raise ValueError('Onvolledige audio')
                        upload.write(data); remaining-=len(data)
                    upload.flush()
                    with (Path(os.getenv('WHISPER_LOCK_DIR','/coord'))/'heavy-work.lock').open('a') as work_lock:
                        fcntl.flock(work_lock, fcntl.LOCK_EX)
                        if task['cancelled']: raise ValueError('Controle geannuleerd')
                        result=transcribe(upload.name,model,language,task)
            finally:
                with STATE_LOCK: task['finished']=time.monotonic()
                LOCK.release()
            self.reply(200,result)
        except PermissionError:
            self.reply(422,{'error':'Onvoldoende rechten voor modelmap, tijdelijke opslag of gedeeld werklot.'})
        except ValueError as e:
            self.reply(422,{'error':str(e)[:200]})
        except (OSError, subprocess.SubprocessError):
            self.reply(422,{'error':'Whisper-controle mislukt; controleer WAV en service.'})
    def log_message(self, fmt, *args):
        # Do not log potentially sensitive request contents.
        return

if __name__=='__main__': ThreadingHTTPServer(('0.0.0.0',8090),Handler).serve_forever()
