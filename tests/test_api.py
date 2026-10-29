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
        assert kw['params']['model']=='base' and kw['params']['language']=='nl' and kw['params']['task']==resp.json['id']
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
    assert c.get('/api/jobs/'+jid+'/quality').json[0]['status']=='interrupted'


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


def test_generation_waits_for_shared_whisper_lock(client, monkeypatch):
    import fcntl
    import threading
    m,c=client; h=login(c)
    payload={'engine':'supertonic','voice':'M1','source':'bofm','text':'test'}
    assert c.post('/api/jobs',json=payload,headers=h).status_code==202
    buf=io.BytesIO()
    with wave.open(buf,'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b'\0\0')
    called=threading.Event()
    def generate(*args): called.set(); return buf.getvalue()
    monkeypatch.setattr(m,'synthesize',generate)
    monkeypatch.setattr(m.time,'sleep',lambda _: (_ for _ in ()).throw(SystemExit()))
    def worker():
        try: m.worker()
        except SystemExit: pass
    with (m.DATA/'heavy-work.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        thread=threading.Thread(target=worker,daemon=True); thread.start()
        assert not called.wait(0.5)
        fcntl.flock(lock,fcntl.LOCK_UN)
        assert called.wait(5)
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_running_cancel_and_interrupted_recovery(client, monkeypatch):
    m,c=client; h=login(c)
    jid=c.post('/api/jobs',json={'engine':'supertonic','voice':'M1','source':'bible','text':'tekst'},headers=h).json['id']
    with m.db() as db: db.execute("UPDATE jobs SET status='done',audio='safe.wav' WHERE id=?",(jid,))
    (m.AUDIO/'safe.wav').write_bytes(b'existing')
    qid=c.post('/api/jobs/'+jid+'/quality',json={'model':'base'},headers=h).json['id']
    with m.db() as db: db.execute("UPDATE quality_tasks SET status='running' WHERE id=?",(qid,))
    calls=[]
    class Response:
        def raise_for_status(self): pass
    def post(url,**kwargs): calls.append((url,kwargs)); return Response()
    monkeypatch.setattr(m.requests,'post',post)
    assert c.post('/api/quality/'+qid+'/cancel',headers=h).status_code==200
    assert calls[0][1]['params']=={'task':qid}
    assert c.get('/api/jobs/'+jid+'/quality').json[0]['status']=='cancelled'
    assert (m.AUDIO/'safe.wav').read_bytes()==b'existing'
    next_id=c.post('/api/jobs/'+jid+'/quality',json={'model':'base'},headers=h).json['id']
    with m.db() as db: db.execute("UPDATE quality_tasks SET status='running' WHERE id=?",(next_id,))
    m.init()
    assert c.get('/api/jobs/'+jid+'/quality').json[0]['status']=='interrupted'
    monkeypatch.setattr(m.time,'sleep',lambda _: (_ for _ in ()).throw(SystemExit()))
    with pytest.raises(SystemExit): m.worker()
    assert calls[-1][1]['params']=={'task':next_id}
    assert c.get('/api/jobs/'+jid+'/quality').json[0]['status']=='failed'
    assert (m.AUDIO/'safe.wav').read_bytes()==b'existing'


def test_repeated_analysis_history_and_unavailable_service(client, monkeypatch):
    m,c=client; h=login(c)
    jid=c.post('/api/jobs',json={'engine':'piper','voice':'nl_NL-ronnie-medium','source':'bible','text':'tekst'},headers=h).json['id']
    buf=io.BytesIO()
    with wave.open(buf,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*100)
    original=buf.getvalue();(m.AUDIO/'old.wav').write_bytes(original)
    with m.db() as db: db.execute("UPDATE jobs SET status='done',audio='old.wav' WHERE id=?",(jid,))
    first=c.post('/api/jobs/'+jid+'/quality',json={'model':'tiny'},headers=h).json['id']
    with m.db() as db: db.execute("UPDATE quality_tasks SET status='done',report='{}' WHERE id=?",(first,))
    second=c.post('/api/jobs/'+jid+'/quality',json={'model':'small'},headers=h).json['id']
    def offline(*a,**kw): raise m.requests.ConnectionError('offline')
    monkeypatch.setattr(m.requests,'post',offline)
    monkeypatch.setattr(m.time,'sleep',lambda _: (_ for _ in ()).throw(SystemExit()))
    with pytest.raises(SystemExit): m.worker()
    history=c.get('/api/jobs/'+jid+'/quality').json
    assert len(history)==2 and history[0]['id']==second and history[0]['status']=='interrupted'
    assert history[1]['id']==first and history[1]['report']=='{}'
    assert (m.AUDIO/'old.wav').read_bytes()==original


def test_uncertain_tts_blocks_both_queues_until_explicit_recovery(client, monkeypatch):
    m,c=client; h=login(c)
    data={'engine':'supertonic','voice':'M1','source':'bofm','text':'eerste'}
    first=c.post('/api/jobs',json=data,headers=h).json['id']
    second=c.post('/api/jobs',json={**data,'text':'tweede'},headers=h).json['id']
    with m.db() as db:
        db.execute("INSERT INTO quality_tasks(id,job_id,model,status) VALUES('quality',?,'base','queued')",(first,))
    calls=[]
    def lost(*args): calls.append(args); raise m.requests.ConnectionError('verbinding weg')
    monkeypatch.setattr(m,'synthesize',lost)
    monkeypatch.setattr(m.time,'sleep',lambda _: (_ for _ in ()).throw(SystemExit()))
    with pytest.raises(SystemExit): m.worker()
    assert len(calls)==1
    assert c.get('/api/worker/status').json['blocked'] is True
    m.init()
    with pytest.raises(SystemExit): m.worker()
    with m.db() as db:
        assert db.execute('SELECT status FROM jobs WHERE id=?',(second,)).fetchone()[0]=='queued'
        assert db.execute("SELECT status FROM quality_tasks WHERE id='quality'").fetchone()[0]=='queued'
    assert c.post('/api/worker/recover',json={'job_id':first,'confirmed_engine_stopped':True}).status_code==403
    assert c.post('/api/worker/recover',json={'job_id':first,'confirmed_engine_stopped':False},headers=h).status_code==400
    assert c.post('/api/worker/recover',json={'job_id':'wrong','confirmed_engine_stopped':True},headers=h).status_code==409
    assert c.post('/api/worker/recover',json={'job_id':first,'confirmed_engine_stopped':True},headers=h).status_code==200
    assert not c.get('/api/worker/status').json['blocked']


def test_running_tts_guard_cannot_be_manually_cleared(client):
    m,c=client; h=login(c)
    data={'engine':'piper','voice':'nl_NL-ronnie-medium','source':'bofm','text':'tekst'}
    jid=c.post('/api/jobs',json=data,headers=h).json['id']
    with m.db() as db:
        db.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,))
        db.execute('INSERT INTO heavy_tts_guard(singleton,job_id,engine) VALUES(1,?,?)',(jid,'piper'))
    assert c.post('/api/worker/recover',json={'job_id':jid,'confirmed_engine_stopped':True},headers=h).status_code==409


def test_guard_migration_blocks_legacy_running_job(client):
    m,c=client; h=login(c)
    jid=c.post('/api/jobs',json={'engine':'supertonic','voice':'M1','source':'bofm','text':'test'},headers=h).json['id']
    with m.db() as db:
        db.execute('DROP TABLE heavy_tts_guard')
        db.execute('UPDATE schema_version SET version=3')
        db.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,))
    m.init()
    with m.db() as db:
        assert db.execute('SELECT version FROM schema_version').fetchone()[0]==5
    state=c.get('/api/worker/status').json
    assert state['blocked'] and state['job_id']==jid


def test_mls_speaker_inventory_selection_and_rule_priority(client, monkeypatch):
    import json
    from app import engines
    from app.pronunciation import Rule, prepare
    m, c = client
    models = m.Path(__import__('os').environ['PIPER_MODELS_DIR'])
    model = models / 'nl_NL-mls-medium.onnx'
    model.touch()
    mapping = {str(1000 + i): i for i in range(52)}
    model.with_name(model.name + '.json').write_text(json.dumps({'num_speakers':52,'speaker_id_map':mapping}))
    h=login(c)
    options=c.get('/api/voices').json['piper']
    speakers=[x for x in options if '#' in x]
    assert speakers == ['nl_NL-mls-medium#'+str(1000+i) for i in range(52)]
    chosen=speakers[7]
    data={'engine':'piper','voice':chosen,'source':'bofm','text':'Ik, Nephi, ben geboren uit goede ouders'}
    assert c.post('/api/jobs',json=data,headers=h).status_code==202
    assert c.get('/api/jobs').json[0]['voice']==chosen
    assert c.post('/api/jobs',json={**data,'voice':'nl_NL-mls-medium#9999'},headers=h).status_code==400
    rules=[Rule(1,1,'nl','bofm','Naam','basis',engine='piper',voice='nl_NL-mls-medium'),Rule(2,1,'nl','bofm','Naam','spreker',engine='piper',voice=chosen)]
    assert prepare('Naam',rules,'nl','bofm','piper',chosen)[0]=='spreker'
    assert prepare('Naam',rules[:1],'nl','bofm','piper',chosen)[0]=='basis'
    seen={}
    async def fake(voice,text,speaker=None,settings=None):
        seen.update(voice=voice,text=text,speaker=speaker)
        return b'WAV'
    monkeypatch.setattr(engines,'_piper',fake)
    assert engines.synthesize('piper',chosen,'tekst')==b'WAV'
    assert seen=={'voice':'nl_NL-mls-medium','text':'tekst','speaker':'1007'}


def test_mls_invalid_configuration_not_advertised(client):
    m,c=client
    models=m.Path(__import__('os').environ['PIPER_MODELS_DIR'])
    model=models/'nl_NL-mls-medium.onnx';model.touch()
    model.with_name(model.name+'.json').write_text('{broken')
    login(c)
    assert not any('#' in x for x in c.get('/api/voices').json['piper'])


def test_mls_speaker_sent_in_wyoming_event(monkeypatch):
    from app import engines
    from wyoming.audio import AudioStart, AudioChunk, AudioStop
    from wyoming.tts import Synthesize
    events=iter([AudioStart(rate=22050,width=2,channels=1).event(),AudioChunk(rate=22050,width=2,channels=1,audio=b'\0\0').event(),AudioStop().event()])
    seen=[]
    class Client:
        def __init__(self,*args): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def write_event(self,event): seen.append(Synthesize.from_event(event))
        async def read_event(self): return next(events)
    monkeypatch.setattr(engines,'AsyncTcpClient',Client)
    engines.synthesize('piper','nl_NL-mls-medium#2450','tekst')
    assert seen[0].voice.name=='nl_NL-mls-medium'
    assert seen[0].voice.speaker=='2450'


def test_piper_settings_snapshot_worker_preview_and_validation(client,monkeypatch):
    import json
    from app.engines import validate_settings
    m,c=client;h=login(c)
    settings={'length_scale':1.25,'sentence_silence':0.45,'noise_scale':0.2,'noise_w':0.4}
    data={'engine':'piper','voice':'nl_NL-ronnie-medium','source':'bofm','text':'Ik, Nephi, ben geboren uit goede ouders','settings':settings}
    jid=c.post('/api/jobs',json=data,headers=h).json['id']
    assert json.loads(c.get('/api/jobs').json[0]['settings'])==settings
    assert c.post('/api/previews',json={**data,'test_rule':1},headers=h).status_code==202
    with m.db() as db: db.execute('DELETE FROM jobs WHERE is_preview=1')
    seen=[]
    output=io.BytesIO()
    with wave.open(output,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(22050);wav.writeframes(b'\0\0'*10)
    monkeypatch.setattr(m,'synthesize',lambda *args:seen.append(args) or output.getvalue())
    monkeypatch.setattr(m.time,'sleep',lambda _:(_ for _ in ()).throw(SystemExit()))
    with pytest.raises(SystemExit): m.worker()
    assert seen[0][-1]==settings and c.get('/api/jobs').json[0]['status']=='done'
    assert c.get('/api/jobs/'+jid+'/audio').data==output.getvalue()
    for key,value in [('length_scale',0),('noise_scale',True),('sentence_silence',float('nan')),('noise_w',2)]:
        with pytest.raises(ValueError): validate_settings('piper',{**settings,key:value})


def test_filter_keeps_original_and_labels_persist(client,monkeypatch):
    import json
    m,c=client;h=login(c)
    assert c.put('/api/voice-labels',json={'voice':'nl_NL-ronnie-medium','labels':['Man','Warm']},headers=h).status_code==200
    assert c.get('/api/voice-labels').json['nl_NL-ronnie-medium']==['Man','Warm']
    assert c.put('/api/voice-labels',json={'voice':'nl_NL-ronnie-medium','labels':['invented']},headers=h).status_code==400
    jid=c.post('/api/jobs',json={'engine':'piper','voice':'nl_NL-ronnie-medium','source':'bofm','text':'Nephi'},headers=h).json['id']
    source=io.BytesIO()
    with wave.open(source,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(22050);w.writeframes(b'\0\0'*22050)
    original=source.getvalue();(m.AUDIO/'original.wav').write_bytes(original)
    with m.db() as db: db.execute("UPDATE jobs SET status='done',voice='nl_NL-mls-medium',audio='original.wav' WHERE id=?",(jid,))
    assert c.post('/api/jobs/'+jid+'/filter',json={'mode':'light'}).status_code==403
    child=c.post('/api/jobs/'+jid+'/filter',json={'mode':'light'},headers=h).json['id']
    assert c.delete('/api/jobs/'+jid,headers=h).status_code==409
    original_sleep=m.time.sleep
    def stop_when_idle(seconds):
        if seconds==1: raise SystemExit()
        original_sleep(seconds)
    monkeypatch.setattr(m.time,'sleep',stop_when_idle)
    with pytest.raises(SystemExit): m.worker()
    jobs={x['id']:x for x in c.get('/api/jobs').json}
    assert jobs[child]['status']=='done' and jobs[child]['parent_id']==jid, jobs[child]['error']
    assert json.loads(jobs[child]['settings'])['audio_filter']['name']=='afftdn'
    assert (m.AUDIO/'original.wav').read_bytes()==original
    filtered=c.get('/api/jobs/'+child+'/audio').data
    with wave.open(io.BytesIO(filtered),'rb') as w: assert w.getnframes()==22050
    m.init()
    assert c.get('/api/jobs/'+child+'/audio').data==filtered
    second=c.post('/api/jobs/'+jid+'/filter',json={'mode':'light'},headers=h).json['id']
    m.init()  # Queued processing survives restart without touching the WAV.
    import app.processing
    def fail(_): raise OSError('opslag niet beschikbaar')
    monkeypatch.setattr(app.processing,'filter_wav',fail)
    with pytest.raises(SystemExit): m.worker()
    jobs={x['id']:x for x in c.get('/api/jobs').json}
    assert jobs[second]['status']=='failed'
    assert (m.AUDIO/'original.wav').read_bytes()==original
    assert c.get('/api/worker/status').json['blocked']



@pytest.mark.parametrize('reply',['timeout','close','wrong'])
def test_piper_incompatible_before_synthesis(monkeypatch,reply):
    import asyncio
    from app import engines
    from wyoming.event import Event
    seen=[]
    class Client:
        def __init__(self,*args): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def write_event(self,event): seen.append(event.type)
        async def read_event(self):
            if reply=='timeout': raise TimeoutError()
            return None if reply=='close' else Event(type='unexpected')
    monkeypatch.setattr(engines,'AsyncTcpClient',Client)
    with pytest.raises(engines.PiperSettingsError,match='Portainer'):
        engines.synthesize('piper','nl_NL-ronnie-medium','nooit versturen',settings=engines.validate_settings('piper',{}))
    assert seen==['versado-settings']
    state=asyncio.run(engines.piper_health())
    assert state['reachable'] and not state['ready'] and 'rhasspy' in state['error']


def test_piper_handshake_failure_does_not_block_supertonic(client,monkeypatch):
    m,c=client;h=login(c)
    first=c.post('/api/jobs',json={'engine':'piper','voice':'nl_NL-ronnie-medium','source':'bofm','text':'test'},headers=h).json['id']
    second=c.post('/api/jobs',json={'engine':'supertonic','voice':'M5','source':'bofm','text':'test'},headers=h).json['id']
    output=io.BytesIO()
    with wave.open(output,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(22050);w.writeframes(b'\0\0'*20)
    def synthesize(engine,*args):
        if engine=='piper': raise m.PiperSettingsError('Portainer: verkeerde Piper-image')
        return output.getvalue()
    monkeypatch.setattr(m,'synthesize',synthesize)
    monkeypatch.setattr(m.time,'sleep',lambda _:(_ for _ in ()).throw(SystemExit()))
    with pytest.raises(SystemExit): m.worker()
    rows={x['id']:x for x in c.get('/api/jobs').json}
    assert rows[first]['status']=='failed' and 'Portainer' in rows[first]['error']
    assert rows[second]['status']=='done'
    assert not c.get('/api/worker/status').json['blocked']


def test_piper_health_authorization(client,monkeypatch):
    m,c=client
    assert c.get('/api/piper/health').status_code==401
    login(c)
    async def healthy(): return {'ready':True,'reachable':True,'settings_supported':True}
    monkeypatch.setattr(m,'piper_health',healthy)
    assert c.get('/api/piper/health').json['ready']


def test_piper_timeout_after_synthesis_keeps_uncertain_error(monkeypatch):
    from app import engines
    from wyoming.event import Event
    seen=[]
    settings=engines.validate_settings('piper',{})
    class Client:
        def __init__(self,*args): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def write_event(self,event): seen.append(event.type)
        async def read_event(self):
            if len(seen)==1: return Event(type='versado-settings-ready',data=settings)
            raise TimeoutError()
    monkeypatch.setattr(engines,'AsyncTcpClient',Client)
    with pytest.raises(TimeoutError): engines.synthesize('piper','nl_NL-ronnie-medium','tekst',settings=settings)
    assert seen==['versado-settings','synthesize']
