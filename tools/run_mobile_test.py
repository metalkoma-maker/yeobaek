"""Start the unchanged Flask app against a NEW synthetic-only temporary DB.
No backup scripts, deployment or production database access.
"""
import os
import sys
import tempfile
import secrets
from html import escape
from pathlib import Path
from mobile_test_proxy import configured_origin, SyntheticPublicOrigin

TEST_RUNNER_VERSION = 'codespaces-origin-v2'


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    origin = configured_origin()
    # Set before importing app: importing it initializes its configured DB.
    with tempfile.TemporaryDirectory(prefix='yeobaek-mobile-test-') as directory:
        os.environ['DATABASE_PATH'] = str(Path(directory) / 'synthetic.sqlite3')
        os.environ['COOKIE_SECURE'] = '1' if origin else '0'
        import app as module
        from flask import request
        if origin:
            module.app.wsgi_app = SyntheticPublicOrigin(module.app.wsgi_app, origin)
        run_id = os.environ.get('YEOBAEK_TEST_RUN_ID') or secrets.token_hex(16)
        @module.app.get('/__mobile_test__')
        def test_marker():
            return {'syntheticOnly': True, 'protocol': 'yeobaek-mobile-test-v1',
                    'runnerVersion': TEST_RUNNER_VERSION, 'runId': run_id,
                    'publicOrigin': origin}

        @module.app.after_request
        def test_origin_diagnostic(response):
            if (request.path.startswith('/api/') and response.status_code == 403
                    and request.headers.get('Origin') != request.host_url.rstrip('/')):
                # Only origins and Fetch Metadata, never credentials, cookies,
                # document bodies, or Referer paths/query strings.
                received = request.environ.get('yeobaek.test_received_origin', '')[:200]
                print('TEST_ORIGIN_REJECTED received=' + repr(received)
                      + ' expected=' + repr(request.host_url.rstrip('/'))
                      + ' site=' + repr(request.headers.get('Sec-Fetch-Site', '')[:30]), flush=True)
            return response

        @module.app.get('/_mobile/open')
        def open_mobile():
            link = escape(os.environ.get('YEOBAEK_EXPO_LINK', ''), quote=True)
            return ('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<h1>여백 아이폰 테스트</h1><p>가짜 원고 전용입니다.</p>'
                    f'<p><a href="{link}">Expo Go에서 여백 열기</a></p>'
                    '<p><a href="/">같은 계정의 테스트 웹 열기</a></p>'
                    '<p>mobile-test@example.com / test-password-123</p>')
        module.app.config['TESTING'] = True
        with module.app.test_client() as client:
            result = client.post('/api/register', json={
                'email': 'mobile-test@example.com', 'password': 'test-password-123'})
            if result.status_code != 200:
                raise RuntimeError('Could not create synthetic test account')
            headers = {'X-CSRF-Token': result.json['csrf']}
            doc = client.post('/api/manuscripts', json={}, headers=headers).json
            saved = client.put('/api/manuscripts/' + doc['id'], headers=headers,
                               json={'title': '테스트 원고', 'body': '가 나\n다😀', 'version': 0})
            if saved.status_code != 200:
                raise RuntimeError('Could not create synthetic test manuscript')
        module.app.config['TESTING'] = False
        print('Synthetic-only test server: http://0.0.0.0:8000')
        print('Test runner: ' + TEST_RUNNER_VERSION)
        print('Account: mobile-test@example.com / test-password-123')
        print('A fresh temporary DB is used on every run; stopping removes test data.')
        module.app.run(host='0.0.0.0', port=8000, debug=False, use_reloader=False)


if __name__ == '__main__':
    main()
