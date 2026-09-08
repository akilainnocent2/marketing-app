import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission, Group
from django.core import signing
from django.core.cache import cache
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from .shop_sso import claim_assertion

TEST_SECRET = 'test-only-sso-key-' * 4
START = '/accounts/sso/shop/start/'
CONSUME = '/accounts/sso/shop/consume/'

@override_settings(SHOP_MARKETING_SSO_SECRET=TEST_SECRET,
                   SHOP_APP_URL='https://shop.britishschool.ac.tz',
                   MARKETING_APP_URL='https://marketing.britishschool.ac.tz',
                   SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver'])
class ShopSSOTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('Exact.Case', password='test-only-login-927!')
        cls.user.user_permissions.add(Permission.objects.get(codename='view_customer'))
        cls.group = Group.objects.create(name='SSO existing group')
        cls.user.groups.add(cls.group)
        get_user_model().objects.create_user('inactive', is_active=False)

    def setUp(self):
        cache.clear()
        self.client = Client(enforce_csrf_checks=True)

    def start(self, client=None):
        response = (client or self.client).get(START)
        self.assertEqual(response.status_code, 302)
        url = urlparse(response.url)
        self.assertEqual(url.scheme+'://'+url.netloc+url.path, 'https://shop.britishschool.ac.tz/sso/marketing/authorize/')
        return parse_qs(url.query)['state'][0]

    def payload(self, **changes):
        result = dict(ver=1, iss='shop.britishschool.ac.tz', aud='marketing.britishschool.ac.tz',
                      sub=self.user.username, state=self.start(), jti=uuid.uuid4().hex)
        result.update(changes)
        return result

    def signed(self, payload, key=TEST_SECRET):
        return signing.dumps(payload, key=key, salt='britishschool.shop-marketing.sso.v1', compress=True)

    def consume(self, payload, **kwargs):
        return self.client.post(CONSUME, {'token': self.signed(payload, **kwargs)})

    def test_start_bounded_states_and_pruning(self):
        states=[self.start() for _ in range(7)]
        self.assertEqual([x['state'] for x in self.client.session['shop_sso_states']], states[-5:])
        session=self.client.session
        session['shop_sso_states']=[{'state':states[0],'created':time.time()-301}]
        session.save()
        self.start()
        self.assertEqual(len(self.client.session['shop_sso_states']),1)

    def test_success_permissions_and_back_link(self):
        before=set(self.user.get_all_permissions())
        payload=self.payload()
        response=self.consume(payload)
        self.assertRedirects(response, reverse('api:dashboard'), fetch_redirect_response=False)
        self.assertEqual(self.client.session['_auth_user_id'],str(self.user.pk))
        self.assertEqual(self.client.session['shop_sso_states'],[])
        user=get_user_model().objects.get(pk=self.user.pk)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(set(user.get_all_permissions()),before)
        self.assertEqual(list(user.groups.values_list('pk',flat=True)),[self.group.pk])
        response=self.client.get('/dashboard/',follow=True)
        self.assertContains(response,'href="https://shop.britishschool.ac.tz/"')
        self.assertContains(response,'Back to Shop')
        self.assertEqual(self.client.get('/accounts/login/').url,'/dashboard/')
        self.assertEqual(self.client.get('/reports/').status_code,403)

    def test_signature_and_expiration(self):
        payload=self.payload()
        self.assertEqual(self.consume(payload,key='wrong-key').status_code,400)
        with patch('django.core.signing.time.time',return_value=time.time()-61):token=self.signed(payload)
        self.assertEqual(self.client.post(CONSUME,{'token':token}).status_code,400)
        self.assertNotIn('_auth_user_id',self.client.session)

    def test_payload_validation(self):
        for change in [{'iss':'wrong'},{'aud':'wrong'},{'ver':2},{'ver':True},{'sub':''},{'sub':None},
                       {'state':'bad'},{'jti':'bad'},{'jti':None},{'is_superuser':True},
                       {'permissions':['api.view_reports']},{'groups':['admin']}]:
            with self.subTest(change=change):self.assertEqual(self.consume(self.payload(**change)).status_code,400)
        self.assertEqual(self.consume([]).status_code,400)
        payload=self.payload();del payload['sub']
        self.assertEqual(self.consume(payload).status_code,400)

    def test_missing_large_token_and_methods(self):
        for token in ['', 'a'*4097,'invalid']:
            self.assertEqual(self.client.post(CONSUME,{'token':token}).status_code,400)
        self.assertEqual(self.client.get(CONSUME).status_code,405)
        self.assertEqual(self.client.post(START).status_code,403)  # normal CSRF remains active

    def test_state_mismatch_stale_and_other_browser(self):
        payload=self.payload(state=secrets.token_urlsafe(32))
        self.assertEqual(self.consume(payload).status_code,400)
        payload=self.payload()
        self.assertEqual(Client().post(CONSUME,{'token':self.signed(payload)}).status_code,400)
        session=self.client.session
        session['shop_sso_states']=[{'state':payload['state'],'created':time.time()-301}];session.save()
        self.assertEqual(self.consume(payload).status_code,400)

    def test_state_reuse_and_jti_replay(self):
        payload=self.payload();self.assertEqual(self.consume(payload).status_code,302)
        self.assertEqual(self.consume(payload).status_code,400)
        newer=self.payload(jti=payload['jti'])
        self.assertEqual(self.consume(newer).status_code,400)
        # Simulate stale parallel session data with a separately signed assertion.
        session=self.client.session
        session['shop_sso_states']=[{'state':payload['state'],'created':time.time()}];session.save()
        payload['jti']=uuid.uuid4().hex
        self.assertEqual(self.consume(payload).status_code,400)

    def test_parallel_replay_claim(self):
        jti=uuid.uuid4().hex;state=secrets.token_urlsafe(32)
        with ThreadPoolExecutor(max_workers=6) as executor:
            results=list(executor.map(lambda _:claim_assertion(jti,state),range(6)))
        self.assertEqual(results.count(True),1)

    def test_missing_inactive_and_exact_case_no_provisioning(self):
        before=get_user_model().objects.count()
        for name in ['absent','inactive','exact.case']:
            response=self.consume(self.payload(sub=name))
            self.assertRedirects(response,'/accounts/login/',fetch_redirect_response=False)
            self.assertNotIn('_auth_user_id',self.client.session)
            self.assertContains(self.client.get('/accounts/login/'),'no active Marketing account')
        self.assertEqual(get_user_model().objects.count(),before)

    def test_direct_login_and_csrf(self):
        self.assertTrue(self.client.get('/').url.startswith('/accounts/login/'))
        self.assertEqual(self.client.post('/accounts/login/',{'username':self.user.username,'password':'test-only-login-927!'}).status_code,403)
        self.assertEqual(self.client.get('/accounts/login/').status_code,200)
        csrf=self.client.cookies['csrftoken'].value
        response=self.client.post('/accounts/login/',{'username':self.user.username,'password':'test-only-login-927!','csrfmiddlewaretoken':csrf})
        self.assertEqual(response.url,'/dashboard/')
        self.assertEqual(self.client.get('/accounts/login/').url,'/dashboard/')

    def test_fail_closed(self):
        payload=self.payload()
        for key in ['', 'short']:
            with override_settings(SHOP_MARKETING_SSO_SECRET=key):
                self.assertEqual(self.client.get(START).status_code,503)
                self.assertEqual(self.consume(payload).status_code,503)
                self.assertEqual(self.client.get('/accounts/login/').status_code,200)
        with patch('config.api.shop_sso.claim_assertion',side_effect=OSError):
            self.assertEqual(self.consume(payload).status_code,503)
