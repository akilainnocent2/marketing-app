from django.urls import path, register_converter
from django.contrib.auth import views as auth
from . import views, shop_sso
app_name='api'
urlpatterns=[
 path('dashboard/export/',views.dashboard_export,name='dashboard-export'),
 path('dashboard/export/pdf/',views.dashboard_export,{'format':'pdf'},name='dashboard-export-pdf'),
 path('dashboard/export/excel/',views.dashboard_export,{'format':'excel'},name='dashboard-export-excel'),
 path('dashboard/details/<str:metric>/',views.dashboard_detail,name='dashboard-detail'),
 path('accounts/sso/shop/start/',shop_sso.shop_sso_start,name='shop_sso_start'),
 path('accounts/sso/shop/consume/',shop_sso.shop_sso_consume,name='shop_sso_consume'),
 path('',views.dashboard,name='home'),path('dashboard/',views.dashboard,name='dashboard'),
 path('accounts/login/',views.RateLimitedLogin.as_view(),name='login'),path('accounts/signup/',views.signup,name='signup'),
 path('accounts/logout/',auth.LogoutView.as_view(),name='logout'),
 path('accounts/password/',auth.PasswordChangeView.as_view(template_name='api/auth.html',success_url='/dashboard/',extra_context={'title':'Change password','action':'Change password'}),name='password'),
 path('reports/',views.reports,name='reports'),
 path('locations/options/',views.location_options,name='location-options'),
 path('options/<str:kind>/create/',views.custom_option,name='custom-option'),
 path('drafts/<str:kind>/save/',views.draft_save,name='draft-save'),path('drafts/<str:kind>/resume/',views.draft_resume,name='draft-resume'),
 path('receipts/<int:pk>/',views.receipt,name='receipt'),
 path('records/<str:kind>/add/',views.edit,name='add'),path('records/<str:kind>/<int:pk>/edit/',views.edit,name='edit'),
 path('records/<str:kind>/<int:pk>/',views.detail,name='detail'),path('records/<str:kind>/<int:pk>/<str:action>/',views.transition,name='transition'),
]
class DatasetConverter:
    regex='(?:administration/(?:users|groups|logs)|marketing/(?:customers|sales|expenditures)|settings/(?:commissions|periods|expenditure-types|locations))'
    def to_python(self,value): return value.split('/')[-1]
    def to_url(self,value):
        module = 'administration' if value in ['users','groups','logs'] else 'marketing' if value in ['customers','sales','expenditures'] else 'settings'
        return module+'/'+value
register_converter(DatasetConverter,'dataset')
urlpatterns += [path('<dataset:kind>/',views.listing,name='list'),path('settings/commissions/bulk/',views.bulk,name='bulk'),path('reports/<str:kind>/pdf/',views.export,name='export')]

urlpatterns += [path('accounts/profile/',views.profile,name='profile'),path('lookups/<str:kind>/',views.lookup,name='lookup'),path('preferences/<str:kind>/',views.preferences,name='preferences'),path('validation/phone/',views.phone_validation,name='phone-validation'),path('drafts/<uuid:pk>/discard/',views.discard_draft,name='draft-discard')]
from django.conf import settings
if settings.PASSWORD_RESET_ENABLED:
    urlpatterns += [
        path('accounts/reset/',auth.PasswordResetView.as_view(template_name='api/auth.html',email_template_name='api/reset_email.txt',success_url='/accounts/reset/sent/',extra_context={'title':'Reset password','action':'Send reset email'}),name='password_reset'),
        path('accounts/reset/sent/',auth.PasswordResetDoneView.as_view(template_name='api/reset_done.html'),name='password_reset_done'),
        path('accounts/reset/<uidb64>/<token>/',auth.PasswordResetConfirmView.as_view(template_name='api/auth.html',success_url='/accounts/login/',extra_context={'title':'Set a new password','action':'Save password'}),name='password_reset_confirm'),
    ]

urlpatterns += [path('reports/<str:kind>/',views.report_detail,name='report-detail'),path('settings/commissions/preview/',views.policy_preview,name='policy-preview'),path('settings/remove/<str:kind>/<int:pk>/',views.remove_setting,name='remove-setting')]
