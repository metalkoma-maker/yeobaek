"""Exercise the real preview with a reserved socket and a synthetic HTTPS origin."""
import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import start_web_preview_tunnel as launcher
from run_web_preview import quick_tunnel_origin


class TunnelConfigurationTest(unittest.TestCase):
    def test_only_exact_quick_tunnel_origins_are_accepted(self):
        self.assertEqual(quick_tunnel_origin('https://preview-check.trycloudflare.com'),
                         'https://preview-check.trycloudflare.com')
        for value in ('http://preview.trycloudflare.com', 'https://example.com',
                      'https://preview.trycloudflare.com/', 'https://preview.trycloudflare.com:443',
                      'https://preview.trycloudflare.com?x=1', 'https://preview.trycloudflare.com#x',
                      'https://user@preview.trycloudflare.com', 'https://a.b.trycloudflare.com',
                      'https://-a.trycloudflare.com', 'https://a-.trycloudflare.com',
                      'https://PREVIEW.trycloudflare.com', 'https://preview.trycloudflare.com.evil.test'):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                quick_tunnel_origin(value)

    def test_readiness_rejects_an_old_or_unrelated_server(self):
        expected = {'syntheticOnly': True, 'preview': 'web-download-order-v1',
                    'publicOrigin': 'https://preview.trycloudflare.com', 'runId': 'current'}
        self.assertTrue(launcher.marker_matches(expected, expected['publicOrigin'], 'current'))
        for change in ({'runId': 'old'}, {'syntheticOnly': False}, {'publicOrigin': 'https://other.trycloudflare.com'},
                       {'preview': 'something-else'}):
            self.assertFalse(launcher.marker_matches({**expected, **change}, expected['publicOrigin'], 'current'))

    def test_tampered_download_never_becomes_executable(self):
        import io
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(launcher.platform, 'system', return_value='Linux'), \
             patch.object(launcher.platform, 'machine', return_value='x86_64'), \
             patch.object(launcher.urllib.request, 'urlopen', return_value=io.BytesIO(b'bad download')):
            with self.assertRaisesRegex(RuntimeError, '검증'):
                launcher.download_connector(Path(directory))
            self.assertFalse((Path(directory) / 'cloudflared').stat().st_mode & 0o111)

    def test_launcher_cleans_up_on_failed_public_probe_and_on_interrupt(self):
        # A stand-in connector creates no external tunnel. The app and socket are real.
        real_popen = subprocess.Popen
        real_sleep = time.sleep
        real_wait = launcher.wait_for_preview
        for fail_public in (True, False):
            with self.subTest(fail_public=fail_public):
                processes = []
                state = {'checked': False}
                directories = []
                def fake_connector(directory):
                    directories.append(directory)
                    binary = directory / 'cloudflared'
                    binary.write_text('#!' + sys.executable + '\nimport time\n'
                        'print("https://synthetic-run.trycloudflare.com", flush=True)\ntime.sleep(300)\n')
                    binary.chmod(0o700)
                    return binary
                def start(*args, **kwargs):
                    process = real_popen(*args, **kwargs)
                    processes.append(process)
                    return process
                def probe(base, origin, run_id, children, *, public=False):
                    if public:
                        if fail_public:
                            raise RuntimeError('simulated external connection failure')
                        state['checked'] = True
                    else:
                        real_wait(base, origin, run_id, children)
                def wait(seconds):
                    if state['checked']:
                        raise KeyboardInterrupt
                    real_sleep(seconds)
                output = io.StringIO()
                with patch.dict(os.environ, {'CODESPACES': 'true'}), \
                     patch.object(launcher, 'download_connector', side_effect=fake_connector), \
                     patch.object(launcher.subprocess, 'Popen', side_effect=start), \
                     patch.object(launcher, 'wait_for_preview', side_effect=probe), \
                     patch.object(launcher, 'time', SimpleNamespace(monotonic=time.monotonic, sleep=wait)), \
                     patch.object(launcher.signal, 'signal'), redirect_stdout(output):
                    with self.assertRaises(RuntimeError if fail_public else KeyboardInterrupt):
                        launcher.main()
                self.assertEqual(len(processes), 2)
                self.assertTrue(all(process.poll() is not None for process in processes))
                self.assertTrue(all(not directory.exists() for directory in directories))
                self.assertEqual('미리보기 응답·로그인 확인 완료' in output.getvalue(), not fail_public)


class RealTunnelPreviewTest(unittest.TestCase):
    def test_reserved_loopback_server_origin_cookie_csrf_and_isolation(self):
        origin = 'https://synthetic-test.trycloudflare.com'
        with tempfile.TemporaryDirectory() as temporary, socket.socket() as listener:
            directory = Path(temporary)
            sentinel = directory / 'not-a-preview-database'
            sentinel.write_text('This inherited database must not be opened or changed.')
            listener.bind(('127.0.0.1', 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            base = f'http://127.0.0.1:{port}'
            environment = {**os.environ, 'DATABASE_PATH': str(sentinel), 'TMPDIR': temporary,
                           'CODESPACES': 'true', 'CODESPACE_NAME': 'synthetic-codespace'}
            with (directory / 'server.log').open('w+') as log:
                process = subprocess.Popen([sys.executable, '-u', str(ROOT / 'tools/run_web_preview.py'),
                    '--port', str(port), '--public-origin', origin, '--listen-fd', str(listener.fileno()),
                    '--run-id', 'current'], pass_fds=(listener.fileno(),), env=environment,
                    stdout=log, stderr=subprocess.STDOUT)
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                def request(path, data=None, headers=None, method=None):
                    body = None if data is None else json.dumps(data).encode()
                    req = urllib.request.Request(base + path, data=body, method=method,
                        headers={'Content-Type': 'application/json', **(headers or {})})
                    try:
                        response = opener.open(req, timeout=2)
                    except urllib.error.HTTPError as error:
                        response = error
                    with response:
                        return response.status, response.headers, response.read()
                try:
                    for _ in range(50):
                        if process.poll() is not None:
                            self.fail('Preview exited: ' + (directory / 'server.log').read_text())
                        try:
                            launcher.check_preview(base, origin, 'current')
                            break
                        except (OSError, ValueError, RuntimeError, urllib.error.URLError):
                            time.sleep(0.1)
                    else:
                        self.fail('Preview readiness timed out')
                    status, headers, body = request('/')
                    self.assertEqual(status, 200)
                    self.assertEqual(headers.get_content_type(), 'text/html')
                    self.assertIn('운영 전 미리보기', body.decode())
                    credentials = {'email': launcher.EMAIL, 'password': launcher.PASSWORD}
                    status, headers, body = request('/api/login', credentials, {'Origin': origin})
                    self.assertEqual(status, 200)
                    cookie = headers['Set-Cookie']
                    self.assertIn('Secure;', cookie)
                    csrf = json.loads(body)['csrf']
                    auth = {'Origin': origin, 'Cookie': cookie.split(';')[0]}
                    status, _, body = request('/api/manuscript-order', headers=auth)
                    self.assertEqual(status, 200)
                    order = json.loads(body)
                    self.assertEqual(len(order['ids']), 3)
                    reversed_order = {**order, 'ids': list(reversed(order['ids']))}
                    self.assertEqual(request('/api/manuscript-order', reversed_order, auth, 'PUT')[0], 403)
                    self.assertEqual(request('/api/manuscript-order', reversed_order,
                        {**auth, 'X-CSRF-Token': csrf, 'Origin': 'https://foreign.example'}, 'PUT')[0], 403)
                    status, _, _ = request('/api/manuscript-order', reversed_order,
                        {**auth, 'X-CSRF-Token': csrf}, 'PUT')
                    self.assertEqual(status, 200)
                    # A second login reads the same account's saved order.
                    status, second_headers, _ = request('/api/login', credentials, {'Origin': origin})
                    self.assertEqual(status, 200)
                    _, _, body = request('/api/manuscript-order', headers={
                        'Cookie': second_headers['Set-Cookie'].split(';')[0]})
                    self.assertEqual(json.loads(body)['ids'], reversed_order['ids'])
                    self.assertEqual(sentinel.read_text(), 'This inherited database must not be opened or changed.')
                finally:
                    launcher.stop_process(process)
            self.assertFalse(list(directory.glob('yeobaek-web-preview-*')), 'Temporary preview DB was not removed')


if __name__ == '__main__':
    unittest.main()
