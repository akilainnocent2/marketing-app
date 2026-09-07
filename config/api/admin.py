from django.contrib import admin
# The native admin is maintenance-only. Business workflows run through scoped services.
# Restrict auth User/Group administration here to superusers to preserve grant ceilings.
admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser
admin.site.site_header = 'MarketFlow maintenance'
