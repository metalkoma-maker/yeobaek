"""Run a temporary synthetic iPhone preview on a GitHub Actions runner."""
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from start_web_preview_tunnel import ORIGIN_PATTERN, download_connector, stop_process

ROOT = Path(__file__).resolve().parents[1]
EMAIL = 'mobile-test@example.com'
PASSWORD = 'test-password-123'


def tunnel_url(binary, config, directory, name, port, environment):
    log = (directory / (name + '.log')).open('w+')
    local_host = 'localhost' if name == 'metro' else '127.0.0.1'
    process = subprocess.Popen([str(binary), 'tunnel', '--config', str(config),
                                '--no-autoupdate', '--protocol', 'http2',
                                '--url', f'http://{local_host}:{port}'],
                               stdout=log, stderr=subprocess.STDOUT, env=environment)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(name + ' tunnel exited before creating a URL')
        match = ORIGIN_PATTERN.search((directory / (name + '.log')).read_text(errors='replace'))
        if match:
            return process, match.group(), log
        time.sleep(0.25)
    raise RuntimeError(name + ' tunnel did not create a URL')


def wait_for(check, processes, description, seconds=90):
    deadline = time.monotonic() + seconds
    last_error = 'not ready'
    while time.monotonic() < deadline:
        if any(p.poll() is not None for p in processes):
            raise RuntimeError(description + ': a child process exited')
        try:
            check()
            return
        except (OSError, ValueError, AssertionError, RuntimeError, urllib.error.URLError) as error:
            last_error = str(error)
        time.sleep(1)
    raise RuntimeError(description + ': ' + last_error)


def marker(url, run_id, public_origin):
    with urllib.request.urlopen(url + '/__mobile_test__', timeout=5) as response:
        body = json.load(response)
    assert body.get('syntheticOnly') is True
    assert body.get('protocol') == 'yeobaek-mobile-test-v1'
    assert body.get('runId') == run_id
    assert body.get('publicOrigin') == public_origin


def public_login(url):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    data = json.dumps({'email': EMAIL, 'password': PASSWORD}).encode()
    request = urllib.request.Request(url + '/api/login', data=data,
        headers={'Content-Type': 'application/json', 'Origin': url})
    with opener.open(request, timeout=8) as response:
        signed_in = json.load(response)
    assert signed_in.get('email') == EMAIL
    with opener.open(url + '/api/manuscripts', timeout=8) as response:
        manuscripts = json.load(response)
    assert len(manuscripts) == 1 and manuscripts[0]['title'] == '테스트 원고'


def metro_status(url):
    with urllib.request.urlopen(url + '/status', timeout=8) as response:
        assert response.read(100).strip() == b'packager-status:running'


def expo_go_link(url):
    with urllib.request.urlopen(url + '/_expo/open?platform=ios&runtime=expo', timeout=8) as response:
        info = json.load(response)
    link = info.get('url')
    if not isinstance(link, str) or not link.startswith('exp://'):
        raise RuntimeError('Expo CLI did not provide an iOS Expo Go link')
    return link


def check_expo_go_link(url, expected):
    actual = expo_go_link(url)
    if actual != expected:
        raise RuntimeError('Expo CLI link differs from preview page')


def open_page(api_url, expo_url):
    with urllib.request.urlopen(api_url + '/_mobile/open', timeout=8) as response:
        page = response.read(20_000).decode('utf-8')
    assert 'href="' + expo_url + '"' in page


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('The temporary preview is launched by GitHub Actions only')
    import flask  # noqa: F401 - fail before publishing URLs if Python deps are missing
    processes = []
    logs = []
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    with tempfile.TemporaryDirectory(prefix='yeobaek-mobile-preview-') as temporary:
        directory = Path(temporary)
        try:
            binary = download_connector(directory)
            config = directory / 'config.yml'
            config.write_text('{}\n')
            environment = {key: value for key, value in os.environ.items() if not key.startswith('TUNNEL_')}
            api_tunnel, api_url, api_log = tunnel_url(binary, config, directory, 'api', 8000, environment)
            processes.append(api_tunnel); logs.append(api_log)
            metro_tunnel, metro_url, metro_log = tunnel_url(binary, config, directory, 'metro', 8081, environment)
            processes.append(metro_tunnel); logs.append(metro_log)
            run_id = secrets.token_hex(16)
            expo_url = 'exp://' + urlsplit(metro_url).hostname
            environment.update(YEOBAEK_MOBILE_PREVIEW='true', EXPO_PUBLIC_YEOBAEK_MODE='synthetic',
                               EXPO_PUBLIC_TEST_API_URL=api_url, EXPO_PACKAGER_PROXY_URL=metro_url,
                               YEOBAEK_EXPO_LINK=expo_url,
                               YEOBAEK_TEST_RUN_ID=run_id, CI='1')
            api_log = (directory / 'server.log').open('w+')
            logs.append(api_log)
            api = subprocess.Popen([sys.executable, '-u', str(ROOT / 'tools/run_mobile_test.py')],
                                   cwd=ROOT, stdout=api_log, stderr=subprocess.STDOUT, env=environment)
            processes.append(api)
            wait_for(lambda: marker('http://127.0.0.1:8000', run_id, api_url), processes, 'local synthetic API', 30)
            metro_log = (directory / 'expo.log').open('w+')
            logs.append(metro_log)
            metro = subprocess.Popen(['npm', 'start', '--', '--localhost', '--port', '8081'],
                                     cwd=ROOT / 'mobile', stdout=metro_log,
                                     stderr=subprocess.STDOUT, env=environment)
            processes.append(metro)
            wait_for(lambda: metro_status('http://localhost:8081'), processes, 'local Expo Metro', 90)
            wait_for(lambda: marker(api_url, run_id, api_url), processes, 'public synthetic API')
            wait_for(lambda: public_login(api_url), processes, 'public test login')
            wait_for(lambda: metro_status(metro_url), processes, 'public Expo Metro')
            wait_for(lambda: check_expo_go_link(metro_url, expo_url), processes, 'Expo CLI iOS link')
            wait_for(lambda: open_page(api_url, expo_url), processes, 'public Expo Go link')
            print('MOBILE_EXPO_URL=' + expo_url, flush=True)
            print('EXPO_AUTH_CONFIGURED=' + ('true' if environment.get('EXPO_TOKEN') else 'false'), flush=True)
            print('MOBILE_PREVIEW_URL=' + api_url + '/_mobile/open', flush=True)
            print('Synthetic data only; expires within 55 minutes.', flush=True)
            deadline = time.monotonic() + 55 * 60
            while time.monotonic() < deadline:
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError('The temporary preview stopped early')
                time.sleep(2)
        except Exception:
            for name in ('api.log', 'metro.log', 'server.log', 'expo.log'):
                path = directory / name
                if path.exists():
                    print('--- ' + name + ' ---', file=sys.stderr)
                    print('\n'.join(path.read_text(errors='replace').splitlines()[-12:]), file=sys.stderr)
            raise
        finally:
            for process in reversed(processes):
                stop_process(process)
            for log in logs:
                log.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Mobile preview stopped.', flush=True)
    except Exception as error:
        print('Mobile preview failed: ' + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
