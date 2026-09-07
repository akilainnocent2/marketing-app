import uuid
from datetime import date
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group,Permission
from django.core.management import call_command
from django.urls import reverse
from .models import *
from .services import commission

class BusinessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('initialize',verbosity=0)
        cls.a=get_user_model().objects.create_user('alice',password='Str0ngPass!478')
        cls.b=get_user_model().objects.create_user('bob',password='Str0ngPass!478')
        group=Group.objects.get(name='Marketer')
        cls.a.groups.add(group);cls.b.groups.add(group)
        cls.admin=get_user_model().objects.create_superuser('admin','admin@example.test','Str0ngPass!478')
        cls.period=CommissionPeriod.objects.create(name='Test January',start=date(2025,1,1),end=date(2025,1,31))
        cls.policy=CommissionPolicy.objects.create(marketer=cls.a,period=cls.period,base=3000000,rate=3)
    def owned(self,user=None):
        user=user or self.a
        return dict(marketer=user,created_by=user,updated_by=user)
    def customer(self,user=None):
        return Customer.objects.create(name='Customer',phone='+255712345678',comment='Interested',**self.owned(user))
    def sale(self,amount,status='confirmed',user=None,**extra):
        return Sale.objects.create(reference=str(uuid.uuid4()),amount=amount,status=status,date=date(2025,1,15),description='Sale',**self.owned(user),**extra)
    def test_commission_examples(self):
        for amount,expected in [(2000000,0),(3000000,0),(3500000,15000),(6000000,90000)]:
            Sale.objects.all().delete();self.sale(amount)
            self.assertEqual(commission(self.a,self.period)['commission'],Decimal(expected))
    def test_accumulation_void_and_other_user(self):
        self.sale(2000000);self.sale(1500000);self.sale(9000000,'void');self.sale(9000000,'draft');self.sale(9000000,user=self.b)
        self.assertEqual(commission(self.a,self.period)['commission'],Decimal('15000.00'))
        self.assertFalse(commission(self.b,self.period)['configured'])
    def test_zero_base_rounding(self):
        self.policy.base=0;self.policy.rate=3;self.policy.save();self.sale('1.50')
        self.assertEqual(commission(self.a,self.period)['commission'],Decimal('.05'))
    def test_scope_details_edit_export_and_forged_filter(self):
        customer=self.customer(self.b);self.client.force_login(self.a)
        for name in ['detail','edit']:
            self.assertEqual(self.client.get(reverse('api:'+name,args=['customers',customer.pk])).status_code,404)
        self.assertEqual(self.client.get(reverse('api:list',args=['customers']),{'marketer':self.b.pk}).status_code,403)
        response=self.client.get(reverse('api:export',args=['customers']))
        self.assertEqual(response.status_code,200);self.assertTrue(response.content.startswith(b'%PDF'))
    def customer_data(self,**extra):
        return dict(name='New customer',phone='0712345678',comment='Interested',date='2025-01-12',version=1,token=str(uuid.uuid4()),**extra)
    def test_create_phone_normalization_and_ownership(self):
        self.client.force_login(self.a)
        url=reverse('api:add',args=['customers'])
        response=self.client.post(url,self.customer_data(marketer=self.b.pk))
        self.assertEqual(response.status_code,422);self.assertEqual(Customer.objects.count(),0)
        response=self.client.post(url,self.customer_data())
        self.assertEqual(response.status_code,302)
        c=Customer.objects.get();self.assertEqual(c.marketer,self.a);self.assertEqual(c.phone,'+255712345678')
    def test_retry_creates_once(self):
        self.client.force_login(self.a);data=self.customer_data();url=reverse('api:add',args=['customers'])
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertEqual(Customer.objects.count(),1)
    def test_draft_conflict_and_finalization(self):
        self.client.force_login(self.a);url=reverse('api:draft-save',args=['customers'])
        r=self.client.post(url,{'name':'Unfinished'});self.assertEqual(r.status_code,200);d=r.json()
        self.assertEqual(Customer.objects.count(),0)
        self.assertEqual(self.client.post(url,{'draft_id':d['id'],'draft_version':0}).status_code,409)
        data=self.customer_data(draft_id=d['id'],draft_version=d['version'])
        self.assertEqual(self.client.post(reverse('api:add',args=['customers']),data).status_code,302)
        self.assertEqual(self.client.post(url,{'draft_id':d['id'],'draft_version':d['version']}).status_code,409)
        self.client.force_login(self.b)
        self.assertEqual(self.client.post(url,{'draft_id':d['id'],'draft_version':d['version']}).status_code,404)
    def test_cannot_confirm_and_customer_owner_validation(self):
        sale=self.sale(10,'draft');self.client.force_login(self.a)
        self.assertEqual(self.client.post(reverse('api:transition',args=['sales',sale.pk,'confirm'])).status_code,403)
        other=self.customer(self.b)
        data=dict(reference='BAD',amount='12',date='2025-01-10',description='Sale',customer=other.pk,token=str(uuid.uuid4()),version=1)
        self.assertEqual(self.client.post(reverse('api:add',args=['sales']),data).status_code,422)
    def test_staff_has_no_business_power(self):
        user=get_user_model().objects.create_user('staff',is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('api:list',args=['customers'])).status_code,403)
        self.assertEqual(self.client.get(reverse('api:dashboard')).status_code,403)
    def test_custom_location_parent_and_scope(self):
        self.client.force_login(self.a);url=reverse('api:custom-option',args=['location'])
        r=self.client.post(url,{'name':'  New Region ','level':'region'});self.assertEqual(r.status_code,200)
        parent=r.json()['id'];r2=self.client.post(url,{'name':'new region','level':'region'});self.assertEqual(r2.json()['id'],parent)
        self.assertEqual(self.client.post(url,{'name':'Ward','level':'ward','parent_id':parent}).status_code,422)
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(reverse('api:location-options'),{'level':'district','parent_id':parent}).status_code,404)
    def test_user_cannot_escalate_group(self):
        self.a.user_permissions.add(Permission.objects.get(content_type__app_label='auth',codename='change_group'))
        self.client.force_login(self.a)
        group=Group.objects.get(name='Administrator')
        self.assertEqual(self.client.post(reverse('api:edit',args=['groups',group.pk]),{'name':'Administrator','permissions':[]}).status_code,422)
    def test_all_main_pages_render_real_documents(self):
        self.client.force_login(self.admin)
        from .registry import REGISTRY
        for kind in REGISTRY:
            r=self.client.get(reverse('api:list',args=[kind]));self.assertEqual(r.status_code,200,kind);self.assertContains(r,'<!doctype html>')
        self.assertEqual(self.client.get(reverse('api:dashboard')).status_code,200)
    def test_signup_cannot_become_staff(self):
        response=self.client.post(reverse('api:signup'),{'username':'newuser','password1':'MyStr0ngSecret!876','password2':'MyStr0ngSecret!876','is_staff':'on','is_superuser':'on'})
        self.assertEqual(response.status_code,302)
        user=get_user_model().objects.get(username='newuser');self.assertFalse(user.is_staff);self.assertFalse(user.is_superuser);self.assertFalse(user.has_perm('api.confirm_sale'));self.assertTrue(user.has_perm('api.add_customer'))
    def test_csrf_required(self):
        c=Client(enforce_csrf_checks=True);c.force_login(self.a)
        self.assertEqual(c.post(reverse('api:add',args=['customers']),self.customer_data()).status_code,403)
    def test_closed_period_blocks_correction(self):
        sale=self.sale(10,'draft');self.period.closed=True;self.period.save();self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('api:transition',args=['sales',sale.pk,'confirm'])).status_code,422)
        sale.refresh_from_db();self.assertEqual(sale.status,'draft')
    def test_bulk_preview_commit_and_retry(self):
        import re
        self.client.force_login(self.admin)
        url=reverse('api:bulk')
        data={'marketers':[self.a.pk,self.b.pk],'period':self.period.pk,'base':'2500000.00','rate':'4.00','token':str(uuid.uuid4())}
        r=self.client.post(url,data);self.assertEqual(r.status_code,200)
        token=r.context['preview_token'];self.assertTrue(token)
        self.assertFalse(CommissionPolicy.objects.filter(marketer=self.b,period=self.period).exists())
        data.update(commit='1',preview_token=token)
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertEqual(CommissionPolicy.objects.filter(period=self.period).count(),2)
        self.assertEqual(CommissionPolicy.objects.get(marketer=self.a,period=self.period).base,Decimal('2500000'))
    def test_bulk_rejects_tampering(self):
        self.client.force_login(self.admin);url=reverse('api:bulk')
        data={'marketers':[self.a.pk],'period':self.period.pk,'base':'20','rate':'4','token':str(uuid.uuid4())}
        r=self.client.post(url,data);data.update(commit='1',preview_token=r.context['preview_token'],rate='99')
        r=self.client.post(url,data);self.assertContains(r,'changed');self.policy.refresh_from_db();self.assertEqual(self.policy.rate,3)
    def test_policy_revision_requires_reason_after_sales(self):
        self.sale(3500000);self.client.force_login(self.admin)
        url=reverse('api:edit',args=['commissions',self.policy.pk])
        data={'marketer':self.a.pk,'period':self.period.pk,'base':'3000000','rate':'4','active':'on'}
        self.assertEqual(self.client.post(url,data).status_code,422)
        data['reason']='Authorized rate correction';self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertEqual(PolicyRevision.objects.get().rate,3)
        self.assertEqual(commission(self.a,self.period)['commission'],Decimal('20000'))
    def test_overlapping_period_rejected(self):
        self.client.force_login(self.admin)
        r=self.client.post(reverse('api:add',args=['periods']),{'name':'Overlap','start':'2025-01-15','end':'2025-02-01'})
        self.assertEqual(r.status_code,422)
    def test_permission_revocation_and_inactive_account(self):
        self.client.force_login(self.a);url=reverse('api:list',args=['customers'])
        self.assertEqual(self.client.get(url).status_code,200)
        self.a.groups.clear();self.assertEqual(self.client.get(url).status_code,403)
        self.a.is_active=False;self.a.save();self.assertEqual(self.client.get(url).status_code,302)
    def test_receipt_scope(self):
        kind=ExpenditureType.objects.first()
        expense=Expenditure.objects.create(title='Private receipt',amount=10,expenditure_type=kind,receipt='receipts/private.pdf',**self.owned(self.b))
        self.client.force_login(self.a)
        self.assertEqual(self.client.get(reverse('api:receipt',args=[expense.pk])).status_code,404)
    def test_report_all_requires_both_scopes(self):
        self.customer(self.b)
        self.a.user_permissions.add(Permission.objects.get(content_type__app_label='api',codename='view_all_marketing'))
        self.client.force_login(self.a)
        response=self.client.get(reverse('api:reports'));self.assertEqual(response.context['customer_count'],0)
        response=self.client.get(reverse('api:report-detail',args=['customers']));self.assertEqual(response.context['count'],0)
    def test_stale_record_version_does_not_overwrite(self):
        customer=self.customer();self.client.force_login(self.a)
        customer.version=2;customer.save()
        response=self.client.post(reverse('api:edit',args=['customers',customer.pk]),self.customer_data())
        self.assertEqual(response.status_code,422);customer.refresh_from_db();self.assertEqual(customer.name,'Customer')
    def test_native_admin_requires_superuser(self):
        self.a.is_staff=True;self.a.save();self.a.groups.add(Group.objects.get(name='Administrator'))
        self.client.force_login(self.a)
        self.assertEqual(self.client.get('/admin/').status_code,302)
    def test_logout_is_post_only(self):
        self.client.force_login(self.a)
        self.assertEqual(self.client.get(reverse('api:logout')).status_code,405)
        self.assertEqual(self.client.post(reverse('api:logout')).status_code,302)
