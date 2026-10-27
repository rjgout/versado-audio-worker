"""Optional internal HTTP bridge to Wyoming Piper."""
from flask import Flask, request, Response, abort
from app.engines import synthesize
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 128 * 1024
@app.post('/synthesize')
def render():
    data = request.get_json(silent=True) or {}
    text = data.get('text')
    if not isinstance(text, str) or not 0 < len(text) <= 20000: abort(400)
    try:
        return Response(synthesize('piper', data.get('voice'), text), mimetype='audio/wav')
    except ValueError as e:
        return str(e), 400
