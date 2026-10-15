"""Run the reviewed web against a new synthetic-only DB, never a real DB."""
import argparse
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit

EMAIL = 'mobile-test@example.com'
PASSWORD = 'test-password-123'


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
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Use an unprivileged preview port')
    codespaces = os.environ.get('CODESPACES') == 'true'
    name = os.environ.get('CODESPACE_NAME', '')
    if codespaces and not re.fullmatch('[a-z0-9-]+', name):
        parser.error('A valid Codespace name is required')
    origin = f'https://{name}-{args.port}.app.github.dev' if codespaces else None
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    # Override any inherited DB setting before importing code that initializes it.
    with tempfile.TemporaryDirectory(prefix='yeobaek-web-preview-') as directory:
        os.environ['DATABASE_PATH'] = str(Path(directory) / 'synthetic.sqlite3')
        os.environ['COOKIE_SECURE'] = '1' if origin else '0'
        import app as module
        from flask import Response, request
        if origin:
            module.app.wsgi_app = PreviewOrigin(module.app.wsgi_app, origin, args.port)

        @module.app.get('/__web_preview__')
        def marker():
            return {'syntheticOnly': True, 'preview': 'web-download-order-v1',
                    'publicOrigin': origin}

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
                                    '서버를 멈추면 테스트 글은 초기화됩니다.</div>')
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
        module.app.run(host='0.0.0.0' if codespaces else '127.0.0.1',
                       port=args.port, debug=False, use_reloader=False)


if __name__ == '__main__':
    main()
