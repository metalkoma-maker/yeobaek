import app as yeobaek
from werkzeug.middleware.proxy_fix import ProxyFix

yeobaek.SECURE = True
app = yeobaek.app
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)
