from pathlib import Path
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests import fake_ollama, fake_openrouter
from tests.helpers import temp_settings
from sowscout.web.server import make_server
from playwright.sync_api import sync_playwright

fake = fake_ollama.start(0)
cloud = fake_openrouter.start()
settings = temp_settings()
os.environ['OLLAMA_HOST'] = 'http://127.0.0.1:%s' % fake.server_address[1]
cfg = json.loads((ROOT / 'config/models.json').read_text(encoding='utf-8'))
cfg['providers']['ollama']['base_url'] = os.environ['OLLAMA_HOST']
cfg['providers']['openrouter']['base_url'] = 'http://127.0.0.1:%s/api/v1' % cloud.server_address[1]
cfg['providers']['deepseek']['base_url'] = 'http://127.0.0.1:%s/deepseek' % cloud.server_address[1]
cfg['providers']['openai']['base_url'] = 'http://127.0.0.1:%s/api/v1' % cloud.server_address[1]
cfg['providers']['openai'].pop('base_url_env', None)
config_path = settings.runs_dir.parent / 'models.json'
config_path.write_text(json.dumps(cfg), encoding='utf-8')
os.environ['SOWSCOUT_MODELS'] = str(config_path)
os.environ['OPENROUTER_API_KEY'] = 'test-key'
os.environ.pop('DEEPSEEK_API_KEY', None)
server = make_server('127.0.0.1', 0, settings)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = 'http://127.0.0.1:%s' % server.server_address[1]
screens = ROOT / 'examples/ui-v2'
screens.mkdir(exist_ok=True)
errors = []
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda err: errors.append(str(err)))
        page.goto(base)
        page.locator('#provider').wait_for()
        assert page.locator('#provider option[value="router"]').count() == 1
        page.screenshot(path=str(screens / '01-new-run.png'), full_page=True)
        for tab in ['models', 'connection', 'files', 'tools', 'history', 'eval', 'ask']:
            page.locator('nav.tabs a[href="#%s"]' % tab).click()
            page.locator('#view-' + tab).wait_for(state='visible')
            if tab == 'models':
                page.locator('#models-body table').wait_for()
                page.screenshot(path=str(screens / '02-models.png'), full_page=True)
        frame = page.frame_locator('#ask-frame')
        frame.locator('#input').wait_for()
        frame.locator('#input').fill('Hello')
        frame.locator('#input').press('Enter')
        frame.get_by_text('Hello! I am a fake model.', exact=False).wait_for(timeout=30000)
        page.screenshot(path=str(screens / '03-ask.png'), full_page=True)
        payload = {'case': 'wong', 'settings': {'provider': 'mock'}, 'control': {'ask_reviewer': False}}
        req = urllib.request.Request(base + '/api/runs', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as response:
            rid = json.load(response)['run_id']
        for _ in range(300):
            with urllib.request.urlopen(base + '/api/runs/' + rid) as response:
                result = json.load(response)
            if result['status'] == 'done':
                break
            time.sleep(.1)
        assert result['status'] == 'done', result['status']
        page.reload()
        page.locator('nav.tabs a[href="#history"]').click()
        page.get_by_role('button', name='Open', exact=True).first.click()
        page.locator('nav.tabs a[href="#results"]').click()
        page.get_by_role('button', name='Ask about this memo', exact=True).click()
        frame = page.frame_locator('#ask-frame')
        frame.locator('#input').wait_for()
        frame.get_by_text('SoWScout memo -', exact=False).first.wait_for(timeout=15000)
        page.screenshot(path=str(screens / '04-memo-chat.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        frame.locator('#app.sidebar-closed').wait_for()
        page.wait_for_timeout(300)
        page.screenshot(path=str(screens / '05-mobile-ask.png'), full_page=True)
        assert not errors, errors
        browser.close()
    print('PASS: all console tabs, local streamed chat, completed demo run, memo handoff, mobile render; no JavaScript errors')
finally:
    server.shutdown()
    server.server_close()
    fake.shutdown()
    cloud.shutdown()
