"""Production configuration for marketing.britishschool.ac.tz."""
from .settings import *

DEBUG = False
ALLOWED_HOSTS = ['marketing.britishschool.ac.tz']
CSRF_TRUSTED_ORIGINS = ['https://marketing.britishschool.ac.tz']
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': 'marketing',
    'USER': 'marketing',
    'PASSWORD': os.environ['MARKETING_DB_PASSWORD'],
    'HOST': '127.0.0.1',
    'PORT': '5432',
    'CONN_MAX_AGE': 60,
}}
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
# HTTPS policy is limited to this exact hostname; do not opt other hosts into preload.
SILENCED_SYSTEM_CHECKS = ['security.W005', 'security.W021']
STATIC_ROOT = Path('/var/www/marketing/static')
MEDIA_ROOT = Path('/var/lib/marketing/private-media')
CACHES['default']['LOCATION'] = '/var/lib/marketing/cache'
