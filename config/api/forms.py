import uuid
import phonenumbers
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.db.models import Q
from .models import *
from .selectors import eligible_users, locations, scoped


class LimitedSelect(forms.Select):
    """Bounded native fallback; validation still uses the entire scoped queryset."""
    def optgroups(self,name,value,attrs=None):
        choices=self.choices
        if hasattr(choices,'queryset'):
            ids=[v for v in value if str(v).isdigit()]
            qs=choices.queryset
            selected=list(qs.filter(pk__in=ids))
            first=list(qs[:30])
            objects={x.pk:x for x in selected+first}
            self.choices=[('', 'Select an option…')]+[(x.pk,str(x)) for x in objects.values()]
        result=super().optgroups(name,value,attrs)
        self.choices=choices
        return result

class LimitedSelectMultiple(LimitedSelect):
    allow_multiple_selected=True

class SignupForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('username','first_name','last_name','email')

class RecordForm(forms.ModelForm):
    version = forms.IntegerField(widget=forms.HiddenInput,initial=1)
    token = forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    draft_id = forms.UUIDField(widget=forms.HiddenInput,required=False)
    draft_version = forms.IntegerField(widget=forms.HiddenInput,required=False)
    def __init__(self,*args,user,**kwargs):
        self.user = user
        super().__init__(*args,**kwargs)
        if 'marketer' in self.fields:
            if user.has_perm('api.assign_marketer') and user.has_perm('api.manage_all_marketing'):
                self.fields['marketer'].queryset = eligible_users(user)
            else: del self.fields['marketer']
        if 'customer' in self.fields:
            self.fields['customer'].queryset = scoped(Customer,user).filter(status='finalized')
        if 'location' in self.fields: self.fields['location'].queryset = locations(user)
        if 'expenditure_type' in self.fields:
            self.fields['expenditure_type'].queryset = ExpenditureType.objects.filter(active=True).filter(Q(creator=None)|Q(creator=user)) if not user.has_perm('api.manage_all_marketing') else ExpenditureType.objects.filter(active=True)
        if self.instance.pk:
            self.initial['version'] = self.instance.version
        for name, field in self.fields.items():
            if isinstance(field, forms.DateField): field.widget = forms.DateInput(attrs={'type':'date'})
            if isinstance(field.widget, forms.Textarea): field.widget.attrs['rows'] = 3
        if 'phone' in self.fields: self.fields['phone'].widget.attrs['type']='tel'
        for name in ['location','customer','marketer','expenditure_type']:
            if name in self.fields:
                self.fields[name].widget=LimitedSelect(attrs={'data-lookup':name})
                self.fields[name].widget.choices=self.fields[name].choices
    def clean(self):
        data = super().clean()
        if 'marketer' not in self.fields and self.data.get('marketer') and str(self.data['marketer']) != str(self.user.pk):
            raise ValidationError('You cannot assign this record to another marketer.')
        owner = data.get('marketer') or (self.instance.marketer if self.instance.pk else self.user)
        if self.instance.pk and data.get('marketer') and data['marketer'].pk != self.instance.marketer_id:
            self.add_error('marketer','Existing record ownership cannot be reassigned through this form.')
        customer = data.get('customer')
        if customer and customer.marketer_id != owner.pk:
            self.add_error('customer','Customer must belong to the selected marketer.')
        return data

class CustomerForm(RecordForm):
    reuse_location = forms.BooleanField(required=False,initial=True,label='Reuse this location for my next customer')
    class Meta:
        model = Customer
        fields = ['marketer','location','address','name','phone','potential','comment','description','date']
    def clean_phone(self):
        value = self.cleaned_data['phone']
        try:
            number=phonenumbers.parse(value,'TZ')
            if not phonenumbers.is_valid_number(number) or number.country_code != 255: raise ValueError
            return phonenumbers.format_number(number,phonenumbers.PhoneNumberFormat.E164)
        except (ValueError,phonenumbers.NumberParseException): raise ValidationError('Enter a valid Tanzania phone number, for example 0712 345 678.')
    def clean_name(self): return ' '.join(self.cleaned_data['name'].split())

class SaleForm(RecordForm):
    correction_reason=forms.CharField(required=False,max_length=500)
    def clean(self):
        data=super().clean()
        if self.instance.pk and self.instance.status!='draft' and not data.get('correction_reason'):self.add_error('correction_reason','Explain this financial correction.')
        return data
    class Meta:
        model=Sale
        fields=['marketer','customer','reference','amount','date','description']

class ExpenditureForm(RecordForm):
    class Meta:
        model=Expenditure
        fields=['marketer','date','expenditure_type','amount','title','description','payment_method','vendor','reference','receipt','location','customer']
    def clean_receipt(self):
        f=self.cleaned_data.get('receipt')
        if f and hasattr(f,'content_type'):
            if f.size > 5*1024*1024: raise ValidationError('Receipt must be at most 5 MB.')
            head=f.read(16); f.seek(0)
            if head.startswith(b'%PDF-'):
                if not f.name.lower().endswith('.pdf'): raise ValidationError('PDF receipts must use .pdf.')
            else:
                from PIL import Image
                try:
                    im=Image.open(f); im.verify(); f.seek(0)
                    if im.format not in ['JPEG','PNG']: raise ValueError
                except Exception: raise ValidationError('Upload a valid JPEG, PNG, or PDF receipt.')
            f.name = str(uuid.uuid4()) + ('.pdf' if head.startswith(b'%PDF-') else '.png' if im.format=='PNG' else '.jpg')
        return f

class PeriodForm(forms.ModelForm):
    token=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4,required=False)
    name = forms.CharField(required=False, max_length=100, help_text='Optional. Leave blank to use the date range.')
    class Meta:
        model=CommissionPeriod
        fields=['name','start','end','closed']
        widgets={x:forms.DateInput(format='%Y-%m-%d', attrs={'type':'date'}) for x in ('start','end')}
        help_texts={'start': 'Periods may overlap.', 'end': 'Choose the same day or any later date.'}
    def clean(self):
        d=super().clean()
        if d.get('start') and d.get('end'):
            if d['end'] < d['start']:
                self.add_error('end', 'End date must be on or after the start date.')
                return d
            if not d.get('name'):
                d['name'] = f"{d['start']:%d %b %Y} – {d['end']:%d %b %Y}"
        return d

class PolicyForm(forms.ModelForm):
    version=forms.IntegerField(widget=forms.HiddenInput,required=False)
    token=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    reason=forms.CharField(required=False,widget=forms.Textarea,label='Correction reason')
    class Meta:
        model=CommissionPolicy
        fields=['marketer','period','base','rate','active']
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        from .reporting import cohort
        self.fields['marketer'].queryset=cohort(user)
        self.initial['version']=self.instance.version if self.instance.pk else 0
        if self.instance.pk:
            self.fields['marketer'].disabled=True; self.fields['period'].disabled=True

class TypeForm(forms.ModelForm):
    class Meta:
        model=ExpenditureType
        fields=['name','active']

class UserForm(forms.ModelForm):
    password = forms.CharField(required=False,widget=forms.PasswordInput,help_text="Required for new accounts. Leave blank to keep the existing password.")
    class Meta:
        model=get_user_model()
        fields=['username','first_name','last_name','email','is_active','groups','user_permissions']
    def __init__(self,*args,user,**kwargs):
        self.actor=user
        super().__init__(*args,**kwargs)
        if not user.is_superuser:
            allowed=Permission.objects.filter(pk__in=[p.pk for p in Permission.objects.select_related('content_type') if user.has_perm(f'{p.content_type.app_label}.{p.codename}')])
            self.fields['user_permissions'].queryset=allowed
            self.fields['groups'].queryset=Group.objects.exclude(permissions__in=Permission.objects.exclude(pk__in=allowed)).distinct()
    def clean(self):
        d=super().clean()
        password=d.get('password')
        if not self.instance.pk and not password:self.add_error('password','Set an initial password.')
        if password:
            from django.contrib.auth.password_validation import validate_password
            validate_password(password,self.instance)
        if self.instance.is_superuser and not self.actor.is_superuser: raise ValidationError('Only a superuser can edit this account.')
        if self.instance.is_superuser and not d.get('is_active') and get_user_model().objects.filter(is_superuser=True,is_active=True).count() <= 1: raise ValidationError('The last active superuser cannot be deactivated.')
        if not self.actor.is_superuser and self.instance.pk:
            if self.instance.is_staff or not self.instance.get_all_permissions().issubset(self.actor.get_all_permissions()): raise ValidationError('This account exceeds your permission ceiling.')
        return d

class GroupForm(forms.ModelForm):
    class Meta:
        model=Group
        fields=['name','permissions']
    def __init__(self,*args,user,**kwargs):
        self.actor=user
        super().__init__(*args,**kwargs)
        if not user.is_superuser:
            self.fields['permissions'].queryset=Permission.objects.filter(pk__in=[p.pk for p in Permission.objects.select_related('content_type') if user.has_perm(f'{p.content_type.app_label}.{p.codename}')])
    def clean(self):
        d=super().clean()
        if self.instance.pk and not self.actor.is_superuser:
            for p in self.instance.permissions.select_related('content_type'):
                if not self.actor.has_perm(f'{p.content_type.app_label}.{p.codename}'): raise ValidationError('This group exceeds your permission ceiling.')
        return d

class BulkPolicyForm(forms.Form):
    marketers=forms.ModelMultipleChoiceField(queryset=get_user_model().objects.none())
    period=forms.ModelChoiceField(queryset=CommissionPeriod.objects.filter(closed=False))
    base=forms.DecimalField(max_digits=18,decimal_places=2,min_value=0)
    rate=forms.DecimalField(max_digits=5,decimal_places=2,min_value=0,max_value=100)
    reason=forms.CharField(required=False,max_length=500)
    token=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        from .reporting import cohort
        if user.has_perm('api.manage_commissions') and user.has_perm('api.change_commissionpolicy'):
            self.fields['period'].queryset=CommissionPeriod.objects.all()
        self.fields['marketers'].queryset=cohort(user).order_by('pk')
        self.fields['marketers'].widget=LimitedSelectMultiple(attrs={'data-lookup':'report-marketer'})
        self.fields['marketers'].widget.choices=self.fields['marketers'].choices

class ProfileForm(forms.ModelForm):
    first_name=forms.CharField(max_length=150,required=False)
    last_name=forms.CharField(max_length=150,required=False)
    email=forms.EmailField(required=False)
    class Meta:
        model=Profile
        fields=['phone','reuse_location']

class LocationForm(forms.ModelForm):
    shared=forms.BooleanField(required=False,label='Publish to all marketers')
    class Meta:
        model=Location
        fields=['name','level','parent','active']
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['parent'].widget=LimitedSelect(attrs={'data-lookup':'location'})
        self.fields['parent'].widget.choices=self.fields['parent'].choices
        if self.instance.pk:
            self.initial['shared']=self.instance.creator_id is None
            self.fields['level'].disabled=True;self.fields['parent'].disabled=True
    def clean(self):
        d=super().clean();level=d.get('level');parent=d.get('parent');levels=list(dict(Location.LEVELS))
        if level=='region' and parent:self.add_error('parent','A region cannot have a parent.')
        if level and level!='region' and (not parent or levels.index(parent.level)!=levels.index(level)-1):self.add_error('parent','Select a parent from the preceding level.')
        if self.instance.pk and self.instance.source.startswith('mtaa') and d.get('name')!=self.instance.name:self.add_error('name','Keep imported source names intact. Create and merge a custom correction instead.')
        return d

class ReportFilterForm(forms.Form):
    """Read scope is independent of record assignment. Empty marketer is explicit."""
    period=forms.ModelChoiceField(queryset=CommissionPeriod.objects.all(),required=False)
    marketer=forms.ModelMultipleChoiceField(queryset=get_user_model().objects.none(),required=False)
    selection=forms.ChoiceField(choices=[('all','All authorized marketers'),('selected','Selected marketers')],required=False)
    def __init__(self,data=None,*,user,**kwargs):
        from .reporting import cohort
        from django.utils import timezone
        data=data.copy() if data is not None else __import__('django.http',fromlist=['QueryDict']).QueryDict('',mutable=True)
        if not data.get('period'):
            current=CommissionPeriod.objects.filter(start__lte=timezone.localdate(),end__gte=timezone.localdate()).first()
            if current:data['period']=str(current.pk)
        # Resolve malformed periods through the field, without querying an integer with arbitrary text.
        try: period=self.base_fields['period'].clean(data.get('period'))
        except ValidationError: period=None
        self.cohort=cohort(user,period)
        if 'marketer' in data:data.setlist('marketer',list(dict.fromkeys(x for x in data.getlist('marketer') if x)))
        super().__init__(data,**kwargs)
        self.fields['marketer'].queryset=self.cohort

    def clean(self):
        d=super().clean()
        if len(set(self.data.getlist('period')))>1:self.add_error(None,'Select one saved commission period.')
        for key in ['from','to']:
            value=self.data.get(key)
            if value:
                try: d[key]=forms.DateField().clean(value)
                except ValidationError:self.add_error(None,f'Invalid {key} date.')
        if d.get('from') and d.get('to') and d['from']>d['to']:self.add_error(None,'From date must not follow the to date.')
        for key in ['min','max']:
            if self.data.get(key):
                try:d[key]=forms.DecimalField(max_digits=18,decimal_places=2,min_value=0).clean(self.data[key])
                except ValidationError:self.add_error(None,f'Invalid {key} amount.')
        if d.get('min') is not None and d.get('max') is not None and d['min']>d['max']:self.add_error(None,'Minimum must not exceed maximum.')
        if self.data.get('status') and self.data['status'] not in dict(Sale._meta.get_field('status').choices):self.add_error(None,'Invalid sale status.')
        from .registry import REGISTRY
        allowed=REGISTRY['sales'][4]
        if self.data.get('sort') and self.data['sort'] not in allowed+['-'+x for x in allowed]:self.add_error(None,'Invalid sort column.')
        if any(c not in allowed for c in self.data.getlist('columns')):self.add_error(None,'Invalid report column.')
        return d
