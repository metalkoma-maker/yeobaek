"""One-command, synthetic-only preview through a temporary Cloudflare URL.

Run with the project's Python environment in Codespaces. No Cloudflare login,
system installation, production data, or GitHub forwarded port is used.
"""
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import platform
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from run_web_preview import EMAIL, PASSWORD, quick_tunnel_origin

VERSION = '2026.10.0'
# Published GitHub release asset SHA256 digests, pinned with the version.
BINARIES = {
    'x86_64': ('amd64', 'd33ff2d14475178d2012c2c56beba87389ac5ded27649519f198a7d3134a99db'),
    'aarch64': ('arm64', 'e6422b9d4f72d3194bc5a38676f13667c06666523217b842a877d72a80b5ac08'),
}
ORIGIN_PATTERN = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com(?![a-zA-Z0-9.:-])')


def download_connector(directory):
    if platform.system() != 'Linux' or platform.machine() not in BINARIES:
        raise RuntimeError('이 실행기는 Linux Codespaces에서 사용하세요.')
    architecture, expected = BINARIES[platform.machine()]
    url = f'https://github.com/cloudflare/cloudflared/releases/download/{VERSION}/cloudflared-linux-{architecture}'
    target = directory / 'cloudflared'
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(url, timeout=30) as response, target.open('xb') as output:
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > 100 * 1024 * 1024:
                raise RuntimeError('연결 도구의 크기가 예상 범위를 넘었습니다.')
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != expected:
        raise RuntimeError('연결 도구 검증에 실패했습니다. 실행하지 않습니다.')
    target.chmod(0o700)
    return target


def marker_matches(payload, origin, run_id):
    return (isinstance(payload, dict) and payload.get('syntheticOnly') is True
            and payload.get('preview') == 'web-download-order-v1'
            and payload.get('publicOrigin') == origin and payload.get('runId') == run_id)


def check_preview(base_url, origin, run_id, *, public=False):
    # Only loopback probes skip proxy lookup; HTTPS probes keep inherited proxies/CA.
    handlers = [] if public else [urllib.request.ProxyHandler({})]
    opener = urllib.request.build_opener(*handlers, urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    timeout = 5 if public else 1
    with opener.open(base_url + '/__web_preview__', timeout=timeout) as response:
        if not marker_matches(json.load(response), origin, run_id):
            raise RuntimeError('현재 실행한 가짜 원고 서버의 응답이 아닙니다.')
    request = urllib.request.Request(base_url + '/', headers={'Accept': 'text/html', 'User-Agent': 'Mozilla/5.0'})
    with opener.open(request, timeout=timeout) as response:
        body = response.read(1024 * 1024).decode('utf-8')
        if (response.status != 200 or response.headers.get_content_type() != 'text/html'
                or 'attachment' in response.headers.get('Content-Disposition', '').lower()
                or '운영 전 미리보기 · 가짜 원고 전용' not in body):
            raise RuntimeError('첫 화면이 올바른 미리보기 HTML로 전달되지 않았습니다.')
    if public:
        request = urllib.request.Request(base_url + '/api/login', method='POST',
            headers={'Content-Type': 'application/json', 'Origin': origin},
            data=json.dumps({'email': EMAIL, 'password': PASSWORD}).encode())
        with opener.open(request, timeout=timeout) as response:
            if not json.load(response).get('csrf'):
                raise RuntimeError('미리보기 로그인 검증에 실패했습니다.')
        with opener.open(base_url + '/api/manuscripts', timeout=timeout) as response:
            if not isinstance(json.load(response), list):
                raise RuntimeError('로그인 후 원고 목록을 확인하지 못했습니다.')


def stop_process(process):
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def wait_for_preview(base_url, origin, run_id, processes, *, public=False):
    deadline = time.monotonic() + (90 if public else 20)
    last_error = '응답 대기 중'
    next_progress = time.monotonic() + 15
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError('미리보기 프로세스가 준비 중 종료됐습니다.')
        try:
            check_preview(base_url, origin, run_id, public=public)
            return
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
            last_error = str(error)
        if time.monotonic() >= next_progress:
            print('외부 화면·로그인 연결을 확인 중입니다…', flush=True)
            next_progress = time.monotonic() + 15
        time.sleep(1)
    raise RuntimeError('미리보기 확인 시간 초과: ' + last_error)


def main():
    if os.environ.get('CODESPACES') != 'true':
        raise RuntimeError('이 명령은 GitHub Codespaces 터미널에서 실행하세요.')
    # Catch dependency errors before downloading or publishing a tunnel.
    import flask  # noqa: F401
    tunnel = server = None
    run_id = secrets.token_hex(16)
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    with tempfile.TemporaryDirectory(prefix='yeobaek-preview-tunnel-') as temporary:
        directory = Path(temporary)
        print('임시 연결 도구를 내려받아 검증합니다…', flush=True)
        binary = download_connector(directory)
        # An explicit empty config prevents unrelated named tunnels/ingress use.
        config = directory / 'config.yml'
        config.write_text('{}\n')
        environment = {key: value for key, value in os.environ.items() if not key.startswith('TUNNEL_')}
        with socket.socket() as listener, (directory / 'tunnel.log').open('w+') as tunnel_log, (directory / 'server.log').open('w+') as server_log:
            # Reserve and inherit the socket so no existing app can be exposed.
            listener.bind(('127.0.0.1', 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            local = f'http://127.0.0.1:{port}'
            try:
                print('Cloudflare 임시 주소를 준비합니다…', flush=True)
                tunnel = subprocess.Popen([str(binary), 'tunnel', '--config', str(config),
                    '--no-autoupdate', '--protocol', 'http2', '--url', local],
                    stdout=tunnel_log, stderr=subprocess.STDOUT, env=environment)
                deadline = time.monotonic() + 45
                origin = None
                while time.monotonic() < deadline:
                    if tunnel.poll() is not None:
                        raise RuntimeError('Cloudflare 연결 도구가 종료됐습니다.')
                    match = ORIGIN_PATTERN.search((directory / 'tunnel.log').read_text(errors='replace'))
                    if match:
                        origin = quick_tunnel_origin(match.group())
                        break
                    time.sleep(0.25)
                if not origin:
                    raise RuntimeError('임시 주소를 만들지 못했습니다. Cloudflare 연결을 확인해야 합니다.')
                runner = Path(__file__).with_name('run_web_preview.py')
                server = subprocess.Popen([sys.executable, '-u', str(runner), '--port', str(port),
                    '--public-origin', origin, '--listen-fd', str(listener.fileno()), '--run-id', run_id],
                    pass_fds=(listener.fileno(),), stdout=server_log, stderr=subprocess.STDOUT, env=environment)
                wait_for_preview(local, origin, run_id, [server, tunnel])
                print('외부 주소에서 실제 화면과 테스트 로그인을 검증합니다…', flush=True)
                wait_for_preview(origin, origin, run_id, [server, tunnel], public=True)
                print('\n미리보기 응답·로그인 확인 완료. 아래 주소를 브라우저에서 여세요:', flush=True)
                print(origin + '/', flush=True)
                print('가짜 원고 전용입니다. 이 터미널을 켜두세요. 종료: Ctrl+C', flush=True)
                while server.poll() is None and tunnel.poll() is None:
                    time.sleep(1)
                raise RuntimeError('미리보기 연결이 종료됐습니다. 명령을 다시 실행하면 새 주소를 만듭니다.')
            finally:
                stop_process(tunnel)
                stop_process(server)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n미리보기를 종료했습니다.', flush=True)
    except Exception as error:
        print('미리보기 시작 실패: ' + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
