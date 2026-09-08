from decimal import Decimal
from django import template
register=template.Library()
@register.filter
def field_value(obj,key):
    value=getattr(obj,key,'—')
    if value is None or value=='': return '—'
    if hasattr(value,'all'):return ', '.join(str(x) for x in value.all()) or '—'
    if isinstance(value,bool): return 'Yes' if value else 'No'
    if isinstance(value,Decimal): return f'{value:,.2f}'
    return value
@register.filter
def label(value): return value.replace('_',' ').title()
@register.filter
def money(value):
    if value is None or value == '': return 'Not configured'
    return f'{value:,.2f}'
@register.filter
def initials(user):
    name=user.get_full_name() or user.username
    return ''.join(x[0] for x in name.split()[:2]).upper()

@register.simple_tag
def can_act(user,kind,obj,action):
    from ..registry import permission
    from ..models import OwnedRecord,Sale
    if not user.has_perm(permission(kind,action)):return False
    if isinstance(obj,OwnedRecord) and obj.marketer_id!=user.pk and not user.has_perm('api.manage_all_marketing'):return False
    if isinstance(obj,Sale) and obj.status!='draft' and not user.has_perm('api.confirm_sale'):return False
    return True

@register.inclusion_tag('api/partials/permission_matrix.html')
def permission_matrix(field):
    selected={str(v) for v in (field.value() or [])};rows={}
    for permission in field.field.queryset.select_related('content_type').order_by('content_type__app_label','content_type__model','codename'):
        key=f'{permission.content_type.app_label} · {permission.content_type.model}'
        row=rows.setdefault(key,{'name':key,'standard':{},'custom':[]})
        action=permission.codename.split('_',1)[0]
        item={'pk':permission.pk,'name':permission.name,'selected':str(permission.pk) in selected}
        if action in ['view','add','change','delete'] and permission.codename==f'{action}_{permission.content_type.model}':row['standard'][action]=item
        else:row['custom'].append(item)
    for row in rows.values():row['cells']=[row['standard'].get(x) for x in ['view','add','change','delete']]
    return {'rows':rows.values(),'field_name':field.html_name}

@register.simple_tag
def icon(name):
    from pathlib import Path
    from django.utils.safestring import mark_safe
    if name not in {'grid','group','pie-chart','table','list','box','pencil','trash','eye','plus','download','chevron-down','chevron-left','arrow-right','time','user-circle','dollar-line','calender-line'}:return ''
    path=Path(__file__).resolve().parents[1]/'static/app/icons'/f'{name}.svg'
    return mark_safe(path.read_text()) if path.exists() else ''

@register.simple_tag(takes_context=True)
def query_update(context, **kwargs):
    data=context['request'].GET.copy()
    finance=context.get('finance')
    if finance and finance['period'] and not data.get('period'):data['period']=finance['period'].pk
    for key,value in kwargs.items():
        data.pop(key,None)
        if value is not None:data[key]=value
    return data.urlencode()

@register.simple_tag(takes_context=True)
def report_hidden_filters(context):
    from django.utils.html import format_html_join
    return format_html_join('', '<input type="hidden" name="{}" value="{}">',
        ((k,v) for k,values in context['request'].GET.lists() if k not in ['period','marketer','selection','page','card_page'] for v in values))

@register.simple_tag
def missing_policy_query(finance):
    from urllib.parse import urlencode
    return urlencode([('period',finance['period'].pk)]+[('marketers',r['marketer'].pk) for r in finance['selected']['issues']])

@register.simple_tag(takes_context=True)
def report_selection_fields(context):
    from django.utils.html import format_html_join
    return format_html_join('', '<input type="hidden" name="{}" value="{}">', ((key,v) for key in ['marketer','selection'] for v in context['request'].GET.getlist(key)))


@register.inclusion_tag('api/partials/notification_items.html', takes_context=True)
def configuration_notifications(context):
    """Use the report scope when available, otherwise the current authorized scope."""
    from django.http import QueryDict
    from ..reporting import report_context
    user = context['request'].user
    if context.get('scope') is not None:
        return {key: context.get(key) for key in ['scope', 'metrics', 'setup_url', 'policy_url', 'perms']}
    finance = context.get('finance')
    if finance is None and user.has_perm('api.view_reports') and user.has_perm('api.view_sale'):
        finance = report_context(user, QueryDict(''))
    return {'finance': finance, 'perms': context.get('perms')}
