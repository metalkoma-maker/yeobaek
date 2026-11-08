"""Run the reviewed web against a new synthetic-only DB, never a real DB."""
import argparse
import html
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
from urllib.parse import urlsplit

EMAIL = 'mobile-test@example.com'
PASSWORD = 'test-password-123'


def quick_tunnel_origin(value):
    """Accept only an exact HTTPS origin for a single Cloudflare Quick Tunnel."""
    if not re.fullmatch(r'https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.trycloudflare\.com', value):
        raise argparse.ArgumentTypeError('Use an exact https://NAME.trycloudflare.com origin')
    return value


class PreviewOrigin:
    """Restore only this Codespace's same-origin port-forward transformation."""
    def __init__(self, app, origin, port):
        self.app, self.origin, self.port = app, origin, port
        self.host = urlsplit(origin).netloc

    def __call__(self, environ, start_response):
        environ = environ.copy()
        received = environ.get('HTTP_ORIGIN', '')
        if received in (f'http://localhost:{self.port}', f'https://localhost:{self.port}'):
            try:
                referrer = urlsplit(environ.get('HTTP_REFERER', ''))
                same = referrer.scheme == 'https' and referrer.netloc == self.host
            except ValueError:
                same = False
            if same and environ.get('HTTP_SEC_FETCH_SITE') == 'same-origin':
                environ['HTTP_ORIGIN'] = self.origin
        environ.update({'wsgi.url_scheme': 'https', 'HTTP_HOST': self.host,
                        'SERVER_NAME': self.host, 'SERVER_PORT': '443'})
        return self.app(environ, start_response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8001)
    parser.add_argument('--public-origin', type=quick_tunnel_origin,
                        help='HTTPS origin of a temporary Cloudflare Quick Tunnel')
    parser.add_argument('--listen-fd', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--run-id', default='', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Use an unprivileged preview port')
    if args.listen_fd is not None:
        if not args.public_origin:
            parser.error('An inherited socket requires an explicit preview origin')
        with socket.fromfd(args.listen_fd, socket.AF_INET, socket.SOCK_STREAM) as listener:
            if (listener.getsockname() != ('127.0.0.1', args.port)
                    or not listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)):
                parser.error('The preview socket must already listen on loopback')
    codespaces = os.environ.get('CODESPACES') == 'true'
    name = os.environ.get('CODESPACE_NAME', '')
    if codespaces and not args.public_origin and not re.fullmatch('[a-z0-9-]+', name):
        parser.error('A valid Codespace name is required')
    origin = args.public_origin or (f'https://{name}-{args.port}.app.github.dev' if codespaces else None)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    # Override any inherited DB setting before importing code that initializes it.
    with tempfile.TemporaryDirectory(prefix='yeobaek-web-preview-') as directory:
        os.environ['DATABASE_PATH'] = str(Path(directory) / 'synthetic.sqlite3')
        os.environ['COOKIE_SECURE'] = '1' if origin else '0'
        os.environ['SMTP_HOST'] = 'synthetic-preview.invalid'
        os.environ['SMTP_FROM'] = 'preview@synthetic.invalid'
        os.environ['SMTP_USERNAME'] = os.environ['SMTP_PASSWORD'] = ''
        os.environ['APP_PUBLIC_URL'] = origin or f'https://localhost:{args.port}'
        import app as module
        from flask import Response, request
        messages = []

        def fake_mail(address, subject, body):
            if address == EMAIL:
                messages.append((subject, body))
                del messages[:-10]
        module.send_account_mail = fake_mail

        @module.app.get('/_preview/mail')
        def preview_mail():
            items = []
            for subject, body in reversed(messages):
                match = re.search(r'https://[^\s]+/#reset=[A-Za-z0-9_-]{43}', body)
                link = f'<p><a href="{html.escape(match.group(0), quote=True)}">비밀번호 재설정 링크 열기</a></p>' if match else ''
                items.append(f'<article><h2>{html.escape(subject)}</h2><pre>{html.escape(body)}</pre>{link}</article>')
            content = ''.join(items) or '<p>아직 테스트 메일이 없습니다.</p>'
            response = Response('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                            '<title>소설여백 테스트 메일함</title><style>body{font:16px sans-serif;max-width:700px;margin:32px auto;padding:16px;color:#172b44}'
                            'article{border:1px solid #dce3eb;border-radius:10px;padding:18px;margin:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}'
                            '</style><h1>가짜 계정 테스트 메일함</h1><p>실제 메일은 발송되지 않습니다. <a href="/">테스트 웹으로 돌아가기</a></p>'
                            + content + '</html>', mimetype='text/html')
            response.headers['Cache-Control'] = 'no-store'
            return response
        if origin:
            module.app.wsgi_app = PreviewOrigin(module.app.wsgi_app, origin, args.port)

        @module.app.get('/__web_preview__')
        def marker():
            return {'syntheticOnly': True, 'preview': 'web-download-order-v1',
                    'publicOrigin': origin, 'runId': args.run_id}

        @module.app.get('/_preview/banner.css')
        def preview_style():
            return Response('#previewNotice{position:fixed;top:0;left:0;right:0;z-index:1000;'
                            'padding:9px 16px;background:#fff2d5;color:#523e18;font-size:13px;'
                            'line-height:1.5;text-align:center}body{padding-top:58px}'
                            'main{height:calc(100dvh - 58px)}', mimetype='text/css')

        @module.app.get('/_preview/login.js')
        def preview_login():
            return Response("document.getElementById('email').value='" + EMAIL + "';"
                            "document.getElementById('password').value='" + PASSWORD + "';",
                            mimetype='application/javascript')

        @module.app.after_request
        def label_preview(response):
            if request.path == '/' and response.status_code == 200:
                response.direct_passthrough = False
                html = response.get_data(as_text=True)
                html = html.replace('</head>', '<link rel="stylesheet" href="/_preview/banner.css"></head>')
                html = html.replace('<body>', '<body><div id="previewNotice" role="note">'
                                    '<b>운영 전 미리보기 · 가짜 원고 전용</b><br>'
                                    '서버를 멈추면 테스트 글은 초기화됩니다. '
                                    '<a href="/_preview/mail">테스트 메일함</a></div>')
                html = html.replace('</body>', '<script defer src="/_preview/login.js"></script></body>')
                response.set_data(html)
                response.headers['Cache-Control'] = 'no-store'
                for header in ('ETag', 'Last-Modified'):
                    response.headers.pop(header, None)
            return response

        base_url = origin or f'http://localhost:{args.port}'
        with module.app.test_client() as client:
            registered = client.post('/api/register', base_url=base_url,
                                     json={'email': EMAIL, 'password': PASSWORD})
            if registered.status_code != 200:
                raise RuntimeError('Could not create the synthetic account')
            headers = {'X-CSRF-Token': registered.json['csrf']}
            for title in ('봄의 원고', '여름의 원고', '가을의 원고'):
                result = client.post('/api/manuscripts', base_url=base_url, json={}, headers=headers)
                if result.status_code != 201:
                    raise RuntimeError('Could not create a synthetic manuscript')
                saved = client.put('/api/manuscripts/' + result.json['id'], base_url=base_url,
                                   headers=headers, json={'title': title,
                                   'body': '미리보기용 가짜 원고입니다.\n이 글로 드래그와 내려받기를 확인하세요.',
                                   'version': 0})
                if saved.status_code != 200:
                    raise RuntimeError('Could not seed the synthetic manuscript')
        print('WEB PREVIEW: ' + (origin or f'http://127.0.0.1:{args.port}'), flush=True)
        print('Synthetic account: ' + EMAIL + ' / ' + PASSWORD, flush=True)
        print('Temporary fake DB only. Stopping the server removes preview data.', flush=True)
        if args.listen_fd is not None:
            from werkzeug.serving import make_server
            server = make_server('127.0.0.1', args.port, module.app,
                                 threaded=True, fd=args.listen_fd)
            os.close(args.listen_fd)
            try:
                server.serve_forever()
            finally:
                server.server_close()
        else:
            module.app.run(host='0.0.0.0' if codespaces and not args.public_origin else '127.0.0.1',
                           port=args.port, debug=False, use_reloader=False)


if __name__ == '__main__':
    main()
