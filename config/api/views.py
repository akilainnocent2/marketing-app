import uuid,json,calendar
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.models import Group
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction, IntegrityError
from django.db.models import Q, Sum, Count
from django.http import JsonResponse, HttpResponse, FileResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.vary import vary_on_headers
from .reporting import report_context, organization, cohort
from .models import *
from .forms import SignupForm
from .registry import REGISTRY,permission
from .selectors import scoped,require,locations,eligible_users,total,location_descendants
from .services import commission,audit,save_policy,financial_open

class RateLimitedLogin(LoginView):
    redirect_authenticated_user = True
    template_name='api/auth.html'
    extra_context={'title':'Sign in','subtitle':'Enter your username and password to sign in.','action':'Sign in'}
    def form_valid(self, form):
        if cache.get(self.key(),0)>=10:
            form.add_error(None,'Too many attempts. Please try again in 15 minutes.')
            return self.form_invalid(form)
        return super().form_valid(form)
    def key(self):
        import hashlib
        return 'login:'+hashlib.sha256((self.request.META.get('REMOTE_ADDR','')+self.request.POST.get('username','').lower()).encode()).hexdigest()
    def form_invalid(self,form):
        cache.set(self.key(),cache.get(self.key(),0)+1,900)
        return super().form_invalid(form)


def signup(request):
    if request.user.is_authenticated: return redirect('api:dashboard')
    form=SignupForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            user=form.save()
            # Assign a fixed least-privilege permission set; never trust submitted roles.
            from django.contrib.auth.models import Permission
            allowed=['view_customer','add_customer','change_customer','delete_customer','view_sale','add_sale','change_sale','delete_sale','view_expenditure','add_expenditure','change_expenditure','delete_expenditure','view_reports','export_reports','view_commissionpolicy']
            user.user_permissions.set(Permission.objects.filter(content_type__app_label='api',codename__in=allowed))
            audit(user,'signup',user)
        login(request,user)
        return redirect('api:dashboard')
    return render(request,'api/auth.html',{'form':form,'title':'Create an account','subtitle':'Start managing your customers, sales, and expenses.','action':'Create account','signup':True})


def dataset(request,kind,action='view'):
    if kind not in REGISTRY: raise Http404
    require(request.user,permission(kind,action))
    model=REGISTRY[kind][0]
    if issubclass(model,OwnedRecord): return scoped(model,request.user,action!='view')
    if kind=='commissions' and not request.user.has_perm('api.manage_commissions'): return model.objects.filter(marketer=request.user)
    if kind=='locations': return locations(request.user)
    return model.objects.all()


def filtered(request,kind,qs):
    fields=REGISTRY[kind][4]; searches=REGISTRY[kind][5]
    q=request.GET.get('q','').strip()[:150]
    if q:
        expr=Q()
        for field in searches: expr |= Q(**{field+'__icontains':q})
        qs=qs.filter(expr)
    model=REGISTRY[kind][0]
    if issubclass(model,OwnedRecord):
        for key,lookup in [('from','date__gte'),('to','date__lte')]:
            if request.GET.get(key):
                try: value=date.fromisoformat(request.GET[key])
                except ValueError: raise ValidationError('Use a valid date filter.')
                qs=qs.filter(**{lookup:value})
        if 'marketer' in request.GET:
            raw=list(dict.fromkeys(x for x in request.GET.getlist('marketer') if x))
            try: ids=[int(x) for x in raw]
            except ValueError: raise ValidationError('Invalid marketer.')
            if not request.user.has_perm('api.view_all_marketing') and any(x!=request.user.pk for x in ids): raise PermissionDenied
            if not (kind=='sales' and request.GET.get('selection')=='all'):qs=qs.filter(marketer_id__in=ids)
        if request.GET.get('status'):
            allowed=dict(model._meta.get_field('status').choices)
            if request.GET['status'] not in allowed: raise ValidationError('Invalid status.')
            qs=qs.filter(status=request.GET['status'])
        for key,lookup in [('min','amount__gte'),('max','amount__lte')]:
            if request.GET.get(key) and 'amount' in fields:
                try:
                    amount=Decimal(request.GET[key])
                    if not amount.is_finite(): raise InvalidOperation
                except InvalidOperation: raise ValidationError('Invalid amount.')
                qs=qs.filter(**{lookup:amount})
        if kind=='customers' and request.GET.get('potential') in ['yes','no']: qs=qs.filter(potential=request.GET['potential']=='yes')
    if kind in ['customers','expenditures'] and request.GET.get('location'):
        try: location_id=int(request.GET['location'])
        except ValueError: raise ValidationError('Invalid location.')
        root=get_object_or_404(locations(request.user),pk=location_id)
        ids=location_descendants(request.user,root)
        qs=qs.filter(location_id__in=ids)
    if kind=='sales' and request.GET.get('period'):
        try: period_id=int(request.GET['period'])
        except ValueError: raise ValidationError('Invalid period.')
        period=get_object_or_404(CommissionPeriod,pk=period_id);qs=qs.filter(date__range=(period.start,period.end))
    if kind=='expenditures':
        if request.GET.get('type'):
            types=ExpenditureType.objects.all()
            if not request.user.has_perm('api.view_all_marketing'):types=types.filter(Q(creator=None)|Q(creator=request.user))
            selected=get_object_or_404(types,pk=request.GET['type']);qs=qs.filter(expenditure_type=selected)
        if request.GET.get('payment'):
            if request.GET['payment'] not in dict(Expenditure._meta.get_field('payment_method').choices):raise ValidationError('Invalid payment method.')
            qs=qs.filter(payment_method=request.GET['payment'])
        if request.GET.get('receipt') in ['yes','no']:qs=qs.exclude(receipt='') if request.GET['receipt']=='yes' else qs.filter(receipt='')
    if kind=='logs':
        for key,lookup in [('from','timestamp__date__gte'),('to','timestamp__date__lte')]:
            if request.GET.get(key):
                try:value=date.fromisoformat(request.GET[key])
                except ValueError:raise ValidationError('Invalid log date filter.')
                qs=qs.filter(**{lookup:value})
        for key in ['action','outcome','target_type']:
            if request.GET.get(key):qs=qs.filter(**{key:request.GET[key][:60]})
        if request.GET.get('actor'):
            actor=get_object_or_404(get_user_model(),pk=request.GET['actor']);qs=qs.filter(actor=actor)
    sort=request.GET.get('sort','')
    if sort and sort in fields+['-'+x for x in fields]: qs=qs.order_by(sort,'pk')
    elif not model._meta.ordering: qs=qs.order_by('-pk')
    return qs


def columns(request,kind):
    allowed=REGISTRY[kind][4]
    selected=request.GET.getlist('columns')
    if not selected:
        obj=Profile.objects.filter(user=request.user).first()
        selected=obj.columns.get(kind,[]) if obj else []
    return [x for x in allowed if x in selected] or allowed


@login_required
@vary_on_headers('HX-Request','HX-History-Restore-Request')
def listing(request,kind):
    qs=dataset(request,kind)
    if getattr(request,'report_mode',False):
        require(request.user,'api.view_reports')
        if not request.user.has_perm('api.view_all_reports'):qs=qs.filter(marketer=request.user)
    finance=None
    if kind=='sales' and request.user.has_perm('api.view_reports'):
        try: finance=report_context(request.user,request.GET)
        except ValidationError as e: return HttpResponse(' '.join(e.messages),status=400)
        qs=qs.filter(marketer_id__in=finance['selected_ids'])
    error=None
    try: qs=filtered(request,kind,qs)
    except ValidationError as e: error=' '.join(e.messages); qs=qs.none()
    model,form,title,module,fields,_=REGISTRY[kind]
    if issubclass(model,OwnedRecord): qs=qs.select_related('marketer')
    if kind in ['customers','expenditures']: qs=qs.select_related('location')
    if kind=='expenditures': qs=qs.select_related('expenditure_type')
    page=Paginator(qs,15).get_page(request.GET.get('page'))
    params=request.GET.copy(); params.pop('page',None)
    if finance and finance['period'] and not params.get('period'):params['period']=finance['period'].pk
    ctx={'title':title,'module':module,'kind':kind,'page':page,'columns':columns(request,kind),'all_columns':fields,'query':params.urlencode(),'error':error,'can_add':bool(form) and request.user.has_perm(permission(kind,'add')),'can_change':bool(form) and request.user.has_perm(permission(kind,'change')),'can_delete':kind in ['customers','sales','expenditures','users','groups','periods','commissions','expenditure-types'] and request.user.has_perm(permission(kind,'delete')),'amount_total':total(qs) if 'amount' in fields else None,'count':page.paginator.count}
    ctx['finance_cards']=Paginator(finance['rows'],18).get_page(request.GET.get('card_page')) if finance else None
    ctx['finance']=finance
    ctx['region']='#list-content'
    ctx['selected_marketers']=request.GET.getlist('marketer')
    ctx['eligible_detail_total']=total(qs.filter(status='confirmed')) if kind=='sales' else None
    ctx['statuses']=model._meta.get_field('status').choices if issubclass(model,OwnedRecord) else []
    ctx['location_options']=locations(request.user).filter(pk=request.GET.get('location')) if request.GET.get('location','').isdigit() else []
    ctx['period_options']=CommissionPeriod.objects.all() if kind=='sales' else []
    ctx['filter_users']=[] if finance else (cohort(request.user) if organization(request.user) else [])
    return render(request,'api/partials/list_content.html' if fragment_request(request) else 'api/list.html',ctx)


def form_response(request,context,status=200):
    from django.utils.cache import patch_vary_headers
    context['enhanced']=bool(fragment_request(request))
    response=render(request,'api/partials/form.html' if context['enhanced'] else 'api/form_page.html',context,status=status)
    patch_vary_headers(response,['HX-Request','HX-History-Restore-Request'])
    return response


@login_required
def edit(request,kind,pk=None):
    qs=dataset(request,kind,'change' if pk else 'add')
    model,formclass,title,module,_,_=REGISTRY[kind]
    if not formclass: raise Http404
    if module=='Settings': require(request.user,'api.manage_commissions' if kind in ['commissions','periods'] else permission(kind,'change' if pk else 'add'))
    obj=get_object_or_404(qs,pk=pk) if pk else model()
    if kind=='sales' and pk and obj.status!='draft': require(request.user,'api.confirm_sale')
    kwargs={'instance':obj}
    if kind in ['customers','sales','expenditures','commissions','users','groups']: kwargs['user']=request.user
    initial={}
    if kind=='commissions' and not pk and request.method=='GET' and (request.GET.get('marketer') or request.GET.get('period')):
        from .forms import ReportFilterForm
        context=ReportFilterForm(request.GET,user=request.user)
        if not context.is_valid() or len(context.cleaned_data['marketer'])!=1 or not context.cleaned_data['period']:
            return HttpResponse('Select a valid marketer and period.',status=400)
        marketer=context.cleaned_data['marketer'][0];period=context.cleaned_data['period']
        existing=CommissionPolicy.objects.filter(marketer=marketer,period=period).first()
        if existing:return edit(request,kind,existing.pk)
        initial={'marketer':marketer,'period':period,'active':True}
    if kind=='periods' and not pk:
        today=timezone.localdate()
        initial={'start':today.replace(day=1),'end':today.replace(day=calendar.monthrange(today.year,today.month)[1]),'name':today.strftime('%B %Y')}
    if kind=='customers' and not pk:
        profile,_=Profile.objects.get_or_create(user=request.user)
        initial={'reuse_location':profile.reuse_location,'location':profile.last_location if profile.reuse_location else None}
    form=formclass(request.POST if request.method=='POST' else None,request.FILES or None,initial=initial,**kwargs)
    if request.method=='POST' and (issubclass(model,OwnedRecord) or kind in ['commissions','periods']):
        try:
            prior=Operation.objects.filter(token=uuid.UUID(request.POST.get('token','')),owner=request.user,kind=kind,result__isnull=False).first()
            if prior: return saved_response(request,kind,model.objects.filter(pk=prior.result).first())
        except ValueError: pass
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                history={}
                period_op=None
                if kind=='periods' and form.cleaned_data.get('token'):
                    period_op,created=Operation.objects.get_or_create(token=form.cleaned_data['token'],defaults={'owner':request.user,'kind':kind})
                    if not created:
                        if period_op.owner_id!=request.user.pk or period_op.kind!=kind:raise PermissionDenied
                        if period_op.result:return saved_response(request,kind,model.objects.get(pk=period_op.result))
                        raise ValidationError('This request is still processing.')
                owned=issubclass(model,OwnedRecord)
                if owned:
                    token=form.cleaned_data['token']
                    op,created=Operation.objects.get_or_create(token=token,defaults={'owner':request.user,'kind':kind})
                    if not created:
                        if op.owner_id!=request.user.pk or op.kind!=kind: raise PermissionDenied
                        if op.result: return saved_response(request,kind)
                        raise ValidationError('This request is still processing. Retry shortly.')
                    if pk:
                        current=get_object_or_404(dataset(request,kind,'change').select_for_update(),pk=pk)
                        if current.version!=form.cleaned_data['version']: raise ValidationError('This record changed in another tab. Reopen it before saving.')
                        financial_open(current)
                        history['before']={f:str(getattr(current,f)) for f in ['date','status','version']+(['amount'] if hasattr(current,'amount') else [])}
                    instance=form.save(commit=False)
                    instance.marketer=form.cleaned_data.get('marketer') or (current.marketer if pk else request.user)
                    if not pk: instance.created_by=request.user
                    instance.updated_by=request.user
                    instance.version=(current.version+1) if pk else 1
                    financial_open(instance)
                    did=form.cleaned_data.get('draft_id')
                    if did:
                        draft=get_object_or_404(Draft.objects.select_for_update(),pk=did,owner=request.user,kind=kind,target=pk)
                        if draft.complete or draft.version!=form.cleaned_data.get('draft_version') or (pk and draft.target_version!=current.version): raise ValidationError('Draft changed in another tab. Resume the latest draft before saving.')
                        draft.complete=True; draft.save()
                    instance.save(); op.result=instance.pk; op.save()
                    if kind=='customers':
                        Profile.objects.update_or_create(user=request.user,defaults={'reuse_location':form.cleaned_data['reuse_location'],'last_location':instance.location})
                elif kind=='commissions':
                    token=form.cleaned_data['token']
                    op,created=Operation.objects.get_or_create(token=token,defaults={'owner':request.user,'kind':kind})
                    if not created:
                        if op.owner_id!=request.user.pk or op.kind!=kind:raise PermissionDenied
                        if op.result:return saved_response(request,kind)
                        raise ValidationError('This request is still processing.')
                    policy=form.save(commit=False)
                    policy.version=form.cleaned_data.get('version') or 0
                    if not pk:
                        CommissionPeriod.objects.select_for_update().get(pk=policy.period_id)
                        existing=CommissionPolicy.objects.filter(marketer=policy.marketer,period=policy.period).first()
                        if existing:raise ValidationError('A policy now exists for this marketer. Close and reopen setup to review the current policy.')
                        policy.version=1
                    instance=save_policy(policy,request.user,form.cleaned_data['reason'])
                    op.result=instance.pk;op.save()

                else:
                    instance=form.save(commit=False)
                    if kind=='expenditure-types': instance.identity='shared:'+instance.name.strip().casefold()
                    if kind=='locations':
                        instance.normalized_name=''.join(c for c in instance.name.casefold() if c.isalnum())
                        instance.creator=None if form.cleaned_data['shared'] else request.user
                        if not instance.identity:instance.identity=f'{instance.creator_id or 0}:{instance.parent_id or 0}:{instance.level}:{instance.normalized_name}'
                    if kind=='users' and form.cleaned_data.get('password'): instance.set_password(form.cleaned_data['password'])
                    instance.save(); form.save_m2m()
                if period_op:
                    period_op.result=instance.pk;period_op.save()
                if owned:
                    history['after']={f:str(getattr(instance,f)) for f in ['date','status','version']+(['amount'] if hasattr(instance,'amount') else [])}
                    history['reason']=form.cleaned_data.get('correction_reason','')
                audit(request.user,'updated' if pk else 'created',instance,history or {'fields':[x for x in form.changed_data if x in ['amount','status','base','rate','active','is_active','potential','date','is_default']]})
            return saved_response(request,kind,instance)
        except (ValidationError,IntegrityError) as e:
            form.add_error(None,' '.join(e.messages) if isinstance(e,ValidationError) else 'A matching record already exists. Refresh and try again.')
    return form_response(request,{'form':form,'title':('Edit ' if pk else 'Add ')+title.lower(),'kind':kind,'object':obj,'module':module,'action':'Save changes' if pk else 'Save '+title.lower(),'post_url':reverse('api:edit',args=[kind,obj.pk]) if kind=='commissions' and obj.pk else request.path,'draft_enabled':kind in ['customers','sales','expenditures'],'target_id':pk or ''},422 if request.method=='POST' else 200)


def saved_response(request,kind,instance=None):
    if request.headers.get('HX-Request'):
        response=HttpResponse(status=204); response['HX-Trigger']=json.dumps({'recordSaved':{'another':bool(request.POST.get('another')),'url':reverse('api:add',args=[kind]),'kind':kind,'id':instance.pk if instance else None,'marketers':[instance.marketer_id] if instance and hasattr(instance,'marketer_id') else [],'periods':[instance.period_id] if instance and hasattr(instance,'period_id') else [],'period':instance.pk if kind=='periods' and instance else None}}); return response
    messages.success(request,'Changes saved successfully.')
    if request.POST.get('another'):return redirect('api:add',kind=kind)
    return redirect('api:list',kind=kind)


@login_required
def detail(request,kind,pk):
    obj=get_object_or_404(dataset(request,kind),pk=pk)
    return form_response(request,{'title':str(obj),'object':obj,'detail_columns':REGISTRY[kind][4]+({'customers':['comment','description','address','created_by','updated_by'],'sales':['description','created_by','updated_by'],'expenditures':['description','payment_method','vendor','reference','customer','location','created_by','updated_by'],'logs':['summary','correlation','target_id'],'users':['groups']}.get(kind,[])),'kind':kind})


@login_required
def transition(request,kind,pk,action):
    if kind not in ['customers','sales','expenditures'] or action not in ['delete','confirm']: raise Http404
    obj=get_object_or_404(dataset(request,kind,'change' if action=='confirm' else 'delete'),pk=pk)
    if action=='confirm' or (kind=='sales' and obj.status!='draft'): require(request.user,'api.confirm_sale')
    if request.method=='POST':
        try:
            with transaction.atomic():
                obj=get_object_or_404(dataset(request,kind,'change' if action=='confirm' else 'delete').select_for_update(),pk=pk)
                financial_open(obj)
                if action=='confirm' and (kind!='sales' or obj.status!='draft'): raise ValidationError('Only a draft sale can be confirmed.')
                obj.status='confirmed' if action=='confirm' else 'archived' if kind=='customers' else 'void'
                obj.version+=1; obj.updated_by=request.user; obj.save()
                audit(request.user,action,obj,{'status':obj.status})
            return saved_response(request,kind)
        except ValidationError as e: return form_response(request,{'title':'Action unavailable','error':' '.join(e.messages)},422)
    return form_response(request,{'title':('Confirm ' if action=='confirm' else 'Archive / void ')+str(obj),'confirmation':'This changes the record status and recalculates affected totals. Its history is retained.','post_url':request.path,'action':'Confirm sale' if action=='confirm' else 'Archive / void'})


@login_required
@require_GET
def location_options(request):
    if not any(request.user.has_perm(permission(k,'add')) or request.user.has_perm(permission(k,'change')) for k in ['customers','expenditures']): raise PermissionDenied
    level=request.GET.get('level','region'); parent=request.GET.get('parent_id')
    if level not in dict(Location.LEVELS): return JsonResponse({'error':'Invalid level'},status=400)
    qs=locations(request.user).filter(level=level)
    if parent:
        p=get_object_or_404(locations(request.user),pk=parent)
        levels=list(dict(Location.LEVELS))
        if levels.index(level)!=levels.index(p.level)+1: return JsonResponse({'error':'Invalid parent level'},status=400)
        qs=qs.filter(parent=p)
    elif level!='region': return JsonResponse({'results':[],'more':False})
    else: qs=qs.filter(parent=None)
    normalized=''.join(c for c in request.GET.get('q','').casefold() if c.isalnum())
    qs=qs.filter(normalized_name__contains=normalized)
    page=Paginator(qs,30).get_page(request.GET.get('page'))
    return JsonResponse({'results':[{'id':x.pk,'label':x.name} for x in page],'more':page.has_next()})


@login_required
@require_POST
def custom_option(request,kind):
    require(request.user,'api.add_customer' if kind=='location' else 'api.add_expenditure')
    name=' '.join(request.POST.get('name','').split())[:100]
    if not name: return JsonResponse({'error':'Enter a name.'},status=422)
    if kind=='location':
        level=request.POST.get('level'); levels=list(dict(Location.LEVELS))
        if level not in levels: return JsonResponse({'error':'Invalid level'},status=422)
        parent=None
        if level!='region':
            parent=get_object_or_404(locations(request.user),pk=request.POST.get('parent_id'))
            if levels.index(level)!=levels.index(parent.level)+1: return JsonResponse({'error':'Invalid hierarchy'},status=422)
        norm=''.join(c for c in name.casefold() if c.isalnum())
        existing=locations(request.user).filter(parent=parent,level=level,normalized_name=norm).first()
        obj=existing or Location.objects.get_or_create(identity=f'{request.user.pk}:{parent.pk if parent else 0}:{level}:{norm}',defaults={'name':name,'normalized_name':norm,'level':level,'parent':parent,'creator':request.user})[0]
    elif kind=='type':
        obj=ExpenditureType.objects.get_or_create(identity=f'{request.user.pk}:{name.casefold()}',defaults={'name':name,'creator':request.user})[0]
    else: raise Http404
    return JsonResponse({'id':obj.pk,'label':obj.name})


@login_required
@require_POST
def draft_save(request,kind):
    if kind not in ['customers','sales','expenditures']: raise Http404
    target=request.POST.get('target')
    current=None
    if target:
        current=get_object_or_404(dataset(request,kind,'change'),pk=target)
        if kind=='sales' and current.status!='draft':require(request.user,'api.confirm_sale')
    else: dataset(request,kind,'add')
    allowed=REGISTRY[kind][1]._meta.fields
    payload={k:request.POST[k] for k in allowed if k in request.POST and k not in ['receipt','marketer']}
    try:
        with transaction.atomic():
            if request.POST.get('draft_id'):
                draft=get_object_or_404(Draft.objects.select_for_update(),pk=request.POST['draft_id'],owner=request.user,kind=kind,target=target or None)
                if draft.complete or draft.version!=int(request.POST.get('draft_version',-1)): return JsonResponse({'error':'Draft conflict. Reopen to resume the latest version.'},status=409)
            else: draft=Draft(owner=request.user,kind=kind,target=target or None,target_version=current.version if current else None)
            if payload.get('location'): get_object_or_404(locations(request.user),pk=payload['location'])
            if payload.get('customer'): get_object_or_404(scoped(Customer,request.user),pk=payload['customer'])
            draft.payload=payload; draft.version+=1; draft.save()
        return JsonResponse({'id':str(draft.pk),'version':draft.version})
    except (ValueError,ValidationError): return JsonResponse({'error':'Invalid draft.'},status=422)


@login_required
def draft_resume(request,kind):
    target=request.GET.get('target')
    if target: get_object_or_404(dataset(request,kind,'change'),pk=target)
    else: dataset(request,kind,'add')
    draft=Draft.objects.filter(owner=request.user,kind=kind,target=target or None,complete=False).order_by('-updated_at').first()
    return JsonResponse({'id':str(draft.pk),'version':draft.version,'payload':draft.payload,'target_version':draft.target_version} if draft else {})


@login_required
def receipt(request,pk):
    obj=get_object_or_404(dataset(request,'expenditures'),pk=pk)
    if not obj.receipt: raise Http404
    return FileResponse(obj.receipt.open('rb'),as_attachment=True,filename='receipt'+__import__('pathlib').Path(obj.receipt.name).suffix)


@login_required
@vary_on_headers('HX-Request', 'HX-History-Restore-Request')
def dashboard(request):
    if not request.user.has_perm('api.view_reports'):
        for kind in REGISTRY:
            if request.user.has_perm(permission(kind)): return redirect('api:list',kind=kind)
        return render(request,'api/no_access.html',status=403)
    from .dashboard import get_dashboard_scope, dashboard_context
    try:
        ctx = dashboard_context(get_dashboard_scope(request.user, request.GET))
    except ValidationError as exc:
        return HttpResponse(' '.join(exc.messages), status=400)
    return render(request, 'api/partials/dashboard_content.html' if fragment_request(request) else 'api/dashboard.html', ctx)


@login_required
def reports(request):
    require(request.user,'api.view_reports')
    return report_view(request)


def fragment_request(request):
    return request.headers.get('HX-Request') and request.headers.get('HX-History-Restore-Request')!='true'

@vary_on_headers('HX-Request','HX-History-Restore-Request')
def report_view(request):
    if not request.user.has_perm('api.view_sale'):
        metrics=[]
        for kind,status in [('customers','finalized'),('expenditures','recorded')]:
            if request.user.has_perm(permission(kind)):
                records=scoped(REGISTRY[kind][0],request.user).filter(status=status)
                if not request.user.has_perm('api.view_all_reports'):records=records.filter(marketer=request.user)
                metrics.append({'kind':kind,'value':records.count() if kind=='customers' else total(records)})
        ctx={'title':'Reports overview','metrics':metrics,'dashboard_partial':'api/partials/non_sales_dashboard.html'}
        return render(request,'api/partials/non_sales_dashboard.html' if fragment_request(request) else 'api/dashboard.html',ctx)
    try: finance=report_context(request.user,request.GET)
    except ValidationError as e: return HttpResponse(' '.join(e.messages),status=400)
    period=finance['period']; ids=finance['selected_ids']
    sales=Sale.objects.filter(marketer_id__in=ids)
    if period:sales=sales.filter(date__range=(period.start,period.end))
    from django.db.models.functions import TruncMonth
    chart=list(sales.filter(status='confirmed').order_by().annotate(month=TruncMonth('date')).values('month').annotate(value=Sum('amount')).order_by('month'))
    maximum=max([x['value'] for x in chart]+[Decimal(1)])
    for x in chart:x['height']=int(x['value']/maximum*100)
    page=Paginator(finance['rows'],18).get_page(request.GET.get('page'))
    expenses=Expenditure.objects.filter(marketer_id__in=ids,status='recorded')
    customers=Customer.objects.filter(marketer_id__in=ids,status='finalized')
    if period:
        expenses=expenses.filter(date__range=(period.start,period.end))
        customers=customers.filter(date__range=(period.start,period.end))
    ctx=dict(title='Reports overview',is_report=True,finance=finance,
             period=period,periods=CommissionPeriod.objects.all(),cards=page,marketer_page=page,
             chart=chart,recent=sales.select_related('marketer','customer')[:5],region='#dashboard-content',
             customer_count=customers.count() if request.user.has_perm('api.view_customer') else None,
             expense_total=total(expenses) if request.user.has_perm('api.view_expenditure') else None)
    return render(request,'api/partials/report_overview.html' if fragment_request(request) else 'api/dashboard.html',dict(ctx, dashboard_partial='api/partials/report_overview.html'))

@login_required
@vary_on_headers('HX-Request','HX-History-Restore-Request')
def bulk(request):
    from .forms import BulkPolicyForm
    from django.core import signing
    require(request.user,'api.manage_commissions'); require(request.user,'api.add_commissionpolicy'); require(request.user,'api.change_commissionpolicy')
    form=BulkPolicyForm(request.POST if request.method=='POST' else None,user=request.user,initial={'period':request.GET.get('period'),'marketers':request.GET.getlist('marketers')})
    preview=None
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        prior=Operation.objects.filter(token=d['token'],owner=request.user,kind='bulk',result__isnull=False).first()
        if prior and request.POST.get('commit'):return saved_response(request,'commissions')
        fingerprint={'users':sorted(u.pk for u in d['marketers']),'period':d['period'].pk,'base':str(d['base']),'rate':str(d['rate']),'reason':d['reason'],'actor':request.user.pk,'token':str(d['token'])}
        from .services import calculate_commission
        amounts=dict(Sale.objects.filter(marketer__in=d['marketers'],status='confirmed',date__range=(d['period'].start,d['period'].end)).order_by().values('marketer_id').annotate(n=Sum('amount')).values_list('marketer_id','n'))
        policies={p.marketer_id:p for p in CommissionPolicy.objects.filter(marketer__in=d['marketers'],period=d['period'])}
        preview=[]
        for user in d['marketers']:
            old=policies.get(user.pk)
            preview.append({'user':user,'base':old.base if old else None,'rate':old.rate if old else None,'version':old.version if old else 0,'before':calculate_commission(amounts.get(user.pk,Decimal(0)),old.base,old.rate) if old and old.active else None,'after':calculate_commission(amounts.get(user.pk,Decimal(0)),d['base'],d['rate'])})
        fingerprint['versions']=[p['version'] for p in preview]
        if request.POST.get('commit'):
            try:
                signed=signing.loads(request.POST.get('preview_token',''),max_age=900,salt='bulk')
                if signed!=fingerprint: raise ValidationError('Policies or selection changed. Preview again before applying.')
                with transaction.atomic():
                    op,created=Operation.objects.get_or_create(token=d['token'],defaults={'owner':request.user,'kind':'bulk'})
                    if not created:
                        if op.owner_id!=request.user.pk or op.kind!='bulk': raise PermissionDenied
                        return saved_response(request,'commissions')
                    period=CommissionPeriod.objects.select_for_update().get(pk=d['period'].pk)
                    locked={p.marketer_id:p for p in CommissionPolicy.objects.select_for_update().filter(period=period,marketer__in=d['marketers'])}
                    versions=[locked[u.pk].version if u.pk in locked else 0 for u in d['marketers']]
                    if versions!=signed['versions']:raise ValidationError('Policies changed. Preview again before applying.')
                    for user in d['marketers']:
                        policy=CommissionPolicy.objects.select_for_update().filter(marketer=user,period=d['period']).first() or CommissionPolicy(marketer=user,period=d['period'])
                        policy.base=d['base'];policy.rate=d['rate'];policy.active=True
                        save_policy(policy,request.user,d['reason'])
                        audit(request.user,'bulk_policy_assignment',policy,{'base':str(d['base']),'rate':str(d['rate'])},d['token'])
                    op.result=len(preview);op.save()
                return saved_response(request,'commissions')
            except (signing.BadSignature,ValidationError,IntegrityError) as e:
                form.add_error(None,' '.join(e.messages) if isinstance(e,ValidationError) else 'Bulk assignment could not be applied. Preview again.');preview=None
        preview_token=signing.dumps(fingerprint,salt='bulk')
    else: preview_token=''
    return render(request,'api/partials/bulk_form.html' if fragment_request(request) else 'api/bulk.html',{'enhanced':bool(fragment_request(request)),'title':'Bulk commission assignment','module':'Settings','form':form,'preview':preview,'preview_token':preview_token,'action':'Preview changes'})


@login_required
def export(request,kind):
    from .pdf import build_pdf
    require(request.user,'api.view_reports');require(request.user,'api.export_reports')
    if kind not in ['customers','sales','expenditures']: raise Http404
    qs=dataset(request,kind)
    if not request.user.has_perm('api.view_all_reports'): qs=qs.filter(marketer=request.user)
    finance=None
    try:
        if kind=='sales':
            finance=report_context(request.user,request.GET)
            qs=qs.filter(marketer_id__in=finance['selected_ids'])
        qs=filtered(request,kind,qs)
    except ValidationError as e: return HttpResponse(' '.join(e.messages),status=400)
    if qs.count()>5000: return HttpResponse('Narrow your filters to 5,000 rows or fewer.',status=422)
    cols=columns(request,kind)
    result=build_pdf(request,kind,qs,cols,finance=finance)
    response=HttpResponse(result,content_type='application/pdf')
    response['Content-Disposition']=f'attachment; filename="marketflow-{kind}.pdf"'
    return response

@login_required
def profile(request):
    from .forms import ProfileForm
    obj,_=Profile.objects.get_or_create(user=request.user)
    form=ProfileForm(request.POST if request.method=='POST' else None,instance=obj,initial={k:getattr(request.user,k) for k in ['first_name','last_name','email']})
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            form.save()
            for k in ['first_name','last_name','email']: setattr(request.user,k,form.cleaned_data[k])
            request.user.save(update_fields=['first_name','last_name','email'])
            audit(request.user,'profile_updated',obj)
        messages.success(request,'Your profile has been updated.');return redirect('api:profile')
    return form_response(request,{'title':'My profile','form':form,'action':'Save profile','module':'Account','post_url':request.path})


@login_required
@require_GET
def lookup(request,kind):
    if kind=='location':
        if not (request.user.has_perm('api.view_location') or request.user.has_perm('api.add_customer') or request.user.has_perm('api.view_reports') or request.user.has_perm('api.view_expenditure')):raise PermissionDenied
        qs=locations(request.user).filter(name__icontains=request.GET.get('q','')[:100])
    elif kind=='dashboard-marketer':
        require(request.user,'api.view_reports')
        from .services import get_default_commission_period
        q=request.GET.get('q','')[:100]
        qs=cohort(request.user,get_default_commission_period()).filter(Q(username__icontains=q)|Q(first_name__icontains=q)|Q(last_name__icontains=q))
    elif kind=='report-marketer':
        require(request.user,'api.view_reports');require(request.user,'api.view_sale')
        from .forms import ReportFilterForm
        form=ReportFilterForm(request.GET,user=request.user)
        if not form.is_valid():return JsonResponse({'error':'Invalid report filters'},status=400)
        q=request.GET.get('q','')[:100]
        qs=form.cohort.filter(Q(username__icontains=q)|Q(first_name__icontains=q)|Q(last_name__icontains=q))
    elif kind=='marketer':
        require(request.user,'api.assign_marketer');require(request.user,'api.manage_all_marketing');qs=eligible_users(request.user)
        q=request.GET.get('q','')[:100];qs=qs.filter(Q(username__icontains=q)|Q(first_name__icontains=q)|Q(last_name__icontains=q))
    elif kind=='customer':
        require(request.user,'api.view_customer');qs=scoped(Customer,request.user).filter(status='finalized')
        owner=request.GET.get('marketer')
        if owner:
            if str(owner)!=str(request.user.pk) and not request.user.has_perm('api.assign_marketer'):raise PermissionDenied
            qs=qs.filter(marketer_id=owner)
        else:qs=qs.filter(marketer=request.user)
        qs=qs.filter(Q(name__icontains=request.GET.get('q','')[:100])|Q(phone__icontains=request.GET.get('q','')[:100]))
    elif kind=='expenditure_type':
        require(request.user,'api.add_expenditure')
        qs=ExpenditureType.objects.filter(active=True)
        if not request.user.has_perm('api.manage_all_marketing'):qs=qs.filter(Q(creator=None)|Q(creator=request.user))
        qs=qs.filter(name__icontains=request.GET.get('q','')[:100])
    else: raise Http404
    page=Paginator(qs.order_by('pk'),30).get_page(request.GET.get('page'))
    return JsonResponse({'results':[{'id':obj.pk,'label':str(obj)} for obj in page],'more':page.has_next()})


@login_required
@require_POST
def preferences(request,kind):
    dataset(request,kind)
    allowed=REGISTRY[kind][4]
    cols=[x for x in request.POST.getlist('columns') if x in allowed]
    obj,_=Profile.objects.get_or_create(user=request.user)
    obj.columns={**obj.columns,kind:cols or allowed};obj.save(update_fields=['columns'])
    return JsonResponse({'saved':True})


@login_required
@require_GET
def phone_validation(request):
    require(request.user,'api.view_customer')
    from .forms import CustomerForm
    form=CustomerForm(user=request.user,data={'phone':request.GET.get('phone','')})
    form.is_valid()
    if 'phone' in form.errors:return JsonResponse({'error':form.errors['phone'][0]})
    phone=form.cleaned_data.get('phone')
    return JsonResponse({'warning':'A customer with this phone number already exists in your authorized records.' if scoped(Customer,request.user).filter(phone=phone,status='finalized').exists() else '', 'normalized':phone})


@login_required
@require_POST
def discard_draft(request,pk):
    draft=get_object_or_404(Draft,pk=pk,owner=request.user,complete=False)
    draft.complete=True;draft.version+=1;draft.save(update_fields=['complete','version'])
    return JsonResponse({'discarded':True})

@login_required
def report_detail(request,kind):
    if kind not in ['customers','sales','expenditures']:raise Http404
    request.report_mode=True
    return listing(request,kind)


@login_required
@require_GET
def policy_preview(request):
    from .services import calculate_commission
    require(request.user,'api.manage_commissions')
    try:
        if not (request.user.has_perm('api.add_commissionpolicy') or request.user.has_perm('api.change_commissionpolicy')):raise PermissionDenied
        values={k:Decimal(request.GET.get(k,'0')) for k in ['sales','base','rate']}
        old=None
        if request.GET.get('marketer') and request.GET.get('period'):
            from .forms import ReportFilterForm
            context=ReportFilterForm(request.GET,user=request.user)
            if not context.is_valid() or len(context.cleaned_data['marketer'])!=1 or not context.cleaned_data['period']:raise ValueError
            marketer=context.cleaned_data['marketer'][0];period=context.cleaned_data['period']
            values['sales']=total(Sale.objects.filter(marketer=marketer,status='confirmed',date__range=(period.start,period.end)))
            policy=CommissionPolicy.objects.filter(marketer=marketer,period=period).first()
            if policy:old=calculate_commission(values['sales'],policy.base,policy.rate)

        if any(not x.is_finite() or x<0 for x in values.values()) or values['rate']>100:raise ValueError
        return JsonResponse({**calculate_commission(values['sales'],values['base'],values['rate']),'old':old})
    except (ValueError,InvalidOperation):return JsonResponse({'error':'Enter nonnegative sales/base and a rate from 0 to 100.'},status=422)


@login_required
def remove_setting(request,kind,pk):
    if kind not in ['users','groups','periods','commissions','expenditure-types']:raise Http404
    obj=get_object_or_404(dataset(request,kind,'delete'),pk=pk)
    if kind in ['periods','commissions']:require(request.user,'api.manage_commissions')
    if kind=='users':
        if obj.is_superuser and (not request.user.is_superuser or obj.is_active and get_user_model().objects.filter(is_active=True,is_superuser=True).count()<=1):raise PermissionDenied
        if not request.user.is_superuser and (obj.is_staff or not obj.get_all_permissions().issubset(request.user.get_all_permissions())):raise PermissionDenied
    if kind=='groups' and not request.user.is_superuser:
        for p in obj.permissions.select_related('content_type'):
            if not request.user.has_perm(f'{p.content_type.app_label}.{p.codename}'):raise PermissionDenied
    if request.method=='POST':
        from django.db.models.deletion import ProtectedError
        try:
            with transaction.atomic():
                audit(request.user,'deleted',obj)
                obj.delete()
            return saved_response(request,kind)
        except (ProtectedError,ValidationError) as e:
            return form_response(request,{'title':'Record retained','error':' '.join(e.messages) if isinstance(e,ValidationError) else 'This record is referenced by historical data. Deactivate it instead.'},422)
    return form_response(request,{'title':'Delete '+str(obj),'confirmation':('Delete this period and its commission policies? Sales and policy revisions will be retained; commission totals will be recalculated.' if kind=='periods' else 'Delete this commission policy? Sales and policy revisions will be retained; commission totals will be recalculated.' if kind=='commissions' else 'Delete this record only if it has no protected history. Referenced records will be retained.'),'kind':kind,'action':'Delete','post_url':request.path})


@login_required
@require_GET
@vary_on_headers('HX-Request', 'HX-History-Restore-Request')
def dashboard_detail(request, metric):
    from .dashboard import (get_dashboard_scope, dashboard_context, get_dashboard_sales,
                            get_dashboard_expenditures, get_dashboard_customers)
    titles = {'sales': 'Confirmed Sales', 'expenditure': 'Recorded Expenditure',
              'customers': 'Customers', 'after-base': 'Commission Basis', 'commission': 'Commission Details'}
    if metric not in titles:
        raise Http404
    require(request.user, 'api.view_' + {'expenditure': 'expenditure', 'customers': 'customer'}.get(metric, 'sale'))
    try:
        scope = get_dashboard_scope(request.user, request.GET)
        ctx = dashboard_context(scope)
    except ValidationError as exc:
        return HttpResponse(' '.join(exc.messages), status=400)
    queries = {'sales': get_dashboard_sales, 'expenditure': get_dashboard_expenditures, 'customers': get_dashboard_customers}
    if metric in queries and scope.period and scope.marketer:
        ctx['page'] = Paginator(queries[metric](scope), 20).get_page(request.GET.get('page'))
    ctx.update(title=titles[metric], metric=metric)
    return render(request, 'api/partials/dashboard_detail.html' if fragment_request(request) else 'api/dashboard_detail.html', ctx)


@login_required
@require_GET
@vary_on_headers('HX-Request', 'HX-History-Restore-Request')
def dashboard_export(request, format=None):
    from .dashboard import (get_dashboard_scope, get_dashboard_export,
                            dashboard_export_filename, DashboardExportTooLarge)
    require(request.user, 'api.view_reports')
    require(request.user, 'api.export_reports')
    try:
        scope = get_dashboard_scope(request.user, request.GET)
        if format is None:
            context = dict(title='Export dashboard', scope=scope, period=scope.period)
            return render(request, 'api/partials/dashboard_export.html' if fragment_request(request)
                          else 'api/dashboard_export.html', context)
        report = get_dashboard_export(scope)
    except ValidationError as exc:
        return HttpResponse(' '.join(exc.messages), status=400, content_type='text/plain')
    except DashboardExportTooLarge as exc:
        return HttpResponse(str(exc), status=422, content_type='text/plain')
    if format == 'pdf':
        from .pdf import build_dashboard_pdf
        content = build_dashboard_pdf(report)
        mime, extension = 'application/pdf', 'pdf'
    elif format == 'excel':
        from .excel import build_dashboard_excel
        content = build_dashboard_excel(report)
        mime, extension = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'xlsx'
    else:
        raise Http404
    response = HttpResponse(content, content_type=mime)
    response['Content-Disposition'] = f'attachment; filename="{dashboard_export_filename(scope, extension)}"'
    response['Cache-Control'] = 'private, no-store'
    return response
