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
    def test_admin_policy_revision_records_default_reason_after_sales(self):
        self.sale(3500000);self.client.force_login(self.admin)
        url=reverse('api:edit',args=['commissions',self.policy.pk])
        data={'marketer':self.a.pk,'period':self.period.pk,'base':'3000000','rate':'4','active':'on','version':self.policy.version,'token':str(uuid.uuid4())}
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertEqual(PolicyRevision.objects.get().reason,'Administrative policy correction')
        self.assertEqual(PolicyRevision.objects.get().rate,3)
        self.assertEqual(commission(self.a,self.period)['commission'],Decimal('20000'))
    def test_overlapping_period_allowed(self):
        self.client.force_login(self.admin)
        r=self.client.post(reverse('api:add',args=['periods']),{'name':'Overlap','start':'2025-01-15','end':'2025-02-01'})
        self.assertEqual(r.status_code,302)
        self.assertTrue(CommissionPeriod.objects.filter(name='Overlap').exists())
    def test_period_name_is_optional(self):
        self.client.force_login(self.admin)
        response=self.client.post(reverse('api:add',args=['periods']),{'start':'2025-01-15','end':'2025-01-15'},HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code,204)
        self.assertTrue(CommissionPeriod.objects.filter(name='15 Jan 2025 – 15 Jan 2025').exists())
    def test_period_invalid_dates_preserve_entries(self):
        self.client.force_login(self.admin)
        for end in ['2025-01-01', 'invalid', '']:
            response=self.client.post(reverse('api:add',args=['periods']),{'name':'Keep my entry','start':'2025-01-15','end':end},HTTP_HX_REQUEST='true')
            self.assertEqual(response.status_code,422)
            self.assertContains(response,'Keep my entry',status_code=422)
            self.assertIn('end',response.context['form'].errors)
        self.assertFalse(CommissionPeriod.objects.filter(name='Keep my entry').exists())
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

class ReportingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin=get_user_model().objects.create_superuser('report_admin',password='Test-only!123')
        cls.period=CommissionPeriod.objects.create(name='Regression period',start=date(2025,1,1),end=date(2025,1,31))
        group=Group.objects.create(name='Marketer')
        group.permissions.add(*Permission.objects.filter(content_type__app_label='api',codename__in=['view_reports','view_sale','export_reports']))
        cls.users=[]
        for name,sales,base,rate in [('A',7000000,3000000,3),('B',2000000,3000000,5),('C',8000000,2000000,5)]:
            u=get_user_model().objects.create_user(name);u.groups.add(group);cls.users.append(u)
            Sale.objects.create(reference=name,amount=sales,status='confirmed',date=date(2025,1,15),marketer=u,created_by=u,updated_by=u)
            CommissionPolicy.objects.create(marketer=u,period=cls.period,base=base,rate=rate)
    def get_report(self,ids=None,path='/reports/',**extra):
        self.client.force_login(self.admin)
        params={'period':self.period.pk,**extra}
        if ids is not None:params['marketer']=ids
        r=self.client.get(path,params,HTTP_HX_REQUEST='true')
        self.assertEqual(r.status_code,200,r.content[:500])
        return r
    def test_exact_and_selected_global_on_every_screen(self):
        for path in ['/reports/','/marketing/sales/','/reports/sales/']:
            r=self.get_report([self.users[0].pk],path)
            f=r.context['finance'];s=f['selected'];g=f['global_summary']
            self.assertEqual((s['sales'],s['excess'],s['commission'],s['rate_label']),(7000000,4000000,120000,'3%'))
            self.assertEqual((g['sales'],g['excess'],g['commission'],g['covered'],g['base']),(17000000,10000000,420000,7000000,8000000))
            self.assertEqual(g['effective_rate'],Decimal('4.2'))
            self.assertContains(r,'TZS 120,000.00');self.assertContains(r,'4.20%');self.assertNotContains(r,'<html')
        s=self.get_report([u.pk for u in self.users[:2]]).context['finance']['selected']
        self.assertEqual((s['sales'],s['excess'],s['commission'],s['rate_label'],s['effective_rate']),(9000000,4000000,120000,'Mixed rates',3))
    def test_partial_inactive_and_zero(self):
        d=get_user_model().objects.create_user('D',is_active=False)
        Sale.objects.create(reference='D',amount=4000000,status='confirmed',date=date(2025,1,10),marketer=d,created_by=d,updated_by=d)
        r=self.get_report();g=r.context['finance']['global_summary']
        self.assertEqual((g['sales'],g['commission'],g['excess'],g['unconfigured_count']),(21000000,420000,10000000,1))
        self.assertContains(r,f'marketer={d.pk}&amp;period={self.period.pk}')
        self.assertContains(r,'complete total is pending')
        policy=CommissionPolicy.objects.create(marketer=d,period=self.period,base=1000000,rate=2)
        completed=self.get_report().context['finance']['global_summary']
        self.assertEqual(completed['commission'],480000);self.assertTrue(completed['complete'])
        policy.active=False;policy.save();self.assertContains(self.get_report(),'Policy inactive')
        policy.active=True;policy.base=0;policy.rate=0;policy.save()
        r=self.get_report([d.pk]);self.assertContains(r,'0%');self.assertTrue(r.context['finance']['selected']['complete'])
    def test_selection_validation_and_read_only_reporter(self):
        r=self.get_report([self.users[0].pk]*2);self.assertEqual(r.context['finance']['selected']['count'],1)
        self.assertEqual(self.get_report(['']).context['finance']['selected']['count'],0)
        for bad in ['xyz','999999999']:
            self.assertEqual(self.client.get('/reports/',{'period':self.period.pk,'marketer':bad}).status_code,400)
        self.assertEqual(self.client.get('/reports/',{'period':'xyz'}).status_code,400)
        reporter=get_user_model().objects.create_user('readonly')
        reporter.user_permissions.add(*Permission.objects.filter(content_type__app_label='api',codename__in=['view_reports','view_sale','view_all_reports','view_all_marketing']))
        self.client.force_login(reporter)
        r=self.client.get('/reports/',{'period':self.period.pk,'marketer':self.users[0].pk})
        self.assertEqual(r.context['finance']['global_summary']['count'],3)
        self.assertEqual(self.client.get('/lookups/report-marketer/',{'period':self.period.pk}).status_code,200)
        self.assertEqual(self.client.get('/lookups/marketer/').status_code,403)
        self.client.force_login(self.users[0])
        for path in ['/reports/','/reports/sales/','/reports/sales/pdf/','/lookups/report-marketer/']:
            r=self.client.get(path,{'period':self.period.pk,'marketer':self.users[1].pk})
            self.assertIn(r.status_code,[400,403,404])
        r=self.client.get('/reports/',{'period':self.period.pk});self.assertIsNone(r.context['finance']['global_summary']);self.assertNotContains(r,'All authorized marketers')
    def test_detail_filters_status_and_period(self):
        for status in ['draft','void']:
            Sale.objects.create(reference=status,amount=9000000,status=status,date=date(2025,1,15),marketer=self.users[0],created_by=self.users[0],updated_by=self.users[0])
        r=self.get_report([self.users[0].pk],'/marketing/sales/',status='draft',**{'from':'2025-01-14','to':'2025-01-16'})
        self.assertEqual(r.context['finance']['selected']['commission'],120000)
        self.assertEqual(r.context['amount_total'],9000000);self.assertEqual(r.context['eligible_detail_total'],0)
        sale=Sale.objects.get(reference='draft');sale.status='confirmed';sale.save()
        self.assertEqual(self.get_report([self.users[0].pk]).context['finance']['selected']['commission'],390000)
        sale.date=date(2024,12,1);sale.save()
        self.assertEqual(self.get_report([self.users[0].pk]).context['finance']['selected']['commission'],120000)
    def test_pagination_and_missing_period(self):
        group=Group.objects.get(name='Marketer')
        for i in range(16):get_user_model().objects.create_user(f'Z{i}').groups.add(group)
        r=self.get_report(page=2);self.assertEqual(len(r.context['cards']),1)
        self.assertEqual(r.context['finance']['selected']['count'],19)
        self.client.force_login(self.admin)
        r=self.client.get('/reports/');self.assertIsNone(r.context['finance']['period']);self.assertContains(r,'All-time confirmed sales')
    def test_policy_prefill_stale_and_retry(self):
        self.client.force_login(self.admin);policy=CommissionPolicy.objects.get(marketer=self.users[0])
        url=reverse('api:edit',args=['commissions',policy.pk])
        data={'base':3000000,'rate':4,'active':'on','reason':'Correction','version':1,'token':str(uuid.uuid4())}
        r=self.client.post(url,data,HTTP_HX_REQUEST='true');self.assertEqual(r.status_code,204,r.content)
        self.assertEqual(self.client.post(url,data,HTTP_HX_REQUEST='true').status_code,204)
        self.assertEqual(PolicyRevision.objects.count(),1)
        data['token']=str(uuid.uuid4());r=self.client.post(url,data);self.assertEqual(r.status_code,422);self.assertContains(r,'another tab',status_code=422)
    def test_pdf_zero_detail_rows_still_has_finance(self):
        from pypdf import PdfReader
        from io import BytesIO
        self.client.force_login(self.admin)
        r=self.client.get(reverse('api:export',args=['sales']),{'period':self.period.pk,'marketer':[self.users[0].pk,self.users[1].pk],'q':'not-matching'})
        self.assertEqual(r.status_code,200)
        text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages)
        for value in ['9,000,000.00','4,000,000.00','120,000.00','17,000,000.00','420,000.00','4.20%','Mixed rates']:self.assertIn(value,text)
    def test_period_setup_event_and_idempotency(self):
        import json
        self.client.force_login(self.admin)
        data={'name':'New period','start':'2026-10-01','end':'2026-10-31','token':str(uuid.uuid4())}
        url=reverse('api:add',args=['periods'])
        r=self.client.post(url,data,HTTP_HX_REQUEST='true');self.assertEqual(r.status_code,204)
        event=json.loads(r['HX-Trigger'])['recordSaved'];self.assertIsNotNone(event['period'])
        retry=self.client.post(url,data,HTTP_HX_REQUEST='true');self.assertEqual(retry.status_code,204)
        self.assertEqual(CommissionPeriod.objects.filter(name='New period').count(),1)
        self.assertEqual(json.loads(retry['HX-Trigger'])['recordSaved']['period'],event['period'])
    def test_prefill_preview_and_inactive_edit_route(self):
        self.client.force_login(self.admin)
        policy=CommissionPolicy.objects.get(marketer=self.users[0]);policy.active=False;policy.save()
        r=self.client.get(reverse('api:add',args=['commissions']),{'marketer':self.users[0].pk,'period':self.period.pk},HTTP_HX_REQUEST='true')
        self.assertEqual(r.context['object'].pk,policy.pk)
        self.assertEqual(r.context['post_url'],reverse('api:edit',args=['commissions',policy.pk]))
        r=self.client.get(reverse('api:policy-preview'),{'marketer':self.users[0].pk,'period':self.period.pk,'sales':999,'base':3000000,'rate':3})
        self.assertEqual(r.json()['sales'],'7000000');self.assertEqual(r.json()['commission'],'120000.00')
    def test_filters_fragments_and_history(self):
        r=self.get_report([u.pk for u in self.users[:2]],'/marketing/sales/',columns=['reference','amount'],sort='amount')
        self.assertContains(r,'name="marketer" value="'+str(self.users[1].pk)+'"')
        self.assertIn('HX-Request',r['Vary'])
        r=self.client.get('/reports/',{'period':self.period.pk},HTTP_HX_REQUEST='true',HTTP_HX_HISTORY_RESTORE_REQUEST='true')
        self.assertContains(r,'<!doctype html>')
        for params in [{'from':'bad'},{'from':'2025-02-01','to':'2025-01-01'},{'sort':'password'},{'sort':'--amount'},{'columns':['password']},{'min':'NaN'}]:
            self.assertEqual(self.client.get('/reports/',{'period':self.period.pk,**params}).status_code,400)
    def test_bulk_stale_preview_atomic_and_popup(self):
        self.client.force_login(self.admin)
        data={'marketers':[u.pk for u in self.users[:2]],'period':self.period.pk,'base':1000000,'rate':2,'reason':'Approved change','token':str(uuid.uuid4())}
        url=reverse('api:bulk');r=self.client.post(url,data,HTTP_HX_REQUEST='true')
        self.assertNotContains(r,'<html');self.assertContains(r,'Proposed excess / commission')
        token=r.context['preview_token']
        policy=CommissionPolicy.objects.get(marketer=self.users[0]);policy.version+=1;policy.save()
        r=self.client.post(url,{**data,'commit':1,'preview_token':token},HTTP_HX_REQUEST='true')
        self.assertContains(r,'changed');self.assertEqual(PolicyRevision.objects.count(),0)
        self.assertEqual(CommissionPolicy.objects.get(marketer=self.users[1]).base,3000000)
    def test_query_budget_not_per_marketer(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        from .reporting import report_context
        from django.http import QueryDict
        self.admin.get_all_permissions()
        q=QueryDict(f'period={self.period.pk}')
        with CaptureQueriesContext(connection) as captured:report_context(self.admin,q)
        count=len(captured)
        for i in range(24):
            u=get_user_model().objects.create_user(f'configured-{i}')
            CommissionPolicy.objects.create(marketer=u,period=self.period,base=0,rate=0)
        with CaptureQueriesContext(connection) as captured:report_context(self.admin,q)
        self.assertLessEqual(len(captured),count+1)
    def test_expired_ajax_preserves_page(self):
        r=self.client.post(reverse('api:add',args=['commissions']),HTTP_HX_REQUEST='true')
        self.assertEqual(r.status_code,401);self.assertNotIn('HX-Redirect',r)
    def test_non_sales_report_reader_retains_dashboard(self):
        user=get_user_model().objects.create_user('customer_reader')
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label='api',codename__in=['view_reports','view_customer']))
        self.client.force_login(user)
        r=self.client.get('/dashboard/');self.assertContains(r,'Commission period is not configured.');self.assertNotContains(r,'17,000,000')
    def test_generic_administrator_group_is_not_business_designation(self):
        group=Group.objects.create(name='Administrator')
        group.permissions.add(*Permission.objects.filter(content_type__app_label__in=['api','auth']))
        admin=get_user_model().objects.create_user('generic_admin');admin.groups.add(group)
        custom=Group.objects.create(name='Field consultants')
        custom.permissions.add(Permission.objects.get(content_type__app_label='api',codename='add_customer'))
        marketer=get_user_model().objects.create_user('custom_marketer');marketer.groups.add(custom)
        r=self.get_report();ids={c['marketer'].pk for c in r.context['finance']['rows']}
        self.assertNotIn(admin.pk,ids);self.assertIn(marketer.pk,ids)
    def test_explicit_all_mode_does_not_truncate_to_chooser_page(self):
        for i in range(40):
            user=get_user_model().objects.create_user(f'Extra-{i}')
            CommissionPolicy.objects.create(marketer=user,period=self.period,base=0,rate=0)
        r=self.get_report([''],'/marketing/sales/',selection='all')
        self.assertEqual(r.context['finance']['selected']['count'],43)
        self.assertEqual(len(r.context['finance']['options']),30)
        self.assertEqual(r.context['count'],3)
        r=self.client.get('/reports/',{'period':self.period.pk,'selection':'all','marketer':'forged'})
        self.assertEqual(r.status_code,400)
