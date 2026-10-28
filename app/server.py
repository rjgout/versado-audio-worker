import hmac
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
from app.engines import VOICES, synthesize, validate_settings, stored_settings
from app.pronunciation import Rule, prepare

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
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, original TEXT NOT NULL, spoken TEXT NOT NULL, engine TEXT NOT NULL, voice TEXT NOT NULL, language TEXT NOT NULL, source TEXT NOT NULL, settings TEXT NOT NULL, rules TEXT NOT NULL, label TEXT NOT NULL, status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, audio TEXT);
        ''')
        if 'is_preview' not in [r['name'] for r in c.execute('PRAGMA table_info(jobs)')]:
            c.execute('ALTER TABLE jobs ADD COLUMN is_preview INTEGER NOT NULL DEFAULT 0')
            c.execute('UPDATE schema_version SET version=2')
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
    return {'piper': [v for v in VOICES['piper'] if v in installed], 'supertonic': supertonic}

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
    if voice and (not engine or voice not in VOICES[engine]): abort(400, 'Ongeldige stem')
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

@app.route('/api/previews', methods=['POST'])
@app.route('/api/jobs', methods=['GET','POST'])
@protected
def jobs():
    with db() as c:
        if request.method == 'GET':
            return jsonify([dict(x) for x in c.execute('SELECT * FROM jobs WHERE is_preview=0 ORDER BY created_at DESC, rowid DESC LIMIT 500')])
        p=payload()
        preview = request.path == '/api/previews'
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
        c.execute('INSERT INTO jobs(id,original,spoken,engine,voice,language,source,settings,rules,label,status,is_preview) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(jid,original,spoken,engine,voice,language,source,json.dumps(settings),json.dumps(used),label,'queued',int(preview)))
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

@app.route('/api/jobs/<jid>', methods=['PATCH','DELETE'])
@protected
def job_update(jid):
    with db() as c:
        row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row: abort(404)
        if request.method == 'PATCH':
            c.execute('UPDATE jobs SET label=? WHERE id=?',(bounded(payload().get('label',''),'label',200,False),jid))
        else:
            if row['status'] in ('queued','running'): abort(409)
            c.execute('DELETE FROM jobs WHERE id=?',(jid,))
            if row['audio']: (AUDIO / row['audio']).unlink(missing_ok=True)
    return {'ok':True}

@app.get('/api/jobs/<jid>/audio')
@protected
def audio(jid):
    with db() as c: row=c.execute("SELECT audio FROM jobs WHERE id=? AND status='done'",(jid,)).fetchone()
    if not row or not row['audio']: abort(404)
    return send_file(AUDIO / row['audio'], mimetype='audio/wav', as_attachment=request.args.get('download') == '1', download_name='versado.wav')

def worker():
    while True:
        try:
            cleanup_previews()
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                row=c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
                if row: c.execute("UPDATE jobs SET status='running' WHERE id=?",(row['id'],))
            if not row:
                time.sleep(1); continue
            try:
                audio_bytes=synthesize(row['engine'],row['voice'],row['spoken'],row['language'],stored_settings(row['engine'], json.loads(row['settings'])))
                if len(audio_bytes)>100*1024*1024: raise ValueError('Audio is te groot')
                import io
                with wave.open(io.BytesIO(audio_bytes),'rb') as w:
                    if not w.getnframes(): raise ValueError('Leeg WAV-bestand')
                filename=row['id']+'.wav'; temp=AUDIO/(filename+'.tmp')
                with temp.open('wb') as f:
                    f.write(audio_bytes); f.flush(); os.fsync(f.fileno())
                os.replace(temp,AUDIO/filename)
                with db() as c: c.execute("UPDATE jobs SET status='done',audio=? WHERE id=?",(filename,row['id']))
            except Exception as e:
                with db() as c: c.execute("UPDATE jobs SET status='failed',error=? WHERE id=?",(str(e)[:500],row['id']))
        except Exception:
            app.logger.exception('Workerfout')
            time.sleep(3)

init()
if os.getenv('START_WORKER','1') == '1':
    threading.Thread(target=worker, daemon=True).start()
