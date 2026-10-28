"""Exercise the private Whisper service without downloading a model."""
import json
import subprocess
import time
import urllib.error
import urllib.request

name='versado-whisper-ci'
subprocess.run(['docker','run','-d','--name',name,'-p','127.0.0.1:19090:8090','versado-whisper:ci'],check=True,stdout=subprocess.DEVNULL)
try:
    for _ in range(40):
        try:
            with urllib.request.urlopen('http://127.0.0.1:19090/health',timeout=2) as response:
                assert json.load(response)['status']=='ok'
                break
        except OSError: time.sleep(.5)
    else: raise RuntimeError('Whisper-service startte niet')
    request=urllib.request.Request('http://127.0.0.1:19090/transcribe?model=base&language=nl',data=b'no model',method='POST')
    try: urllib.request.urlopen(request,timeout=10)
    except urllib.error.HTTPError as e:
        assert e.code==422 and 'ontbreekt' in json.load(e)['error']
    else: raise AssertionError('Ontbrekend model moet falen')
    print('Whisper-service bereikbaar en ontbrekend model correct gemeld; geen model geladen.')
finally:
    subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
