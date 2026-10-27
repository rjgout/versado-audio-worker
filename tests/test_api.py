import importlib
import io
import wave
import pytest

@pytest.fixture
def client(tmp_path, monkeypatch):
    from werkzeug.security import generate_password_hash
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'db'))
    monkeypatch.setenv('AUDIO_DIR', str(tmp_path / 'audio'))
    monkeypatch.setenv('SECRET_KEY', 'a' * 40)
    monkeypatch.setenv('PASSWORD_HASH', generate_password_hash('test-password'))
    monkeypatch.setenv('START_WORKER', '0')
    import app.server
    module = importlib.reload(app.server)
    module.app.config['TESTING'] = True
    return module, module.app.test_client()

def login(c):
    r=c.post('/api/login',json={'password':'test-password'})
    return {'X-CSRF-Token':r.json['csrf']}

def test_auth_and_csrf(client):
    _, c = client
    assert c.get('/api/jobs').status_code == 401
    assert c.post('/api/login',json={'password':'wrong'}).status_code == 401
    h=login(c)
    assert c.post('/api/rules',json={}).status_code == 403
    assert c.get('/api/voices').status_code == 200
    assert c.post('/api/logout',headers=h).status_code == 200
    assert c.get('/api/jobs').status_code == 401

def test_rules_approval_and_job_snapshots(client):
    m,c=client; h=login(c)
    rule={'language':'nl','source':'bofm','original':'Alma','replacement':'Almaah'}
    rid=c.post('/api/rules',json=rule,headers=h).json['id']
    job={'engine':'piper','voice':'nl_NL-ronnie-medium','source':'bofm','text':'Nephi en Alma'}
    assert c.post('/api/jobs',json=job,headers=h).status_code == 202
    assert c.get('/api/jobs').json[0]['spoken']=='Nefi en Alma'
    assert c.put(f'/api/rules/{rid}',json={'action':'approve'},headers=h).status_code==200
    c.post('/api/jobs',json=job,headers=h)
    assert c.get('/api/jobs').json[0]['spoken']=='Nefi en Almaah'
    assert len(c.get(f'/api/rules/{rid}/history').json)==2
    assert c.put(f'/api/rules/{rid}',json=rule,headers=h).status_code == 200
    assert c.get('/api/rules').json[-1]['status'] in ('proposal','approved')
    assert c.delete(f'/api/rules/{rid}',headers=h).status_code == 200
    assert len(c.get(f'/api/rules/{rid}/history').json)==4

def test_job_label_delete_and_restart(client):
    m,c=client; h=login(c)
    jid=c.post('/api/jobs',json={'engine':'supertonic','voice':'M1','source':'bible','text':'tekst'},headers=h).json['id']
    assert c.patch('/api/jobs/'+jid,json={'label':'nieuw'},headers=h).status_code==200
    assert c.delete('/api/jobs/'+jid,headers=h).status_code==409
    with m.db() as db: db.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,))
    m.init()
    assert c.get('/api/jobs').json[0]['status']=='failed'
    assert c.delete('/api/jobs/'+jid,headers=h).status_code==200

def test_supertonic_request(monkeypatch):
    from app import engines
    seen={}
    class Response:
        content=b'WAV'
        def raise_for_status(self): pass
    def post(url,**kwargs): seen.update(url=url,**kwargs); return Response()
    monkeypatch.setattr(engines.requests,'post',post)
    assert engines.synthesize('supertonic','F1','Hallo') == b'WAV'
    assert seen['json']=={'text':'Hallo','voice':'F1','lang':'nl','total_steps':12,'speed':1.0}
    with pytest.raises(ValueError): engines.synthesize('supertonic','wrong','Hallo')

def test_piper_protocol(monkeypatch):
    from app import engines
    from wyoming.audio import AudioStart, AudioChunk, AudioStop
    events=iter([AudioStart(rate=22050,width=2,channels=1).event(),AudioChunk(rate=22050,width=2,channels=1,audio=b'\0\0').event(),AudioStop().event()])
    class Client:
        def __init__(self,*args): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def write_event(self,e): assert e.type=='synthesize'
        async def read_event(self): return next(events)
    monkeypatch.setattr(engines,'AsyncTcpClient',Client)
    data=engines.synthesize('piper','nl_NL-ronnie-medium','Hallo')
    with wave.open(io.BytesIO(data),'rb') as wav: assert wav.getnframes()==1
