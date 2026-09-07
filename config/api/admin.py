from django.contrib import admin

from . import models
from .forms import PeriodForm
from .services import save_policy

# Maintenance access includes auth grants, so keep it restricted to superusers.
admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser
admin.site.site_header = 'MarketFlow maintenance'


@admin.register(models.CommissionPeriod)
class CommissionPeriodAdmin(admin.ModelAdmin):
    form = PeriodForm
    list_display = ('name', 'start', 'end', 'closed')
    list_filter = ('closed',)
    search_fields = ('name',)


@admin.register(models.CommissionPolicy)
class CommissionPolicyAdmin(admin.ModelAdmin):
    list_display = ('marketer', 'period', 'base', 'rate', 'active', 'version')
    list_filter = ('active', 'period')
    search_fields = ('marketer__username', 'period__name')
    readonly_fields = ('version',)

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (('marketer', 'period') if obj else ())

    def save_model(self, request, obj, form, change):
        save_policy(obj, request.user, 'System administrator policy correction')


class HistoryAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.PolicyRevision)
class PolicyRevisionAdmin(HistoryAdmin):
    list_display = ('policy', 'version', 'base', 'rate', 'actor', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('reason', 'actor__username')


@admin.register(models.AuditLog)
class AuditLogAdmin(HistoryAdmin):
    list_display = ('action', 'actor', 'target_type', 'target_id', 'timestamp')
    list_filter = ('action', 'target_type')
    search_fields = ('target_id', 'actor__username')


for model in (
    models.Location, models.Profile, models.Customer, models.Sale,
    models.ExpenditureType, models.Expenditure, models.Draft, models.Operation,
):
    admin.site.register(model)
