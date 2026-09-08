"""Verify Shop identity assertions without provisioning users or permissions."""
import fcntl
import hashlib
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.core import signing
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_POST

STATE_AGE = 300
STATE_KEY = 'shop_sso_states'


def configured():
    return (
        len(settings.SHOP_MARKETING_SSO_SECRET) >= 43
        and settings.SHOP_APP_URL == 'https://shop.britishschool.ac.tz'
        and settings.MARKETING_APP_URL == 'https://marketing.britishschool.ac.tz'
    )


def failure(status=400):
    response = HttpResponse(
        'Marketing single sign-on is unavailable or this handoff is no longer valid. '
        'Please open Marketing from Shop again or '
        '<a href="/accounts/login/">sign in to Marketing</a>.', status=status)
    response['Referrer-Policy'] = 'no-referrer'
    return response


def valid_states(request):
    now = time.time()
    states = request.session.get(STATE_KEY, [])
    if not isinstance(states, list):
        return []
    return [item for item in states[-5:] if isinstance(item, dict)
            and isinstance(item.get('state'), str)
            and isinstance(item.get('created'), (int, float))
            and 0 <= now - item['created'] <= STATE_AGE]


@never_cache
@require_GET
def shop_sso_start(request):
    if not configured():
        return failure(503)
    state = secrets.token_urlsafe(32)
    request.session[STATE_KEY] = valid_states(request)[-4:] + [
        {'state': state, 'created': time.time()}]
    response = redirect(settings.SHOP_APP_URL + '/sso/marketing/authorize/?' + urlencode({'state': state}))
    response['Referrer-Policy'] = 'no-referrer'
    return response


def claim_assertion(jti, state):
    # FileBasedCache.add is check-then-set. Serialize claims across Gunicorn
    # processes with one persistent lock in the existing private cache directory.
    # The state claim also prevents concurrent reuse with a different signed jti.
    directory = Path(settings.CACHES['default']['LOCATION'])
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.shop-marketing-sso.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not cache.add('shop-marketing-sso-jti:' + jti, True, timeout=120):
            return False
        digest = hashlib.sha256(state.encode()).hexdigest()
        return cache.add('shop-marketing-sso-state:' + digest, True, timeout=STATE_AGE + 60)


@csrf_exempt
@never_cache
@require_POST
@sensitive_post_parameters('token')
@sensitive_variables('token', 'payload')
def shop_sso_consume(request):
    token = request.POST.get('token', '')
    if not token or len(token) > 4096:
        return failure()
    if not configured():
        return failure(503)
    try:
        payload = signing.loads(token, key=settings.SHOP_MARKETING_SSO_SECRET,
                                salt=settings.SHOP_MARKETING_SSO_SALT,
                                max_age=settings.SHOP_MARKETING_SSO_MAX_AGE,
                                fallback_keys=[])
    except (signing.BadSignature, ValueError, TypeError, UnicodeError):
        return failure()
    if not isinstance(payload, dict) or set(payload) != {'ver', 'iss', 'aud', 'sub', 'state', 'jti'}:
        return failure()
    if (type(payload['ver']) is not int or payload['ver'] != 1
            or payload['iss'] != 'shop.britishschool.ac.tz'
            or payload['aud'] != 'marketing.britishschool.ac.tz'):
        return failure()
    subject, state, jti = payload['sub'], payload['state'], payload['jti']
    if (not isinstance(subject, str) or not 1 <= len(subject) <= 150
            or any(ord(c) < 32 or ord(c) == 127 for c in subject)
            or not isinstance(state, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', state)
            or not isinstance(jti, str) or not re.fullmatch(r'[a-f0-9]{32}', jti)):
        return failure()
    states = valid_states(request)
    if not any(secrets.compare_digest(item['state'], state) for item in states):
        return failure()
    request.session[STATE_KEY] = [item for item in states if not secrets.compare_digest(item['state'], state)]
    try:
        if not claim_assertion(jti, state):
            return failure()
    except OSError:
        return failure(503)
    user = get_user_model().objects.filter(username=subject, is_active=True).first()
    if user is None:
        messages.error(request, 'Your Shop account is authenticated, but no active Marketing account '
                       'with the same username exists. Please contact an administrator or sign in '
                       'with an existing Marketing account.')
        return redirect('api:login')
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    response = redirect('api:dashboard')
    response['Referrer-Policy'] = 'no-referrer'
    return response
