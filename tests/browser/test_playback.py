"""Real Chromium regression coverage; engine/API responses and WAV are simulated."""
import http.server
import io
import json
import os
from pathlib import Path
import threading
import wave

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def test_playback_survives_polling():
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT / 'app'), **kwargs)
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    wav = io.BytesIO()
    with wave.open(wav, 'wb') as sound:
        sound.setnchannels(1); sound.setsampwidth(2); sound.setframerate(8000)
        sound.writeframes(b'\0\0' * 8000 * 35)
    audio = wav.getvalue()
    state = {'jobs': [dict(id='one', label='Eerste', engine='piper', voice='ronnie', created_at='nu', status='done', error='', original='Hallo', spoken='Hallo', settings='{}', rules='[]'), dict(id='two', label='Volgende', engine='piper', voice='ronnie', created_at='nu', status='queued', error='', original='Test', spoken='Test', settings='{}', rules='[]')]}
    rules = [dict(id=1, language='nl', source='bofm', original='Nephi', replacement='Nefi', status='proposal', version=1, note='', engine=None, voice=None)]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_EXECUTABLE_PATH'), args=['--no-sandbox', '--autoplay-policy=no-user-gesture-required'])
            context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
            page = context.new_page()
            def routes(route):
                path = route.request.url.split('?')[0]
                if path.endswith('/api/session'): result = {'authenticated': True, 'csrf': 'test'}
                elif path.endswith('/api/voices'): result = {'piper': ['ronnie'], 'supertonic': []}
                elif path.endswith('/api/jobs'): result = state['jobs']
                elif path.endswith('/api/rules'): result = rules
                elif path.endswith('/api/previews') and route.request.method == 'POST': result = {'id': 'preview'}
                elif path.endswith('/api/previews/preview'): result = {'id': 'preview', 'status': 'done'}
                elif path.endswith('/audio'):
                    route.fulfill(status=200, body=audio, content_type='audio/wav', headers={'Accept-Ranges': 'bytes'}); return
                else:
                    route.fallback(); return
                route.fulfill(status=200, content_type='application/json', body=json.dumps(result))
            page.route('**/api/**', routes)
            page.goto(f'http://127.0.0.1:{server.server_port}/templates/index.html')
            card = page.locator('[data-job-id="one"]')
            card.locator('summary').click()
            player = card.locator('audio')
            player.evaluate('(a) => { window.originalAudio = a; a.play() }')
            page.wait_for_function('document.querySelector("[data-job-id=one] audio").currentTime > 1')
            state['jobs'][1]['status'] = 'running'
            page.wait_for_function('document.querySelector("[data-job-id=two] .muted").textContent.includes("running")', timeout=10000)
            state['jobs'][1]['status'] = 'done'
            page.wait_for_selector('[data-job-id="two"] audio', timeout=10000)
            page.wait_for_function('document.querySelector("[data-job-id=one] audio").currentTime > 21', timeout=30000)
            assert player.evaluate('(a) => a === window.originalAudio && !a.paused && a.currentTime > 21')
            assert card.locator('details').evaluate('(d) => d.open')
            page.evaluate('''async () => {
                const originalFetch = window.fetch; let first = true;
                window.fetch = async (url, options) => {
                    if (url === '/api/jobs' && first) {
                        first = false;
                        await new Promise(resolve => setTimeout(resolve, 600));
                        return new Response(JSON.stringify([{id:'one',label:'verouderd',engine:'piper',voice:'ronnie',created_at:'nu',status:'done',original:'x',spoken:'x',settings:'{}',rules:'[]'}]), {status:200});
                    }
                    return originalFetch(url, options);
                };
                const running = refresh(); refresh(); await running; window.fetch = originalFetch;
            }''')
            assert card.locator('h3').inner_text() == 'Eerste'
            assert page.locator('[data-job-id="two"]').count() == 1
            player.evaluate('(a) => a.pause()')
            paused = player.evaluate('(a) => a.currentTime')
            page.wait_for_timeout(4500)
            assert player.evaluate('(a) => a.paused && a === window.originalAudio')
            assert abs(player.evaluate('(a) => a.currentTime') - paused) < .3
            player.evaluate('(a) => { a.currentTime = 4; a.play() }')
            page.wait_for_function('document.querySelector("[data-job-id=one] audio").currentTime > 5')
            page.locator('[data-tab="dictionary"]').click()
            page.locator('[data-rule-id="1"] .play').click()
            preview = page.locator('[data-rule-id="1"] audio')
            preview.wait_for(timeout=10000)
            preview.evaluate('(a) => { window.originalPreview = a; a.play() }')
            page.wait_for_timeout(9000)
            assert preview.evaluate('(a) => a === window.originalPreview && !a.paused && a.currentTime > 6')
            browser.close()
    finally:
        server.shutdown()
