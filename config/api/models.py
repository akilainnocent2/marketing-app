import uuid
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


def today():
    return timezone.localdate()


class Location(models.Model):
    LEVELS = [(x, x.title()) for x in ('region','district','ward','street','local')]
    name = models.CharField(max_length=150)
    normalized_name = models.CharField(max_length=150, db_index=True)
    source_name = models.CharField(max_length=150, blank=True)
    level = models.CharField(max_length=12, choices=LEVELS)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT)
    source = models.CharField(max_length=20, default='custom')
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)
    identity = models.CharField(max_length=400, unique=True)
    class Meta:
        ordering = ['name']
    def __str__(self):
        return self.name


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    phone = models.CharField(max_length=30, blank=True)
    reuse_location = models.BooleanField(default=True)
    last_location = models.ForeignKey(Location, null=True, blank=True, on_delete=models.SET_NULL)
    columns = models.JSONField(default=dict)


class OwnedRecord(models.Model):
    marketer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='%(class)s_records')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='%(class)s_created')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='%(class)s_updated')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    date = models.DateField(default=today, db_index=True)
    version = models.PositiveIntegerField(default=1)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    class Meta:
        abstract = True
        ordering = ['-date','-pk']


class Customer(OwnedRecord):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, db_index=True)
    location = models.ForeignKey(Location, null=True, blank=True, on_delete=models.PROTECT)
    address = models.CharField(max_length=250, blank=True)
    comment = models.CharField(max_length=500)
    potential = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=12, default='finalized', choices=[('finalized','Finalized'),('archived','Archived')], db_index=True)
    class Meta(OwnedRecord.Meta):
        permissions = [(x,x.replace('_',' ').title()) for x in ('view_all_marketing','manage_all_marketing','assign_marketer','view_reports','view_all_reports','export_reports','manage_commissions')]
    def __str__(self): return self.name


class Sale(OwnedRecord):
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.PROTECT)
    reference = models.CharField(max_length=60, unique=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('.01'))])
    description = models.CharField(max_length=500)
    status = models.CharField(max_length=12, default='draft', choices=[('draft','Draft'),('confirmed','Confirmed'),('void','Void')], db_index=True)
    class Meta(OwnedRecord.Meta):
        permissions = [('confirm_sale','Confirm and correct sales')]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0),name='positive_sale')]
    def __str__(self): return self.reference


class ExpenditureType(models.Model):
    name = models.CharField(max_length=100)
    identity = models.CharField(max_length=160, unique=True)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)
    class Meta: ordering = ['name']
    def __str__(self): return self.name


class Expenditure(OwnedRecord):
    title = models.CharField(max_length=150)
    expenditure_type = models.ForeignKey(ExpenditureType, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('.01'))])
    description = models.TextField(blank=True)
    payment_method = models.CharField(max_length=20, blank=True, choices=[(x,x) for x in ['Cash','Mobile Money','Bank Transfer','Other']])
    vendor = models.CharField(max_length=150, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    receipt = models.FileField(upload_to='receipts/%Y/%m', blank=True)
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.PROTECT)
    location = models.ForeignKey(Location, null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=12, default='recorded', choices=[('recorded','Recorded'),('void','Void')], db_index=True)
    class Meta(OwnedRecord.Meta):
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0),name='positive_expense')]
    def __str__(self): return self.title


class CommissionPeriod(models.Model):
    name = models.CharField(max_length=100)
    start = models.DateField()
    end = models.DateField()
    closed = models.BooleanField(default=False)
    class Meta:
        ordering = ['-start']
        constraints = [models.CheckConstraint(condition=models.Q(end__gte=models.F('start')), name='valid_period')]
    def __str__(self): return self.name


class CommissionPolicy(models.Model):
    marketer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    period = models.ForeignKey(CommissionPeriod, on_delete=models.CASCADE)
    base = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(0)])
    rate = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(0),MaxValueValidator(100)])
    version = models.PositiveIntegerField(default=1)
    active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['marketer','period'],name='one_policy'),models.CheckConstraint(condition=models.Q(base__gte=0,rate__gte=0,rate__lte=100),name='valid_policy')]
    def __str__(self): return f'{self.marketer} · {self.period}'


class PolicyRevision(models.Model):
    policy = models.ForeignKey(CommissionPolicy, null=True, blank=True, on_delete=models.SET_NULL)
    version = models.PositiveIntegerField()
    base = models.DecimalField(max_digits=18, decimal_places=2)
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    reason = models.CharField(max_length=500)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class Draft(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    kind = models.CharField(max_length=20)
    target = models.PositiveBigIntegerField(null=True, blank=True)
    target_version = models.PositiveIntegerField(null=True, blank=True)
    payload = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=0)
    complete = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class Operation(models.Model):
    token = models.UUIDField(primary_key=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=30)
    result = models.PositiveBigIntegerField(null=True)


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=60, db_index=True)
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.CharField(max_length=60, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    outcome = models.CharField(max_length=20, default='success')
    correlation = models.UUIDField(default=uuid.uuid4)
    summary = models.JSONField(default=dict)
    class Meta:
        ordering = ['-timestamp']
        default_permissions = ('view',)
    def __str__(self): return self.action
