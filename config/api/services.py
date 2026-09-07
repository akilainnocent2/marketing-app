from decimal import Decimal, ROUND_HALF_UP
from contextvars import ContextVar
request_correlation = ContextVar("request_correlation", default=None)
from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Sum
from .models import *


def audit(user, action, obj=None, summary=None, correlation=None):
    data = dict(actor=user, action=action, target_type=obj._meta.model_name if obj else '', target_id=str(obj.pk) if obj else '', summary=summary or {})
    correlation=correlation or request_correlation.get()
    if correlation: data['correlation'] = correlation
    return AuditLog.objects.create(**data)


def commission(marketer, period):
    sales = Sale.objects.filter(marketer=marketer, status='confirmed',date__gte=period.start,date__lte=period.end).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    policy = CommissionPolicy.objects.filter(marketer=marketer,period=period,active=True).first()
    if not policy: return dict(sales=sales, configured=False, commission=None, period=period)
    return dict(configured=True,period=period,**calculate_commission(sales,policy.base,policy.rate))


def financial_open(obj):
    if isinstance(obj, Sale) and CommissionPeriod.objects.filter(start__lte=obj.date,end__gte=obj.date,closed=True).exists():
        raise ValidationError('This commission period is closed. Reopen it before correcting sales.')


@transaction.atomic
def save_policy(policy, actor, reason=''):
    period=CommissionPeriod.objects.select_for_update().get(pk=policy.period_id)
    administrator = actor.has_perm('api.manage_commissions') and actor.has_perm('api.change_commissionpolicy')
    if period.closed and not administrator: raise ValidationError('This period is closed.')
    policy.period=period
    previous = CommissionPolicy.objects.select_for_update().filter(pk=policy.pk).first() if policy.pk else None
    if previous and policy.version != previous.version:
        raise ValidationError('This policy changed in another tab. Reopen it before saving.')
    counted = Sale.objects.filter(marketer=policy.marketer,status='confirmed',date__range=(policy.period.start,policy.period.end)).exists()
    if administrator and not reason: reason = 'Administrative policy correction'
    if counted and not reason: raise ValidationError('A correction reason is required because this period has confirmed sales. Review the whole-period impact before saving.')
    if previous:
        PolicyRevision.objects.create(policy=previous,version=previous.version,base=previous.base,rate=previous.rate,actor=actor,reason=reason or 'Policy update')
        policy.version = previous.version + 1
    policy.full_clean()
    policy.save()
    audit(actor,'policy_saved',policy,{'base':str(policy.base),'rate':str(policy.rate),'reason':reason})
    return policy

def calculate_commission(sales,base,rate):
    excess=max(sales-base,Decimal('0.00'))
    return dict(sales=sales,base=base,rate=rate,excess=excess,commission=(excess*rate/100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP),remaining=max(base-sales,Decimal('0.00')),progress=min(100,int(sales*100/base)) if base else 100)

def commission_batch(users,period):
    users=list(users)
    ids=[u.pk for u in users]
    amounts=dict(Sale.objects.filter(marketer_id__in=ids,status='confirmed',date__range=(period.start,period.end)).values('marketer_id').annotate(total=Sum('amount')).values_list('marketer_id','total'))
    policies={p.marketer_id:p for p in CommissionPolicy.objects.filter(marketer_id__in=ids,period=period,active=True)}
    result=[]
    for user in users:
        sales=amounts.get(user.pk,Decimal('0.00'));policy=policies.get(user.pk)
        c=dict(marketer=user,period=period,configured=bool(policy),sales=sales,commission=None)
        if policy:c.update(calculate_commission(sales,policy.base,policy.rate))
        result.append(c)
    return result
