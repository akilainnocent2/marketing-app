import uuid
from django.http import HttpResponse
from django.template.loader import render_to_string
from .models import AuditLog
class RequestContext:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        request.correlation_id=uuid.uuid4()
        from .services import request_correlation
        token=request_correlation.set(request.correlation_id)
        try:response=self.get_response(request)
        finally:request_correlation.reset(token)
        response['X-Request-ID']=str(request.correlation_id)
        if response.status_code==403 and getattr(request,'user',None) and request.user.is_authenticated:
            AuditLog.objects.create(actor=request.user,action='access_denied',outcome='denied',correlation=request.correlation_id,summary={'method':request.method})
        if request.headers.get('HX-Request') and response.status_code==302 and '/accounts/login/' in response.get('Location',''):
            response=HttpResponse('Your session expired. Sign in again in another tab, then retry.',status=401)
        return response
