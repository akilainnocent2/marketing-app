"""Whole saved-period entitlement. Repeated `marketer` IDs select a subset.

Business participants are designated Marketers/custom add-customer grantees,
period sale owners and policy holders. Administrative status is not designation.
"""
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone
from .models import Sale, CommissionPolicy, CommissionPeriod
from .selectors import require
from .services import calculate_commission

ZERO = Decimal('0.00')

def organization(user):
    return user.has_perm('api.view_all_reports') and user.has_perm('api.view_all_marketing')

def cohort(user, period=None):
    users = get_user_model().objects.all()
    if not organization(user):
        return users.filter(pk=user.pk)
    sales = Sale.objects.all()
    policies = CommissionPolicy.objects.all()
    if period:
        sales = sales.filter(date__range=(period.start, period.end))
        policies = policies.filter(period=period)
    admin_permissions=['add_user','change_user','add_group','change_group']
    custom_groups=Group.objects.filter(permissions__content_type__app_label='api',permissions__codename='add_customer').exclude(name='Administrator').exclude(permissions__content_type__app_label='auth',permissions__codename__in=admin_permissions)
    direct_admins=users.filter(user_permissions__content_type__app_label='auth',user_permissions__codename__in=admin_permissions)
    direct_designation=Q(user_permissions__content_type__app_label='api',user_permissions__codename='add_customer') & ~Q(pk__in=direct_admins.values('pk')) & Q(is_superuser=False)
    designation = Q(groups__name='Marketer') | Q(groups__in=custom_groups) | direct_designation
    return users.filter((Q(is_active=True) & designation) | Q(pk__in=sales.values('marketer_id')) | Q(pk__in=policies.values('marketer_id'))).distinct().order_by('first_name', 'username', 'pk')

def rollup(rows, period):
    configured = [r for r in rows if r['configured']]
    issues = [r for r in rows if not r['configured']]
    sumof = lambda key: sum((r[key] for r in configured), ZERO)
    rates = {}
    for r in configured:
        rates[r['rate']] = rates.get(r['rate'], 0) + 1
    excess, earned = sumof('excess'), sumof('commission')
    return dict(count=len(rows), configured_count=len(configured), unconfigured_count=len(issues),
                sales=sum((r['sales'] for r in rows), ZERO), configured_sales=sumof('sales'),
                unconfigured_sales=sum((r['sales'] for r in issues), ZERO), base=sumof('base'),
                covered=sumof('covered'), excess=excess, commission=earned, complete=bool(period) and not issues,
                rates=[dict(rate=k, count=v) for k,v in sorted(rates.items())],
                rate_label=(format(next(iter(rates)), 'f').rstrip('0').rstrip('.') if next(iter(rates),None) else '0')+'%' if len(rates)==1 else 'Mixed rates' if rates else 'No configured rate',
                effective_rate=earned*100/excess if excess else None, denominator=excess, issues=issues)

def report_context(user, data):
    from .forms import ReportFilterForm
    require(user, 'api.view_reports'); require(user, 'api.view_sale')
    form = ReportFilterForm(data, user=user)
    if not form.is_valid():
        raise ValidationError([f'{key}: {" ".join(values)}' for key,values in form.errors.items()])
    period = form.cleaned_data['period']
    users = list(form.cohort)
    chosen = {u.pk for u in form.cleaned_data['marketer']}
    # Absent filter means all; an explicit empty parameter means an empty scope.
    selection_all=form.cleaned_data['selection']=='all' or ('marketer' not in data and form.cleaned_data['selection']!='selected')
    selected_ids = {u.pk for u in users} if selection_all else chosen
    sales = Sale.objects.filter(marketer_id__in=[u.pk for u in users], status='confirmed')
    if period: sales=sales.filter(date__range=(period.start,period.end))
    amounts=dict(sales.order_by().values('marketer_id').annotate(n=Sum('amount')).values_list('marketer_id','n'))
    policies={p.marketer_id:p for p in CommissionPolicy.objects.filter(period=period, marketer_id__in=[u.pk for u in users])} if period else {}
    rows=[]
    for u in users:
        policy=policies.get(u.pk)
        row=dict(marketer=u, period=period, policy=policy, sales=amounts.get(u.pk,ZERO), configured=bool(policy and policy.active), commission=None, action_url=None)
        row['state']='Configured' if row['configured'] else 'No current commission period' if not period else 'Policy inactive' if policy else 'Needs policy'
        if row['configured']:
            row.update(calculate_commission(row['sales'],policy.base,policy.rate));row['covered']=min(row['sales'],policy.base)
        if period and user.has_perm('api.manage_commissions'):
            if policy and user.has_perm('api.change_commissionpolicy'):
                row['action_url']=reverse('api:edit',args=['commissions',policy.pk])
            elif not policy and not period.closed and user.has_perm('api.add_commissionpolicy'):
                row['action_url']=reverse('api:add',args=['commissions'])+f'?marketer={u.pk}&period={period.pk}'
        rows.append(row)
    selected=[r for r in rows if r['marketer'].pk in selected_ids]
    return dict(form=form, period=period, basis=f'{period.name} · {period.start} – {period.end} · whole-period entitlement' if period else 'All-time confirmed sales · no current commission period',
                selected=rollup(selected,period), global_summary=rollup(rows,period) if organization(user) else None,
                rows=selected, selected_ids=selected_ids, selection_all=selection_all, options=list({u.pk:u for u in users[:30]+([u for u in users if u.pk in selected_ids] if not selection_all else [])}.values()), show_global=organization(user))
