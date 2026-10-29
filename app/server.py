import asyncio
import hmac
import fcntl
import re
import csv
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid
import wave
from functools import wraps

from flask import Flask, abort, jsonify, request, send_file, session, render_template
import requests
from werkzeug.security import check_password_hash
from app.engines import VOICES, synthesize, validate_settings, stored_settings, PiperSettingsError, piper_health
from app.pronunciation import Rule, prepare
from app.quality import compare, inspect_wav, attach_time_ranges

DATA = Path(os.getenv('DATA_DIR', '/data/pronunciation'))
AUDIO = Path(os.getenv('AUDIO_DIR', '/data/tests'))
DATA.mkdir(parents=True, exist_ok=True)
AUDIO.mkdir(parents=True, exist_ok=True)
DB = DATA / 'audio-worker.sqlite3'
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', '')
app.config.update(MAX_CONTENT_LENGTH=1024*1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict', SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'false').lower() == 'true')
if len(app.secret_key) < 32 or not os.getenv('PASSWORD_HASH'):
    raise RuntimeError('SECRET_KEY (minstens 32 tekens) en PASSWORD_HASH zijn vereist')

def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=30000')
    return c

def init():
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
        INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
        CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY, language TEXT NOT NULL, source TEXT NOT NULL, original TEXT NOT NULL, replacement TEXT NOT NULL, engine TEXT, voice TEXT, note TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, version INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS rule_history(id INTEGER PRIMARY KEY, rule_id INTEGER NOT NULL, version INTEGER NOT NULL, snapshot TEXT NOT NULL, changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS voice_labels(voice TEXT PRIMARY KEY, labels TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, original TEXT NOT NULL, spoken TEXT NOT NULL, engine TEXT NOT NULL, voice TEXT NOT NULL, language TEXT NOT NULL, source TEXT NOT NULL, settings TEXT NOT NULL, rules TEXT NOT NULL, label TEXT NOT NULL, status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, audio TEXT);
        ''')
        if 'parent_id' not in [r['name'] for r in c.execute('PRAGMA table_info(jobs)')]:
            c.execute('ALTER TABLE jobs ADD COLUMN parent_id TEXT')
        if 'is_preview' not in [r['name'] for r in c.execute('PRAGMA table_info(jobs)')]:
            c.execute('ALTER TABLE jobs ADD COLUMN is_preview INTEGER NOT NULL DEFAULT 0')
            c.execute('UPDATE schema_version SET version=2')
        if 'quality_model' not in [r['name'] for r in c.execute('PRAGMA table_info(jobs)')]:
            c.execute('ALTER TABLE jobs ADD COLUMN quality_model TEXT')
        c.execute('''CREATE TABLE IF NOT EXISTS quality_tasks (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            model TEXT NOT NULL, status TEXT NOT NULL, report TEXT, error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('UPDATE schema_version SET version=3 WHERE version < 3')
        c.execute('''CREATE TABLE IF NOT EXISTS heavy_tts_guard (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), job_id TEXT NOT NULL,
            engine TEXT NOT NULL, started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        # An older app may have crashed while using a schema without a guard.
        c.execute("INSERT OR IGNORE INTO heavy_tts_guard(singleton,job_id,engine) SELECT 1,id,engine FROM jobs WHERE status='running' ORDER BY rowid LIMIT 1")
        c.execute('UPDATE schema_version SET version=5 WHERE version < 5')
        c.execute("UPDATE quality_tasks SET status='interrupted',error='Controle onderbroken; beëindiging wordt bevestigd.' WHERE status='running'")
        if not c.execute('SELECT 1 FROM rules WHERE id=1').fetchone():
            c.execute("INSERT INTO rules(id,language,source,original,replacement,status,version) VALUES(1,'nl','bofm','Nephi','Nefi','approved',1)")
            history(c, 1)
        c.execute("UPDATE jobs SET status='failed', error='Generatie onderbroken door herstart; maak een nieuwe opdracht.' WHERE status='running'")

def history(c, rid):
    row = dict(c.execute('SELECT * FROM rules WHERE id=?', (rid,)).fetchone())
    c.execute('INSERT INTO rule_history(rule_id,version,snapshot) VALUES(?,?,?)', (rid, row['version'], json.dumps(row, ensure_ascii=False)))

def protected(fn):
    @wraps(fn)
    def inner(*a, **kw):
        if not session.get('auth'):
            abort(401)
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and not hmac.compare_digest(session.get('csrf', ''), request.headers.get('X-CSRF-Token', '')):
            abort(403)
        return fn(*a, **kw)
    return inner

def payload():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        abort(400, 'Ongeldige JSON')
    return value

def valid_language(value):
    return isinstance(value, str) and bool(re.fullmatch(r'(nl|en|de|fr|es)(?:-[A-Za-z0-9]{2,8})*', value))

def available_voices():
    root = Path(os.getenv('PIPER_MODELS_DIR', '/data/models'))
    installed = set()
    if root.exists():
        for model in root.rglob('*.onnx'):
            if model.with_name(model.name + '.json').is_file():
                installed.add(model.stem)
    try:
        response = requests.get(os.getenv('SUPERTONIC_URL', 'http://supertonic:8000') + '/v1/styles', timeout=2)
        response.raise_for_status()
        advertised = {item['name'] for item in response.json()['styles'] if isinstance(item, dict) and isinstance(item.get('name'), str)}
        supertonic = [v for v in VOICES['supertonic'] if v in advertised]
    except (requests.RequestException, ValueError, KeyError, TypeError):
        supertonic = []
    piper = [v for v in VOICES['piper'] if v in installed]
    # The model's own mapping is authoritative; never assume the NAS has 52.
    if 'nl_NL-mls-medium' in installed:
        for model in root.rglob('nl_NL-mls-medium.onnx'):
            try:
                config = json.loads(model.with_name(model.name + '.json').read_text(encoding='utf-8'))
                mapping = config['speaker_id_map']
                count = config['num_speakers']
                if not isinstance(mapping, dict) or type(count) is not int or not 1 <= count <= 10000: break
                valid = [(name, ident) for name, ident in mapping.items()
                         if isinstance(name, str) and name.isascii() and name.isdecimal()
                         and type(ident) is int and 0 <= ident < count]
                if len(valid) != len(mapping) or len({ident for _, ident in valid}) != len(valid): break
                piper += ['nl_NL-mls-medium#' + name for name, ident in sorted(valid, key=lambda item: item[1])]
            except (OSError, ValueError, KeyError, TypeError):
                pass
            break
    return {'piper': piper, 'supertonic': supertonic}

def bounded(v, name, maximum, required=True):
    if not isinstance(v, str) or len(v) > maximum or (required and not v.strip()):
        abort(400, f'Ongeldige {name}')
    return v.strip()

@app.get('/health')
def health():
    return {'status':'ok'}

@app.get('/')
def index():
    return render_template('index.html')

@app.get('/api/session')
def get_session():
    return {'authenticated': bool(session.get('auth')), 'csrf': session.get('csrf')}

@app.post('/api/login')
def login():
    # Origin verification prevents cross-site login requests.
    origin = request.headers.get('Origin')
    if origin and origin != request.host_url.rstrip('/'):
        abort(403)
    password = payload().get('password', '')
    if not isinstance(password, str) or len(password) > 1024 or not check_password_hash(os.environ['PASSWORD_HASH'], password):
        time.sleep(0.5)
        abort(401)
    session.clear()
    session['auth'] = True
    session['csrf'] = secrets.token_urlsafe(32)
    return {'csrf':session['csrf']}

@app.post('/api/logout')
@protected
def logout():
    session.clear()
    return {'ok':True}

@app.get('/api/piper/health')
@protected
def check_piper():
    return asyncio.run(piper_health())

@app.get('/api/voices')
@protected
def voices():
    return available_voices()

@app.route('/api/rules', methods=['GET','POST'])
@protected
def rules():
    with db() as c:
        if request.method == 'GET':
            return jsonify([dict(x) for x in c.execute('SELECT * FROM rules WHERE deleted=0 ORDER BY original')])
        d = validate_rule(payload())
        cur = c.execute('INSERT INTO rules(language,source,original,replacement,engine,voice,note,status,version) VALUES(?,?,?,?,?,?,?,?,1)', (*d, 'proposal'))
        history(c, cur.lastrowid)
        return {'id':cur.lastrowid}, 201

def validate_rule(p):
    language = bounded(p.get('language', 'nl'), 'taal', 16)
    if not valid_language(language): abort(400, 'Ongeldige taal')
    source = p.get('source')
    if source not in ('bofm','bible'): abort(400, 'Ongeldige bron')
    engine = p.get('engine') or None
    voice = p.get('voice') or None
    if engine and engine not in VOICES: abort(400, 'Ongeldig model')
    if voice and (not engine or (voice not in VOICES[engine] and voice not in available_voices().get(engine, []))): abort(400, 'Ongeldige stem')
    return (language, source, bounded(p.get('original'), 'woord', 120), bounded(p.get('replacement'), 'uitspraak', 120), engine, voice, bounded(p.get('note',''), 'toelichting', 1000, False))


@app.post('/api/rules/import/preview')
@protected
def import_preview():
    p = payload()
    fmt = p.get('format')
    text = bounded(p.get('content'), 'import', 200000)
    try:
        if fmt == 'json':
            rows = json.loads(text)
        elif fmt == 'csv':
            rows = list(csv.DictReader(io.StringIO(text)))
        else:
            abort(400, 'Gebruik CSV of JSON')
        if not isinstance(rows, list) or len(rows) > 500:
            abort(400, 'Maximaal 500 regels')
    except (ValueError, csv.Error):
        abort(400, 'Ongeldig importbestand')
    result = []
    seen = set()
    with db() as c:
        for row in rows:
            if not isinstance(row, dict) or not row.get('language') or not row.get('source'):
                abort(400, 'Taal en schriftbron zijn verplicht')
            d = validate_rule(row)
            key = tuple((x or '').casefold() for x in (d[0],d[1],d[2],d[4],d[5]))
            duplicate = key in seen or c.execute("SELECT 1 FROM rules WHERE deleted=0 AND language=? AND source=? AND lower(original)=lower(?) AND coalesce(engine,'')=? AND coalesce(voice,'')=?", (d[0],d[1],d[2],d[4] or '',d[5] or '')).fetchone() is not None
            seen.add(key)
            result.append({'language':d[0], 'source':d[1], 'original':d[2], 'replacement':d[3], 'engine':d[4], 'voice':d[5], 'note':d[6], 'duplicate':duplicate})
    return jsonify(result)

@app.post('/api/rules/import')
@protected
def import_rules():
    p = payload()
    rows = p.get('rows')
    if not isinstance(rows, list) or len(rows) > 500: abort(400)
    count = 0
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        for row in rows:
            if not isinstance(row, dict) or not row.get('language') or not row.get('source'): abort(400)
            d = validate_rule(row)
            if c.execute("SELECT 1 FROM rules WHERE deleted=0 AND language=? AND source=? AND lower(original)=lower(?) AND coalesce(engine,'')=? AND coalesce(voice,'')=?", (d[0],d[1],d[2],d[4] or '',d[5] or '')).fetchone():
                continue
            cur = c.execute('INSERT INTO rules(language,source,original,replacement,engine,voice,note,status,version) VALUES(?,?,?,?,?,?,?,?,1)', (*d, 'proposal'))
            history(c,cur.lastrowid)
            count += 1
    return {'imported':count}

@app.route('/api/rules/<int:rid>', methods=['PUT','DELETE'])
@protected
def rule_update(rid):
    with db() as c:
        old = c.execute('SELECT * FROM rules WHERE id=? AND deleted=0', (rid,)).fetchone()
        if not old: abort(404)
        if request.method == 'DELETE':
            c.execute("UPDATE rules SET deleted=1,status='inactive',version=version+1 WHERE id=?", (rid,))
        else:
            p=payload()
            if 'action' in p:
                status={'approve':'approved','deactivate':'inactive'}.get(p['action'])
                if not status: abort(400)
                c.execute('UPDATE rules SET status=?,version=version+1 WHERE id=?', (status,rid))
            else:
                d=validate_rule(p)
                c.execute("UPDATE rules SET language=?,source=?,original=?,replacement=?,engine=?,voice=?,note=?,status='proposal',version=version+1 WHERE id=?", (*d,rid))
        history(c,rid)
    return {'ok':True}

@app.get('/api/rules/<int:rid>/history')
@protected
def rule_history(rid):
    with db() as c:
        return jsonify([dict(x) for x in c.execute('SELECT version,snapshot,changed_at FROM rule_history WHERE rule_id=? ORDER BY version DESC',(rid,))])

@app.get('/api/worker/status')
@protected
def worker_status():
    with db() as c:
        row=c.execute("SELECT g.job_id,g.engine,g.started_at,j.status FROM heavy_tts_guard g LEFT JOIN jobs j ON j.id=g.job_id WHERE g.singleton=1").fetchone()
    if row is None: return {'blocked':False}
    return {'blocked':row['status'] != 'running', 'job_id':row['job_id'], 'engine':row['engine'], 'started_at':row['started_at']}

@app.post('/api/worker/recover')
@protected
def recover_worker():
    p=payload()
    if p.get('confirmed_engine_stopped') is not True or not isinstance(p.get('job_id'), str): abort(400, 'Bevestig dat de betrokken engine volledig is gestopt')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT g.job_id,j.status FROM heavy_tts_guard g LEFT JOIN jobs j ON j.id=g.job_id WHERE g.singleton=1").fetchone()
        if not row or row['job_id'] != p['job_id']: abort(409, 'De blokkering is gewijzigd; ververs de pagina')
        if row['status']=='running': abort(409, 'Een opdracht is nog actief')
        c.execute('DELETE FROM heavy_tts_guard WHERE singleton=1 AND job_id=?',(row['job_id'],))
    return {'ok':True}

@app.route('/api/previews', methods=['POST'])
@app.route('/api/jobs', methods=['GET','POST'])
@protected
def jobs():
    with db() as c:
        if request.method == 'GET':
            return jsonify([dict(x) for x in c.execute('SELECT jobs.*, (SELECT id FROM quality_tasks WHERE job_id=jobs.id ORDER BY rowid DESC LIMIT 1) AS quality_id, (SELECT status FROM quality_tasks WHERE job_id=jobs.id ORDER BY rowid DESC LIMIT 1) AS quality_status, (SELECT report FROM quality_tasks WHERE job_id=jobs.id ORDER BY rowid DESC LIMIT 1) AS quality_report, (SELECT error FROM quality_tasks WHERE job_id=jobs.id ORDER BY rowid DESC LIMIT 1) AS quality_error FROM jobs WHERE is_preview=0 ORDER BY created_at DESC, jobs.rowid DESC LIMIT 500')])
        p=payload()
        preview = request.path == '/api/previews'
        quality_model=p.get('quality_model')
        if quality_model is not None and (preview or quality_model not in ('tiny','base','small')): abort(400, 'Ongeldig Whisper-model')
        if preview != bool(p.get('test_rule')): abort(400, 'Ongeldige preview')
        engine=p.get('engine'); voice=p.get('voice')
        if voice not in available_voices().get(engine,[]): abort(400,'Stem is niet geïnstalleerd of onbekend')
        try:
            settings=validate_settings(engine, p.get('settings', {}))
        except ValueError as e:
            abort(400, str(e))
        language=p.get('language','nl'); source=p.get('source','bofm')
        if source not in ('bofm','bible') or not valid_language(language): abort(400)
        original=bounded(p.get('text'),'tekst',20000)
        label=bounded(p.get('label',''),'label',200,False)
        if c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] >= 25: abort(429,'Wachtrij is vol')
        rr=[Rule(**{k:r[k] for k in ('id','version','language','source','original','replacement','status','engine','voice')}) for r in c.execute('SELECT * FROM rules WHERE deleted=0')]
        spoken, used=prepare(original,rr,language,source,engine,voice)
        if p.get('test_rule'):
            rule=c.execute('SELECT * FROM rules WHERE id=? AND deleted=0',(p['test_rule'],)).fetchone()
            if not rule: abort(404)
            if rule['language'] != language or rule['source'] != source: abort(400)
            spoken='Dit is de uitspraak van ' + rule['replacement'] + '.'
            used=[{'id':rule['id'],'version':rule['version'],'original':rule['original'],'replacement':rule['replacement']}]
        jid=uuid.uuid4().hex
        c.execute('INSERT INTO jobs(id,original,spoken,engine,voice,language,source,settings,rules,label,status,is_preview,quality_model) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,original,spoken,engine,voice,language,source,json.dumps(settings),json.dumps(used),label,'queued',int(preview),quality_model))
        return {'id':jid},202

@app.get('/api/previews/<jid>')
@protected
def preview_status(jid):
    with db() as c:
        row = c.execute('SELECT id,status,error FROM jobs WHERE id=? AND is_preview=1', (jid,)).fetchone()
    if not row: abort(404)
    return dict(row)

def cleanup_previews():
    # Never remove a running task or a task still waiting for the worker.
    with db() as c:
        rows = c.execute("SELECT id,audio FROM jobs WHERE is_preview=1 AND status IN ('done','failed') AND created_at < datetime('now','-1 hour')").fetchall()
        for row in rows:
            if row['audio']: (AUDIO / row['audio']).unlink(missing_ok=True)
            c.execute('DELETE FROM jobs WHERE id=?', (row['id'],))

@app.get('/api/quality/health')
@protected
def quality_health():
    model=request.args.get('model','base')
    if model not in ('tiny','base','small'): abort(400)
    try:
        result=requests.get(os.getenv('WHISPER_URL','http://whisper:8090')+'/health',params={'model':model},timeout=(2,30))
        result.raise_for_status()
        return {'reachable':True,**result.json()}
    except (requests.RequestException,ValueError):
        return {'reachable':False,'ready':False,'error':'Whisper-service niet bereikbaar'}

@app.route('/api/jobs/<jid>/quality', methods=['GET','POST'])
@protected
def quality_tasks(jid):
    with db() as c:
        job=c.execute('SELECT status,is_preview FROM jobs WHERE id=?',(jid,)).fetchone()
        if not job or job['is_preview']: abort(404)
        if request.method=='GET':
            return jsonify([dict(row) for row in c.execute('SELECT * FROM quality_tasks WHERE job_id=? ORDER BY rowid DESC',(jid,))])
        if job['status']!='done': abort(409, 'Opname is nog niet klaar')
        model=payload().get('model','base')
        if model not in ('tiny','base','small'): abort(400, 'Onbekend Whisper-model')
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT count(*) FROM quality_tasks WHERE status IN ('queued','running','interrupted')").fetchone()[0]>=25: abort(429, 'Wachtrij is vol')
        if c.execute("SELECT 1 FROM quality_tasks WHERE job_id=? AND status IN ('queued','running','interrupted')",(jid,)).fetchone(): abort(409, 'Controle loopt al')
        qid=uuid.uuid4().hex
        c.execute("INSERT INTO quality_tasks(id,job_id,model,status) VALUES(?,?,?,'queued')",(qid,jid,model))
        return {'id':qid},202

@app.post('/api/quality/<qid>/cancel')
@protected
def cancel_quality(qid):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT status FROM quality_tasks WHERE id=?',(qid,)).fetchone()
        if not row: abort(404)
        if row['status']=='queued':
            c.execute("UPDATE quality_tasks SET status='cancelled' WHERE id=? AND status='queued'",(qid,))
            return {'ok':True}
        if row['status']!='running': abort(409, 'Controle is al afgerond')
    try:
        response=requests.post(os.getenv('WHISPER_URL','http://whisper:8090')+'/cancel',params={'task':qid},timeout=(2,5))
        response.raise_for_status()
    except requests.RequestException:
        abort(503, 'De Whisper-service bevestigde het stoppen niet')
    with db() as c:
        changed=c.execute("UPDATE quality_tasks SET status='cancelled' WHERE id=? AND status='running'",(qid,)).rowcount
        if not changed: abort(409, 'Controle is inmiddels afgerond')
    return {'ok':True}


def run_quality(task):
    with db() as c:
        job=c.execute('SELECT * FROM jobs WHERE id=?',(task['job_id'],)).fetchone()
    if not job or not job['audio']: raise ValueError('Audiobestand ontbreekt')
    path=AUDIO/job['audio']
    if path.stat().st_size>100*1024*1024: raise ValueError('Audiobestand te groot')
    audio_stats=inspect_wav(path)
    try:
        with path.open('rb') as data:
            response=requests.post(os.getenv('WHISPER_URL','http://whisper:8090')+'/transcribe',params={'model':task['model'],'language':job['language'].split('-')[0],'task':task['id']},data=data,headers={'Content-Type':'audio/wav'},timeout=(5, min(28800,max(60,int(os.getenv('WHISPER_TIMEOUT','7200'))))))
    except requests.RequestException:
        try: requests.post(os.getenv('WHISPER_URL','http://whisper:8090')+'/cancel',params={'task':task['id']},timeout=(2,5))
        except requests.RequestException: pass
        raise
    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        try: detail=response.json().get('error','Whisper-controle mislukt')
        except (ValueError, AttributeError): detail='Whisper-controle mislukt'
        raise ValueError(str(detail)[:200]) from e
    result=response.json()
    if not isinstance(result.get('text'),str): raise ValueError('Ongeldig Whisper-antwoord')
    report=compare(job['spoken'], result['text'])
    attach_time_ranges(report['findings'],result.get('segments',[]))
    report.update({'transcript':result['text'],'expected':job['spoken'],'audio':audio_stats,'engine':result})
    if audio_stats['near_silence']: report['findings'].append({'type':'near_silence','message':'De opname bevat vrijwel uitsluitend stilte.'})
    return report

@app.route('/api/jobs/<jid>', methods=['PATCH','DELETE'])
@protected
def job_update(jid):
    with db() as c:
        row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row: abort(404)
        if request.method == 'PATCH':
            c.execute('UPDATE jobs SET label=? WHERE id=?',(bounded(payload().get('label',''),'label',200,False),jid))
        else:
            if row['status'] in ('queued','running') or c.execute("SELECT 1 FROM quality_tasks WHERE job_id=? AND status IN ('queued','running','interrupted')",(jid,)).fetchone(): abort(409)
            if c.execute('SELECT 1 FROM jobs WHERE parent_id=?',(jid,)).fetchone(): abort(409,'Verwijder eerst de bewerkte versies')
            c.execute('DELETE FROM jobs WHERE id=?',(jid,))
            if row['audio']: (AUDIO / row['audio']).unlink(missing_ok=True)
    return {'ok':True}

@app.route('/api/voice-labels',methods=['GET','PUT'])
@protected
def voice_labels():
    with db() as c:
        if request.method=='GET': return {r['voice']:json.loads(r['labels']) for r in c.execute('SELECT * FROM voice_labels')}
        p=payload(); voice=bounded(p.get('voice'),'stem',150)
        labels=p.get('labels')
        allowed={'Man','Vrouw','Warm','Helder','Diep','Rustig','Favoriet'}
        if not isinstance(labels,list) or len(labels)>7 or any(not isinstance(x,str) or x not in allowed for x in labels): abort(400)
        if voice not in available_voices()['piper']: abort(400)
        c.execute('INSERT OR REPLACE INTO voice_labels VALUES(?,?)',(voice,json.dumps(sorted(set(labels)))))
    return {'ok':True}

@app.post('/api/jobs/<jid>/filter')
@protected
def filter_job(jid):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT * FROM jobs WHERE id=? AND status='done' AND is_preview=0",(jid,)).fetchone()
        if not row or row['engine']!='piper' or not row['voice'].startswith('nl_NL-mls-medium') or row['parent_id']: abort(400)
        if c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]>=25: abort(429)
        if payload().get('mode')!='light': abort(400)
        settings=json.loads(row['settings']);settings['audio_filter']={'name':'afftdn','nr':6,'nf':-50,'parent_id':jid}
        ident=uuid.uuid4().hex
        c.execute('INSERT INTO jobs(id,original,spoken,engine,voice,language,source,settings,rules,label,status,parent_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(ident,row['original'],row['spoken'],row['engine'],row['voice'],row['language'],row['source'],json.dumps(settings),row['rules'],row['label']+' · lichte ruisfilter','queued',jid))
    return {'id':ident},202

@app.get('/api/jobs/<jid>/audio')
@protected
def audio(jid):
    with db() as c: row=c.execute("SELECT audio FROM jobs WHERE id=? AND status='done'",(jid,)).fetchone()
    if not row or not row['audio']: abort(404)
    return send_file(AUDIO / row['audio'], mimetype='audio/wav', as_attachment=request.args.get('download') == '1', download_name='versado.wav')

def worker():
    next_recovery=0
    while True:
        try:
            cleanup_previews()
            if time.monotonic() >= next_recovery:
                next_recovery=time.monotonic()+30
                with db() as c: interrupted=c.execute("SELECT id FROM quality_tasks WHERE status='interrupted'").fetchall()
                for item in interrupted:
                    try:
                        response=requests.post(os.getenv('WHISPER_URL','http://whisper:8090')+'/cancel',params={'task':item['id']},timeout=(2,5))
                        response.raise_for_status()
                        with db() as c: c.execute("UPDATE quality_tasks SET status='failed',error='Controle onderbroken door herstart.' WHERE id=? AND status='interrupted'",(item['id'],))
                    except requests.RequestException: break
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                # A persisted guard survives client death even when the engine does not.
                guarded=c.execute('SELECT 1 FROM heavy_tts_guard WHERE singleton=1').fetchone()
                row=None; task=None
                if not guarded:
                    row=c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
                    if row:
                        c.execute("UPDATE jobs SET status='running' WHERE id=?",(row['id'],))
                        c.execute('INSERT INTO heavy_tts_guard(singleton,job_id,engine) VALUES(1,?,?)',(row['id'],row['engine']))
                    else:
                        task=c.execute("SELECT * FROM quality_tasks WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
                        if task: c.execute("UPDATE quality_tasks SET status='running' WHERE id=?",(task['id'],))
            if task:
                try:
                    report=run_quality(task)
                    with db() as c: c.execute("UPDATE quality_tasks SET status='done',report=? WHERE id=? AND status='running'",(json.dumps(report,ensure_ascii=False),task['id']))
                except Exception as e:
                    status='interrupted' if isinstance(e, requests.RequestException) else 'failed'
                    with db() as c: c.execute("UPDATE quality_tasks SET status=?,error=? WHERE id=? AND status='running'",(status,str(e)[:500],task['id']))
                continue
            if not row:
                time.sleep(1); continue
            try:
                # The Whisper service holds the same lock for its subprocess.
                # A service surviving an app restart therefore cannot overlap TTS.
                with (DATA/'heavy-work.lock').open('a') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    options=json.loads(row['settings'])
                    if row['parent_id']:
                        from app.processing import filter_wav
                        with db() as c: parent=c.execute("SELECT audio FROM jobs WHERE id=? AND status='done'",(row['parent_id'],)).fetchone()
                        if not parent: raise ValueError('Originele opname ontbreekt')
                        audio_bytes=filter_wav(AUDIO/parent['audio'])
                    else:
                        audio_bytes=synthesize(row['engine'],row['voice'],row['spoken'],row['language'],stored_settings(row['engine'],options))
                    # A complete engine response proves the request ended. Release
                    # only our guard, and keep flock until the DB transaction commits.
                    with db() as c: c.execute('DELETE FROM heavy_tts_guard WHERE singleton=1 AND job_id=?',(row['id'],))
                if len(audio_bytes)>100*1024*1024: raise ValueError('Audio is te groot')
                import io
                with wave.open(io.BytesIO(audio_bytes),'rb') as w:
                    if not w.getnframes(): raise ValueError('Leeg WAV-bestand')
                filename=row['id']+'.wav'; temp=AUDIO/(filename+'.tmp')
                with temp.open('wb') as f:
                    f.write(audio_bytes); f.flush(); os.fsync(f.fileno())
                os.replace(temp,AUDIO/filename)
                with db() as c:
                    c.execute("UPDATE jobs SET status='done',audio=? WHERE id=?",(filename,row['id']))
                    if row['quality_model']:
                        c.execute("INSERT INTO quality_tasks(id,job_id,model,status) VALUES(?,?,?,'queued')",(uuid.uuid4().hex,row['id'],row['quality_model']))
            except Exception as e:
                with db() as c:
                    if isinstance(e, PiperSettingsError):
                        # Raised only before a Synthesize request was sent.
                        c.execute('DELETE FROM heavy_tts_guard WHERE singleton=1 AND job_id=?',(row['id'],))
                    c.execute("UPDATE jobs SET status='failed',error=? WHERE id=?",(str(e)[:500] or 'Generatie mislukt; controleer de engineverbinding.',row['id']))
        except Exception:
            app.logger.exception('Workerfout')
            time.sleep(3)

init()
if os.getenv('START_WORKER','1') == '1':
    threading.Thread(target=worker, daemon=True).start()
