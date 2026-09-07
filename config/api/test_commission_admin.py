import uuid
from datetime import date

from django.apps import apps
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import CommissionPeriod, CommissionPolicy, PolicyRevision, Sale


class CommissionAdministrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('maintenance', password='test')
        self.period = CommissionPeriod.objects.create(name='January', start=date(2025, 1, 1), end=date(2025, 1, 31), closed=True)
        self.policy = CommissionPolicy.objects.create(marketer=self.user, period=self.period, base=100, rate=3)
        self.sale = Sale.objects.create(marketer=self.user, created_by=self.user, updated_by=self.user, date=date(2025, 1, 15), reference='sale', amount=200, status='confirmed', description='Test')
        self.revision = PolicyRevision.objects.create(policy=self.policy, version=1, base=90, rate=2, actor=self.user, reason='Earlier correction')
        self.client.force_login(self.user)

    def test_edit_assigned_period(self):
        response = self.client.post(reverse('api:edit', args=['periods', self.period.pk]), {
            'name': 'Extended', 'start': '2025-01-01', 'end': '2025-02-28', 'closed': 'on', 'token': uuid.uuid4(),
        })
        self.assertEqual(response.status_code, 302)
        self.period.refresh_from_db()
        self.assertEqual(self.period.end, date(2025, 2, 28))

    def test_edit_closed_policy_with_sales(self):
        response = self.client.post(reverse('api:edit', args=['commissions', self.policy.pk]), {
            'base': 150, 'rate': 4, 'active': 'on', 'version': 1, 'token': uuid.uuid4(),
        })
        self.assertEqual(response.status_code, 302)
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.base, 150)
        self.assertEqual(self.policy.version, 2)
        self.assertEqual(self.policy.policyrevision_set.count(), 2)

    def test_delete_policy_preserves_sales_and_revisions(self):
        response = self.client.post(reverse('api:remove-setting', args=['commissions', self.policy.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CommissionPolicy.objects.exists())
        self.revision.refresh_from_db()
        self.assertIsNone(self.revision.policy_id)
        self.assertTrue(Sale.objects.filter(pk=self.sale.pk).exists())

    def test_delete_period_with_policies_and_history(self):
        response = self.client.post(reverse('api:remove-setting', args=['periods', self.period.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CommissionPeriod.objects.exists())
        self.assertFalse(CommissionPolicy.objects.exists())
        self.assertTrue(PolicyRevision.objects.exists())
        self.assertTrue(Sale.objects.exists())

    def test_ordinary_user_cannot_delete_or_edit(self):
        user = get_user_model().objects.create_user('ordinary')
        self.client.force_login(user)
        for kind, obj in [('periods', self.period), ('commissions', self.policy)]:
            self.assertEqual(self.client.post(reverse('api:remove-setting', args=[kind, obj.pk])).status_code, 403)
            self.assertEqual(self.client.post(reverse('api:edit', args=[kind, obj.pk])).status_code, 403)

    def test_admin_registers_all_models_and_updates_policy(self):
        for model in apps.get_app_config('api').get_models():
            self.assertTrue(admin.site.is_registered(model), model.__name__)
        response = self.client.post(reverse('admin:api_commissionpolicy_change', args=[self.policy.pk]), {
            'base': 125, 'rate': 5, 'active': 'on', '_save': 'Save',
        })
        self.assertEqual(response.status_code, 302)
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.base, 125)
        self.assertEqual(self.policy.version, 2)
