from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from .models import *
from .forms import *
# Model, form, title, module, visible/exportable fields, search fields.
REGISTRY={
 'customers':(Customer,CustomerForm,'Customers','Marketing',['name','phone','location','potential','date','marketer','status'],['name','phone']),
 'sales':(Sale,SaleForm,'Sales','Marketing',['reference','customer','amount','date','marketer','status'],['reference','description']),
 'expenditures':(Expenditure,ExpenditureForm,'Expenditure','Marketing',['title','expenditure_type','amount','location','date','marketer','status'],['title','reference']),
 'periods':(CommissionPeriod,PeriodForm,'Commission periods','Settings',['name','start','end','closed','is_default'],['name']),
 'commissions':(CommissionPolicy,PolicyForm,'Commission policies','Settings',['marketer','period','base','rate','active'],['marketer__username']),
 'expenditure-types':(ExpenditureType,TypeForm,'Expenditure types','Settings',['name','active'],['name']),
 'locations':(Location,LocationForm,'Location management','Settings',['name','level','parent','source','active'],['name']),
 'users':(get_user_model(),UserForm,'Users','Administration',['username','first_name','last_name','email','is_active'],['username','first_name','last_name']),
 'groups':(Group,GroupForm,'Groups & permissions','Administration',['name'],['name']),
 'logs':(AuditLog,None,'Activity & authentication logs','Administration',['timestamp','actor','action','target_type','outcome'],['action','actor__username']),
}
def permission(kind,action='view'):
 model=REGISTRY[kind][0]
 return f'{model._meta.app_label}.{action}_{model._meta.model_name}'
