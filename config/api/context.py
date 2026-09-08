from django.urls import reverse
from .registry import REGISTRY, permission

def navigation(request):
    groups=[]
    if request.user.is_authenticated:
        for module,icon in [('Administration','user-circle'),('Marketing','pie-chart'),('Settings','settings'),('Report','bar-chart')]:
            links=[]
            for kind,(_,_,title,group,_,_) in REGISTRY.items():
                if group==module and request.user.has_perm(permission(kind)):
                    links.append({'title':title,'url':reverse('api:list',args=[kind]),'active':('/'+kind+'/') in request.path})
            if module=='Report' and request.user.has_perm('api.view_reports'):
                links=[{'title':'Overview','url':reverse('api:reports'),'active':request.path.startswith('/reports/')}]
                for kind in ['customers','sales','expenditures']:
                    if request.user.has_perm(permission(kind)):
                        links.append({'title':REGISTRY[kind][2],'url':reverse('api:report-detail',args=[kind]),'active':request.path==reverse('api:report-detail',args=[kind])})
            if links: groups.append({'title':module,'icon':icon,'links':links})
    from django.conf import settings
    return {'shop_app_url':settings.SHOP_APP_URL,'nav_groups':groups,'password_reset_enabled':settings.PASSWORD_RESET_ENABLED}
