"""Fixed public origin for the synthetic Codespaces server ONLY.

Do not install this middleware in the production Flask/Gunicorn service.
Never trust caller-supplied forwarded headers or disable the existing CSRF guard.
"""
import os
import re
from urllib.parse import urlsplit


def configured_origin():
    if os.environ.get('CODESPACES') != 'true':
        return None
    name = os.environ.get('CODESPACE_NAME', '')
    if not re.fullmatch('[a-z0-9-]+', name):
        raise ValueError('A valid Codespace name is required')
    expected = 'https://' + name + '-8000.app.github.dev'
    if os.environ.get('EXPO_PUBLIC_TEST_API_URL') != expected:
        raise ValueError('Test API URL must match this Codespace')
    return expected


class SyntheticPublicOrigin:
    def __init__(self, app, origin):
        url = urlsplit(origin)
        if not re.fullmatch(r'https://[a-z0-9-]+-8000\.app\.github\.dev', origin):
            raise ValueError('Only a fixed Codespaces HTTPS origin is supported')
        self.app, self.host, self.origin = app, url.hostname, origin

    def __call__(self, environ, start_response):
        environ = environ.copy()
        # Codespaces can rewrite a same-origin browser Origin to localhost
        # while retaining its public Referer and browser Fetch Metadata.
        # Restore that one documented transformation only in this fake runner.
        received = environ.get('HTTP_ORIGIN', '')
        if received in ('http://localhost:8000', 'https://localhost:8000'):
            try:
                referer = urlsplit(environ.get('HTTP_REFERER', ''))
                same_page = referer.scheme == 'https' and referer.netloc == self.host
            except ValueError:
                same_page = False
            if same_page and environ.get('HTTP_SEC_FETCH_SITE') == 'same-origin':
                environ['HTTP_ORIGIN'] = self.origin
        environ['yeobaek.test_received_origin'] = received
        environ['wsgi.url_scheme'] = 'https'
        environ['HTTP_HOST'] = self.host
        environ['SERVER_NAME'] = self.host
        environ['SERVER_PORT'] = '443'
        return self.app(environ, start_response)
