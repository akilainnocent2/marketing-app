"""One validated dashboard scope, shared by summaries and paginated details."""
from dataclasses import dataclass
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from .models import Customer, Sale, Expenditure, CommissionPolicy, CommissionPeriod
from .reporting import cohort, organization
from .selectors import scoped, locations, require, total, location_descendants
from .services import get_default_commission_period, calculate_commission


@dataclass
class DashboardScope:
    user: object
    period: object
    marketer: object
    location: object
    location_ids: object
    options: object

    @property
    def query(self):
        params = {'marketer': self.marketer.pk} if self.marketer else {}
        if self.location:
            params['location'] = self.location.pk
        return urlencode(params)


def get_dashboard_scope(user, data):
    require(user, 'api.view_reports')
    period = get_default_commission_period()
    permitted = cohort(user, period)
    chosen = None
    for key in ('marketer', 'location'):
        if len(data.getlist(key)) > 1:
            raise ValidationError('Select one ' + key + '.')
    if data.get('marketer'):
        try:
            chosen = permitted.filter(pk=int(data['marketer'])).first()
        except (ValueError, OverflowError):
            pass
        if chosen is None:
            raise ValidationError('Select a permitted marketer.')
    else:
        chosen = permitted.filter(pk=user.pk).first() or permitted.filter(is_active=True).first()
    location = None
    ids = None
    if data.get('location'):
        try:
            location = locations(user).filter(pk=int(data['location'])).first()
        except (ValueError, OverflowError):
            pass
        if location is None:
            raise ValidationError('Select a permitted location.')
        ids = location_descendants(user, location)
    options = list(permitted[:30]) if organization(user) else []
    if chosen and chosen not in options and organization(user):
        options.append(chosen)
    return DashboardScope(user, period, chosen, location, ids, options)


def _records(scope, model, status):
    require(scope.user, 'api.view_' + model._meta.model_name)
    qs = scoped(model, scope.user).filter(marketer=scope.marketer, status=status)
    if not scope.period or not scope.marketer:
        return qs.none()
    return qs.filter(date__range=(scope.period.start, scope.period.end))


def get_dashboard_sales(scope):
    # Official entitlement always uses complete confirmed period sales.
    return _records(scope, Sale, 'confirmed').select_related('customer')


def get_dashboard_expenditures(scope):
    qs = _records(scope, Expenditure, 'recorded').select_related('location', 'expenditure_type')
    return qs.filter(location_id__in=scope.location_ids) if scope.location_ids is not None else qs


def get_dashboard_customers(scope):
    qs = _records(scope, Customer, 'finalized').select_related('location')
    return qs.filter(location_id__in=scope.location_ids) if scope.location_ids is not None else qs


def get_dashboard_metrics(scope):
    metrics = dict(configured=False, sales=None, expenditure=None, customers=None)
    if not scope.period or not scope.marketer:
        return metrics
    if scope.user.has_perm('api.view_sale'):
        metrics['sales'] = total(get_dashboard_sales(scope))
        policy = CommissionPolicy.objects.filter(marketer=scope.marketer, period=scope.period).first()
        if policy and policy.active:
            metrics.update(calculate_commission(metrics['sales'], policy.base, policy.rate), configured=True)
    if scope.user.has_perm('api.view_expenditure'):
        metrics['expenditure'] = total(get_dashboard_expenditures(scope))
    if scope.user.has_perm('api.view_customer'):
        metrics['customers'] = get_dashboard_customers(scope).count()
    return metrics


def dashboard_context(scope):
    metrics = get_dashboard_metrics(scope)
    setup_url = None
    policy_url = None
    user = scope.user
    if user.has_perm('api.manage_commissions'):
        if not scope.period:
            existing = CommissionPeriod.objects.first()
            if existing and user.has_perm('api.change_commissionperiod'):
                setup_url = reverse('api:edit', args=['periods', existing.pk])
            elif not existing and user.has_perm('api.add_commissionperiod'):
                setup_url = reverse('api:add', args=['periods'])
        elif scope.marketer and not metrics['configured']:
            policy = CommissionPolicy.objects.filter(marketer=scope.marketer, period=scope.period).first()
            if policy and user.has_perm('api.change_commissionpolicy'):
                policy_url = reverse('api:edit', args=['commissions', policy.pk])
            elif not policy and user.has_perm('api.add_commissionpolicy'):
                policy_url = reverse('api:add', args=['commissions']) + '?' + urlencode({'marketer': scope.marketer.pk, 'period': scope.period.pk})
    return dict(title='Dashboard', scope=scope, metrics=metrics, period=scope.period,
                setup_url=setup_url, policy_url=policy_url,
                dashboard_partial='api/partials/dashboard_content.html')


DASHBOARD_EXPORT_LIMIT = 5000
COMMISSION_EXPLANATION = 'Commission = max(Confirmed Sales − Base Amount, 0) × Rate'


class DashboardExportTooLarge(Exception):
    pass


def get_dashboard_export(scope):
    """Materialize one bounded, permission-aware payload for either renderer.

    Scope and all KPI calculations remain owned by the dashboard helpers.
    Unavailable model sections are explicitly identified, never treated as zero.
    The extra row detects growth after COUNT without silently truncating output.
    """
    require(scope.user, 'api.export_reports')
    require(scope.user, 'api.view_reports')
    if not scope.period or not scope.marketer:
        raise ValidationError('Configure a default commission period and select a permitted marketer before exporting.')
    sections = []
    specifications = [
        ('Sales', 'sale', get_dashboard_sales, ('Reference', 'Customer', 'Amount', 'Date'),
         lambda row: (row.reference, str(row.customer) if row.customer else '—', row.amount, row.date)),
        ('Expenditure', 'expenditure', get_dashboard_expenditures,
         ('Title', 'Type', 'Amount', 'Location', 'Date', 'Payment Method'),
         lambda row: (row.title, str(row.expenditure_type), row.amount,
                      str(row.location) if row.location else '—', row.date, row.payment_method or '—')),
        ('Customers', 'customer', get_dashboard_customers, ('Customer Name', 'Phone', 'Location', 'Date'),
         lambda row: (row.name, row.phone, str(row.location) if row.location else '—', row.date)),
    ]
    queries = [(spec, spec[2](scope) if scope.user.has_perm('api.view_' + spec[1]) else None)
               for spec in specifications]
    message = 'This dashboard exceeds 5,000 detail records. Select a narrower permitted location where applicable, or ask an administrator for help. No partial report was generated.'
    if sum(qs.count() for _, qs in queries if qs is not None) > DASHBOARD_EXPORT_LIMIT:
        raise DashboardExportTooLarge(message)
    remaining = DASHBOARD_EXPORT_LIMIT
    for (title, model, helper, headers, values), qs in queries:
        rows = [values(row) for row in qs[:remaining + 1]] if qs is not None else []
        remaining -= len(rows)
        if remaining < 0:
            raise DashboardExportTooLarge(message)
        sections.append(dict(title=title, headers=headers, rows=rows, available=qs is not None))
    return dict(scope=scope, metrics=get_dashboard_metrics(scope), sections=sections,
                marketer=scope.marketer.get_full_name() or scope.marketer.username,
                location=str(scope.location) if scope.location else 'All permitted locations',
                prepared_by=scope.user.get_full_name() or scope.user.username,
                generated_at=timezone.localtime(), explanation=COMMISSION_EXPLANATION)


def dashboard_export_filename(scope, extension):
    marketer = slugify(scope.marketer.get_full_name() or scope.marketer.username)[:70] or 'marketer'
    period = slugify(scope.period.name)[:70] or 'period'
    return f'marketflow-dashboard-{marketer}-{period}.{extension}'
