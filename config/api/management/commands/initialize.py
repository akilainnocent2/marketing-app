import calendar
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group,Permission
from django.utils import timezone
from config.api.models import ExpenditureType, CommissionPeriod
class Command(BaseCommand):
    help='Seed roles, expense types and the current calendar-month period without overwriting existing assignments.'
    def handle(self,**options):
        marketer=['view_customer','add_customer','change_customer','delete_customer','view_sale','add_sale','change_sale','delete_sale','view_expenditure','add_expenditure','change_expenditure','delete_expenditure','view_reports','export_reports','view_commissionpolicy']
        for name in ['Administrator','Marketer']:
            group,created=Group.objects.get_or_create(name=name)
            if created:
                perms=Permission.objects.filter(content_type__app_label__in=['api','auth']) if name=='Administrator' else Permission.objects.filter(content_type__app_label='api',codename__in=marketer)
                group.permissions.set(perms)
        for name in ['Transport','Fuel','Meals','Airtime','Internet/Data','Accommodation','Printing/Stationery','Advertising/Promotion','Parking','Other']:
            ExpenditureType.objects.get_or_create(identity='shared:'+name.casefold(),defaults={'name':name})
        now=timezone.localdate(); start=now.replace(day=1); end=now.replace(day=calendar.monthrange(now.year,now.month)[1])
        if not CommissionPeriod.objects.filter(start__lte=end,end__gte=start).exists():
            CommissionPeriod.objects.create(name=now.strftime('%B %Y'),start=start,end=end)
        self.stdout.write(self.style.SUCCESS('Roles, types, and default calendar-month period initialized. No commission rates assigned.'))
