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

    def test_configuration_rejects_foreign_or_malformed_destinations(self):
        with patch.dict(os.environ, {'CODESPACES': 'true', 'CODESPACE_NAME': 'synthetic-cloud', 'EXPO_PUBLIC_TEST_API_URL': 'https://synthetic-cloud-8000.app.github.dev'}):
            self.assertEqual(configured_origin(), 'https://synthetic-cloud-8000.app.github.dev')
            os.environ['EXPO_PUBLIC_TEST_API_URL'] = 'https://other.example.test'
            with self.assertRaises(ValueError):
                configured_origin()
        for value in ('http://synthetic-cloud-8000.app.github.dev', 'https://synthetic-cloud-8000.app.github.dev/path', 'https://example.test'):
            with self.assertRaises(ValueError):
                SyntheticPublicOrigin(lambda environ, start: None, value)
