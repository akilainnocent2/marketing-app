"""Exercise real CSRF enforcement behind the Codespaces HTTPS proxy."""
import importlib
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings


class CodespacesCsrfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        get_user_model().objects.create_user('codespace-check', password='Testing-pass-827!')

    def test_forwarded_login_and_form_with_csrf(self):
        with patch.dict(os.environ, {
            'CODESPACE_NAME': 'test-workspace',
            'GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN': 'app.github.dev',
            'CODESPACE_APP_PORTS': '8000, 9000',
            'ALLOWED_HOSTS': 'localhost, 127.0.0.1',
            'CSRF_TRUSTED_ORIGINS': ' https://custom.example , ',
        }):
            from config import settings as project_settings
            configured = importlib.reload(project_settings)
            overrides = {name: getattr(configured, name) for name in (
                'ALLOWED_HOSTS', 'CSRF_TRUSTED_ORIGINS', 'SECURE_PROXY_SSL_HEADER',
            )}
        importlib.reload(project_settings)
        self.assertIn('https://custom.example', overrides['CSRF_TRUSTED_ORIGINS'])
        self.assertNotIn('https://*.app.github.dev', overrides['CSRF_TRUSTED_ORIGINS'])
        with override_settings(**overrides, SECURE_SSL_REDIRECT=True):
            for port in ('8000', '9000'):
                host = f'test-workspace-{port}.app.github.dev'
                client = Client(enforce_csrf_checks=True, HTTP_HOST=host,
                                HTTP_X_FORWARDED_PROTO='https')
                response = client.get('/accounts/login/')
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.wsgi_request.is_secure())
                response = client.post('/accounts/login/', {
                    'username': 'codespace-check', 'password': 'Testing-pass-827!',
                    'csrfmiddlewaretoken': client.cookies['csrftoken'].value,
                }, HTTP_ORIGIN=f'https://{host}')
                self.assertEqual(response.status_code, 302)
                self.assertIn('_auth_user_id', client.session)
                # Login rotates the token. AJAX must use the current cookie.
                response = client.post('/accounts/profile/', {
                    'first_name': 'Codespace', 'last_name': 'User', 'email': 'test@example.com',
                }, HTTP_ORIGIN=f'https://{host}',
                    HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(get_user_model().objects.get(username='codespace-check').first_name, 'Codespace')
                self.assertEqual(client.post('/accounts/profile/', {},
                    HTTP_ORIGIN=f'https://{host}').status_code, 403)
                self.assertEqual(client.post('/accounts/profile/', {},
                    HTTP_ORIGIN='https://other-workspace-8000.app.github.dev',
                    HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value).status_code, 403)
