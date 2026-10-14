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
        self.app, self.host = app, url.hostname

    def __call__(self, environ, start_response):
        environ = environ.copy()
        environ['wsgi.url_scheme'] = 'https'
        environ['HTTP_HOST'] = self.host
        environ['SERVER_NAME'] = self.host
        environ['SERVER_PORT'] = '443'
        return self.app(environ, start_response)
