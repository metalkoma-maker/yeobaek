"""Codespaces preview forwarding keeps the real app's Origin/CSRF checks."""
import unittest
from test_app import module
from tools.run_web_preview import PreviewOrigin


class WebPreviewTest(unittest.TestCase):
    def test_same_page_localhost_origin_is_restored_without_bypassing_csrf(self):
        origin = 'https://synthetic-preview-8001.app.github.dev'
        original = module.app.wsgi_app
        module.app.wsgi_app = PreviewOrigin(original, origin, 8001)
        try:
            client = module.app.test_client()
            credentials = {'email': 'preview-forwarding@example.com', 'password': 'test-password-123'}
            registration = {**credentials, 'age_confirmed': True}
            headers = {'Origin': 'http://localhost:8001', 'Referer': origin + '/',
                       'Sec-Fetch-Site': 'same-origin'}
            registered = client.post('/api/register', base_url=origin, headers=headers, json=registration)
            self.assertEqual(registered.status_code, 200)
            for changes in ({'Referer': 'https://foreign.example.test/'},
                            {'Sec-Fetch-Site': 'cross-site'},
                            {'Origin': 'https://foreign.example.test'},
                            {'Origin': 'http://localhost:8002'}):
                self.assertEqual(client.post('/api/login', base_url=origin,
                                 headers={**headers, **changes}, json=credentials).status_code, 403)
            order = client.get('/api/manuscript-order', base_url=origin).json
            self.assertEqual(client.put('/api/manuscript-order', base_url=origin,
                             headers=headers, json=order).status_code, 403)
            self.assertEqual(client.put('/api/manuscript-order', base_url=origin,
                             headers={**headers, 'X-CSRF-Token': registered.json['csrf']}, json=order).status_code, 200)
        finally:
            module.app.wsgi_app = original
