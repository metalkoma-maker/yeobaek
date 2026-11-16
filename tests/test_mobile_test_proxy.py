"""Browser Origin/CSRF behind a fake HTTPS Codespaces proxy, temporary DB only."""
import os
import unittest
from unittest.mock import patch
from test_app import module
from tools.mobile_test_proxy import configured_origin, SyntheticPublicOrigin


class MobileTestProxyTest(unittest.TestCase):
    def test_reproduces_browser_rejection_then_preserves_csrf_with_fixed_origin(self):
        origin = 'https://synthetic-cloud-8000.app.github.dev'
        request = {'base_url': origin.replace('https:', 'http:'), 'headers': {'Origin': origin}}
        credentials = {'email': 'synthetic-proxy@example.com', 'password': 'test-password-123'}
        # The unchanged app sees internal HTTP and rejects the actual browser origin.
        self.assertEqual(module.app.test_client().post('/api/register', json=credentials, **request).status_code, 403)
        old = module.app.wsgi_app
        module.app.wsgi_app = SyntheticPublicOrigin(old, origin)
        try:
            with patch.object(module, 'SECURE', True):
                client = module.app.test_client()
                registered = client.post('/api/register', json=credentials, **request)
                self.assertEqual(registered.status_code, 200)
                self.assertIn('Secure;', registered.headers['Set-Cookie'])
                headers = {'Origin': origin, 'X-CSRF-Token': registered.json['csrf']}
                doc = client.post('/api/manuscripts', json={}, base_url=origin, headers=headers)
                self.assertEqual(doc.status_code, 201)
                route = '/api/manuscripts/' + doc.json['id']
                updated = client.put(route, json={'title': '가짜', 'body': '가나다', 'version': 0}, base_url=origin, headers=headers)
                self.assertEqual(updated.status_code, 200)
                self.assertEqual(updated.json['total'], 3)
                self.assertEqual(client.put(route, json={}, base_url=origin, headers={'Origin': origin}).status_code, 403)
                foreign = {**headers, 'Origin': 'https://other.example.test', 'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'other.example.test'}
                self.assertEqual(client.put(route, json={}, base_url=origin, headers=foreign).status_code, 403)
                # Expo native requests have no browser Origin and keep normal authentication.
                self.assertEqual(module.app.test_client().post('/api/login', json=credentials, base_url=origin).status_code, 200)
        finally:
            module.app.wsgi_app = old

    def test_codespaces_rewritten_origins_support_login_and_save_with_csrf(self):
        origin = 'https://synthetic-cloud-8000.app.github.dev'
        old = module.app.wsgi_app
        module.app.wsgi_app = SyntheticPublicOrigin(old, origin)
        try:
            with patch.object(module, 'SECURE', True):
                for scheme in ('http', 'https'):
                    with self.subTest(scheme=scheme):
                        credentials = {'email': f'proxy-loopback-{scheme}@example.com',
                                       'password': 'test-password-123'}
                        # Codespaces changes Origin while preserving the public Referer.
                        browser = {'Origin': f'{scheme}://localhost:8000',
                                   'Referer': origin + '/', 'Sec-Fetch-Site': 'same-origin'}
                        client = module.app.test_client()
                        registered = client.post('/api/register', json=credentials,
                                                 base_url=origin, headers=browser)
                        self.assertEqual(registered.status_code, 200)
                        self.assertIn('Secure;', registered.headers['Set-Cookie'])
                        signed_in = module.app.test_client()
                        login = signed_in.post('/api/login', json=credentials,
                                               base_url=origin, headers=browser)
                        self.assertEqual(login.status_code, 200)
                        self.assertEqual(signed_in.get('/api/me', base_url=origin).json['email'],
                                         credentials['email'])
                        authenticated = {**browser, 'X-CSRF-Token': login.json['csrf']}
                        doc = signed_in.post('/api/manuscripts', json={}, base_url=origin,
                                             headers=authenticated)
                        self.assertEqual(doc.status_code, 201)
                        route = '/api/manuscripts/' + doc.json['id']
                        updated = signed_in.put(route, json={'title': '가짜', 'body': '가나다',
                                                             'version': 0},
                                                base_url=origin, headers=authenticated)
                        self.assertEqual(updated.status_code, 200)
                        self.assertEqual(updated.json['total'], 3)
                        for token in (None, 'foreign-token'):
                            headers = dict(browser)
                            if token is not None:
                                headers['X-CSRF-Token'] = token
                            refused = signed_in.put(route, json={'title': '변경', 'body': '거절',
                                                                 'version': 1},
                                                    base_url=origin, headers=headers)
                            self.assertEqual(refused.status_code, 403)
                        stored = signed_in.get(route, base_url=origin).json
                        self.assertEqual((stored['body'], stored['version']), ('가나다', 1))
        finally:
            module.app.wsgi_app = old

    def test_loopback_origin_requires_exact_public_referrer_and_same_origin_context(self):
        origin = 'https://synthetic-cloud-8000.app.github.dev'
        valid = {'Origin': 'http://localhost:8000', 'Referer': origin + '/',
                 'Sec-Fetch-Site': 'same-origin'}
        invalid = [
            {'Referer': None},
            {'Referer': 'https://foreign.example.test/'},
            {'Referer': origin + '.foreign.example.test/'},
            {'Referer': origin + '@foreign.example.test/'},
            {'Referer': origin.replace('https:', 'http:') + '/'},
            {'Referer': origin + ':8443/'},
            {'Referer': 'https://[malformed/'},
            {'Sec-Fetch-Site': None},
            {'Sec-Fetch-Site': 'cross-site'},
            {'Sec-Fetch-Site': 'same-site'},
            {'Sec-Fetch-Site': 'none'},
            {'Origin': 'http://localhost:8001'},
            {'Origin': 'http://localhost:8000.foreign.example.test'},
            {'Origin': 'null'},
            {'Origin': 'https://foreign.example.test', 'X-Forwarded-Proto': 'https',
             'X-Forwarded-Host': 'foreign.example.test'},
        ]
        old = module.app.wsgi_app
        module.app.wsgi_app = SyntheticPublicOrigin(old, origin)
        try:
            for changes in invalid:
                with self.subTest(changes=changes):
                    headers = {**valid, **changes}
                    headers = {key: value for key, value in headers.items() if value is not None}
                    refused = module.app.test_client().post(
                        '/api/login', json={'email': 'synthetic-blocked@example.com',
                                            'password': 'test-password-123'},
                        base_url=origin, headers=headers)
                    self.assertEqual(refused.status_code, 403)
                    self.assertEqual(refused.json['error'], '허용되지 않는 요청입니다.')
        finally:
            module.app.wsgi_app = old

    def test_configuration_rejects_foreign_or_malformed_destinations(self):
        with patch.dict(os.environ, {'CODESPACES': 'true', 'CODESPACE_NAME': 'synthetic-cloud', 'EXPO_PUBLIC_TEST_API_URL': 'https://synthetic-cloud-8000.app.github.dev'}):
            self.assertEqual(configured_origin(), 'https://synthetic-cloud-8000.app.github.dev')
            os.environ['EXPO_PUBLIC_TEST_API_URL'] = 'https://other.example.test'
            with self.assertRaises(ValueError):
                configured_origin()
        for value in ('http://synthetic-cloud-8000.app.github.dev', 'https://synthetic-cloud-8000.app.github.dev/path', 'https://example.test'):
            with self.assertRaises(ValueError):
                SyntheticPublicOrigin(lambda environ, start: None, value)
        with patch.dict(os.environ, {'YEOBAEK_MOBILE_PREVIEW': 'true',
                                      'EXPO_PUBLIC_TEST_API_URL': 'https://synthetic-preview.trycloudflare.com'}):
            self.assertEqual(configured_origin(), 'https://synthetic-preview.trycloudflare.com')
            SyntheticPublicOrigin(lambda environ, start: None, configured_origin())
            os.environ['EXPO_PUBLIC_TEST_API_URL'] = 'https://other.example.test'
            with self.assertRaises(ValueError):
                configured_origin()
