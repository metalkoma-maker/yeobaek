"""The visible brand remains correct with the protected old server assets."""
import json
from pathlib import Path
import tempfile
import unittest

from test_app import module


class SiteBrandTest(unittest.TestCase):
    def test_public_brand_and_install_name(self):
        client = module.app.test_client()
        page = client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('<title>소설여백 · 소설 쓰는 공간</title>'.encode(), page.data)
        self.assertIn(b'href="/__app_manifest__"', page.data)
        self.assertIn('class="brand">소설여백'.encode(), page.data)
        page.close()

        manifest = client.get('/__app_manifest__')
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json['name'], '소설여백')
        self.assertEqual(manifest.json['short_name'], '소설여백')
        self.assertEqual(manifest.json['start_url'], '/')

    def test_protected_old_assets_still_show_new_brand(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'admin.html').write_text('<title>여백 · 관리자</title><a class="brand">여백</a>')
            (root / 'manifest.json').write_text(json.dumps({'name': '여백', 'short_name': '여백',
                                                             'start_url': '/', 'icons': []}))
            old_folder, old_admin = module.app.static_folder, module.app.is_admin
            module.app.static_folder = temporary
            module.app.is_admin = lambda user: True
            try:
                client = module.app.test_client()
                signup = client.post('/api/register', json={'email': 'brand-test@example.com',
                                                            'password': 'test-password-123'})
                self.assertEqual(signup.status_code, 200)
                admin = client.get('/admin')
                self.assertEqual(admin.status_code, 200)
                self.assertIn('<title>소설여백 · 관리자</title>'.encode(), admin.data)
                self.assertIn('class="brand">소설여백</a>'.encode(), admin.data)
                # A cached old asset must not hide the new name after deployment.
                cached = client.get('/admin', headers={'If-Modified-Since': 'Wed, 21 Oct 2099 07:28:00 GMT'})
                self.assertEqual(cached.status_code, 200)
                self.assertIn('class="brand">소설여백</a>'.encode(), cached.data)
                self.assertEqual(client.get('/__app_manifest__').json['short_name'], '소설여백')
            finally:
                module.app.static_folder, module.app.is_admin = old_folder, old_admin


if __name__ == '__main__':
    unittest.main()
