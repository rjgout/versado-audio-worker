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
    models = tmp_path / 'models'
    models.mkdir()
    (models / 'nl_NL-ronnie-medium.onnx').touch()
    (models / 'nl_NL-ronnie-medium.onnx.json').touch()
    monkeypatch.setenv('PIPER_MODELS_DIR', str(models))
    import app.server
    module = importlib.reload(app.server)
    class Styles:
        def raise_for_status(self): pass
        def json(self): return {'styles': [{'name': x} for x in module.VOICES['supertonic']]}
    monkeypatch.setattr(module.requests, 'get', lambda *a, **kw: Styles())
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
    assert seen['json']=={'text':'Hallo','voice':'F1','lang':'nl','steps':12,'speed':1.0,'silence_duration':0.3}
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


def test_import_preview_and_regional_language(client):
    _, c = client; h = login(c)
    rows = '[{"language":"fr-FR","source":"bible","original":"Nom","replacement":"Nomme"}]'
    preview = c.post('/api/rules/import/preview',json={'format':'json','content':rows},headers=h)
    assert preview.status_code == 200 and not preview.json[0]['duplicate']
    assert c.post('/api/rules/import',json={'rows':preview.json},headers=h).json['imported']==1
    assert c.post('/api/rules/import',json={'rows':preview.json},headers=h).json['imported']==0
    assert any(r['language']=='fr-FR' and r['status']=='proposal' for r in c.get('/api/rules').json)
    assert c.post('/api/jobs',json={'engine':'supertonic','voice':'M1','source':'bible','language':'fr-FR','text':'Nom'},headers=h).status_code==202


def test_preview_hidden_and_cleanup(client):
    m,c=client; h=login(c)
    r=c.post('/api/rules',json={'language':'nl','source':'bofm','original':'Test','replacement':'Testje'},headers=h)
    rid=r.json['id']
    before=c.get(f'/api/rules/{rid}/history').json
    result=c.post('/api/previews',json={'engine':'supertonic','voice':'M1','source':'bofm','text':'Test','test_rule':rid},headers=h)
    assert result.status_code==202
    jid=result.json['id']
    assert c.get('/api/jobs').json == []
    assert c.get('/api/previews/'+jid).json['status']=='queued'
    assert c.get(f'/api/rules/{rid}/history').json == before
    with m.db() as db:
        db.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,))
    m.init()
    assert c.get('/api/previews/'+jid).json['status']=='failed'
    with m.db() as db:
        db.execute("UPDATE jobs SET created_at=datetime('now','-2 hours') WHERE id=?",(jid,))
    m.cleanup_previews()
    assert c.get('/api/previews/'+jid).status_code==404


def test_supertonic_job_settings_and_existing_metadata(client):
    import json
    m, c = client
    h = login(c)
    payload = {'engine': 'supertonic', 'voice': 'M5', 'source': 'bofm', 'text': 'Nephi spreekt.'}
    first = c.post('/api/jobs', json=payload, headers=h).json['id']
    with m.db() as db:
        db.execute('UPDATE jobs SET settings=? WHERE id=?', (json.dumps({'total_steps': 12, 'speed': 1.0}), first))
    second = c.post('/api/jobs', json=payload, headers=h).json['id']
    jobs = {job['id']: job for job in c.get('/api/jobs').json}
    assert json.loads(jobs[first]['settings']) == {'total_steps': 12, 'speed': 1.0}
    assert json.loads(jobs[second]['settings']) == {'steps': 12, 'speed': 1.0, 'silence_duration': 0.3}


@pytest.mark.parametrize('settings', [
    {'speed':0.69}, {'speed':2.01}, {'speed':True}, {'speed':'1'},
    {'speed':float('nan')}, {'steps':0}, {'steps':101}, {'steps':1.5},
    {'steps':False}, {'silence_duration':-1}, {'silence_duration':10.1},
    {'unknown':1}, [], None,
])
def test_invalid_supertonic_settings(client, settings):
    _, c=client; h=login(c)
    data={'engine':'supertonic','voice':'M5','source':'bible','text':'Hallo','settings':settings}
    assert c.post('/api/jobs',json=data,headers=h).status_code == 400

@pytest.mark.parametrize('settings', [
    {'speed':1.0,'steps':12,'silence_duration':0.3},
    {'speed':0.9,'steps':12,'silence_duration':0.35},
    {'speed':0.85,'steps':12,'silence_duration':0.45},
    {'speed':1.23,'steps':20,'silence_duration':1.5},
])
def test_profiles_snapshots_previews_and_worker(client, monkeypatch, settings):
    import json
    m,c=client; h=login(c)
    payload={'engine':'supertonic','voice':'M5','source':'bofm','text':'Nephi', 'settings':settings}
    jid=c.post('/api/jobs',json=payload,headers=h).json['id']
    assert json.loads(c.get('/api/jobs').json[0]['settings']) == settings
    preview=c.post('/api/previews',json={**payload,'test_rule':1},headers=h)
    assert preview.status_code==202
    with m.db() as db:
        row=db.execute('SELECT settings FROM jobs WHERE id=?',(preview.json['id'],)).fetchone()
        assert json.loads(row['settings']) == settings
        db.execute("UPDATE jobs SET status='failed' WHERE id=?",(preview.json['id'],))
    buf=io.BytesIO()
    with wave.open(buf,'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(22050); wav.writeframes(b'\x00\x00')
    called=[]
    def fake(*args): called.append(args); return buf.getvalue()
    monkeypatch.setattr(m,'synthesize',fake)
    def stop(_): raise SystemExit()
    monkeypatch.setattr(m.time,'sleep',stop)
    with pytest.raises(SystemExit): m.worker()
    assert called[0][4] == settings
    assert c.get('/api/jobs').json[0]['status']=='done'

def test_legacy_queue_and_piper_settings(client):
    from app.engines import stored_settings
    assert stored_settings('supertonic',{'total_steps':12,'speed':1.0}) == {'steps':12,'speed':1.0,'silence_duration':0.3}
    assert stored_settings('piper',{'total_steps':12,'speed':1.0}) == {}
    _,c=client; h=login(c)
    payload={'engine':'piper','voice':'nl_NL-ronnie-medium','source':'bofm','text':'Hallo'}
    assert c.post('/api/jobs',json={**payload,'settings':{'speed':0.9}},headers=h).status_code == 400
    assert c.post('/api/jobs',json=payload,headers=h).status_code == 202


def test_supertonic_custom_wire_parameters(monkeypatch):
    from app import engines
    seen={}
    class Response:
        content=b'WAV'
        def raise_for_status(self): pass
    def post(url, **kwargs): seen.update(kwargs); return Response()
    monkeypatch.setattr(engines.requests, 'post', post)
    options={'steps':15,'speed':0.85,'silence_duration':0.45}
    assert engines.synthesize('supertonic','M5','Hallo','nl-NL',options)==b'WAV'
    assert seen['json']=={'text':'Hallo','voice':'M5','lang':'nl',**options}


def test_quality_queue_report_and_recovery(client, monkeypatch):
    import json
    m,c=client; h=login(c)
    request={'engine':'supertonic','voice':'M5','source':'bofm','text':'Nephi ging verder'}
    jid=c.post('/api/jobs',json=request,headers=h).json['id']
    buf=io.BytesIO()
    with wave.open(buf,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*16000)
    (m.AUDIO/(jid+'.wav')).write_bytes(buf.getvalue())
    with m.db() as db:
        db.execute("UPDATE jobs SET status='done',audio=? WHERE id=?",(jid+'.wav',jid))
    resp=c.post('/api/jobs/'+jid+'/quality',json={'model':'base'},headers=h)
    assert resp.status_code==202
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'text':'Nefi ging ging verder','model':'base'}
    def post(url,**kw):
        assert kw['params']=={'model':'base','language':'nl'}
        return Response()
    monkeypatch.setattr(m.requests,'post',post)
    monkeypatch.setattr(m.time,'sleep',lambda _: (_ for _ in ()).throw(SystemExit()))
    with pytest.raises(SystemExit): m.worker()
    task=c.get('/api/jobs/'+jid+'/quality').json[0]
    report=json.loads(task['report'])
    assert task['status']=='done' and report['status']=='manual_review'
    assert any(x['type']=='possible_repetition' for x in report['findings'])
    assert report['audio']['near_silence']
    assert (m.AUDIO/(jid+'.wav')).exists()
    qid=c.post('/api/jobs/'+jid+'/quality',json={'model':'tiny'},headers=h).json['id']
    with m.db() as db: db.execute("UPDATE quality_tasks SET status='running' WHERE id=?",(qid,))
    m.init()
    assert c.get('/api/jobs/'+jid+'/quality').json[0]['status']=='failed'


def test_quality_authorization_and_missing_engine(client, monkeypatch):
    m,c=client; h=login(c)
    assert m.app.test_client().get('/api/jobs/not-real/quality').status_code==401
    jid=c.post('/api/jobs',json={'engine':'piper','voice':'nl_NL-ronnie-medium','source':'bofm','text':'test'},headers=h).json['id']
    assert c.post('/api/jobs/'+jid+'/quality',json={'model':'base'},headers=h).status_code==409
    with m.db() as db: db.execute("UPDATE jobs SET status='done',audio='missing.wav' WHERE id=?",(jid,))
    assert c.post('/api/jobs/'+jid+'/quality',json={'model':'base.en'},headers=h).status_code==400
    qid=c.post('/api/jobs/'+jid+'/quality',json={'model':'base'},headers=h).json['id']
    assert c.post('/api/quality/'+qid+'/cancel',headers=h).status_code==200
    assert c.get('/api/jobs/'+jid+'/quality').json[0]['status']=='cancelled'
