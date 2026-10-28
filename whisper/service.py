"""Private, single-request whisper.cpp CLI service. Never downloads models."""
import hashlib
import json
import os
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


def transcribe(audio, model, language):
    path=validate_model(model)
    if language not in ('nl','en','de','fr','es'): raise ValueError('Taal wordt niet ondersteund')
    with tempfile.TemporaryDirectory(prefix='whisper-') as tmp:
        src=Path(tmp)/'input.wav'; wav=Path(tmp)/'converted.wav'; output=Path(tmp)/'result'
        src.write_bytes(audio)
        subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(src),'-ar','16000','-ac','1','-c:a','pcm_s16le',str(wav)],check=True,timeout=300,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        subprocess.run(['whisper-cli','-ng','-m',str(path),'-t',str(THREADS),'-l',language,'-f',str(wav),'-oj','-of',str(output),'-np'],check=True,timeout=TIMEOUT,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        result=json.loads(output.with_suffix('.json').read_text(encoding='utf-8'))
        transcript=' '.join(x.get('text','').strip() for x in result.get('transcription',[]) if x.get('text','').strip())
        return {'text':transcript,'model':model,'model_sha256':MODELS[model],'whisper_commit':'a8d002cfd879315632a579e73f0148d06959de36','threads':THREADS,'language':language}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body):
        data=json.dumps(body,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if self.path=='/health': self.reply(200,{'status':'ok'})
        else: self.reply(404,{'error':'Niet gevonden'})
    def do_POST(self):
        path=urlsplit(self.path)
        if path.path!='/transcribe': return self.reply(404,{'error':'Niet gevonden'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0 < length <= MAX_AUDIO: raise ValueError('Ongeldige audiogrootte')
            params=parse_qs(path.query); model=params.get('model',['base'])[0]; language=params.get('language',['nl'])[0]
            if not LOCK.acquire(blocking=False): return self.reply(429,{'error':'Whisper is bezig'})
            try:
                data=self.rfile.read(length)
                if len(data)!=length: raise ValueError('Onvolledige audio')
                result=transcribe(data,model,language)
            finally: LOCK.release()
            self.reply(200,result)
        except ValueError as e:
            self.reply(422,{'error':str(e)[:200]})
        except (OSError, subprocess.SubprocessError):
            self.reply(422,{'error':'Whisper-controle mislukt; controleer WAV en service.'})
    def log_message(self, fmt, *args):
        # Do not log potentially sensitive request contents.
        return

if __name__=='__main__': ThreadingHTTPServer(('0.0.0.0',8090),Handler).serve_forever()
