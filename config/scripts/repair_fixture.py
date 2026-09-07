"""Create browser fixtures only in a fresh, explicitly chosen /tmp SQLite DB.

Example: SQLITE_PATH=/tmp/marketflow-repair.sqlite3 .venv/bin/python scripts/repair_fixture.py
Never points at the application's existing database. Does not overwrite existing users.
"""
import os,sys
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
db=Path(os.environ.get('SQLITE_PATH','')).resolve()
if db.parent!=Path('/tmp') or not db.name.startswith('marketflow-repair'):
    raise SystemExit('Set SQLITE_PATH to /tmp/marketflow-repair*.sqlite3; existing application data is not a test fixture.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from config.api.models import CommissionPeriod,CommissionPolicy,Sale
call_command('migrate',interactive=False,verbosity=0)
if get_user_model().objects.exists():raise SystemExit('Use a fresh fixture database; this script never resets users or records.')
call_command('initialize',verbosity=0)
admin=get_user_model().objects.create_superuser('repair_admin',password='Local-Test-Only!573')
period=CommissionPeriod.objects.create(name='Repair January',start=date(2025,1,1),end=date(2025,1,31))
group=Group.objects.get(name='Marketer')
for name,sales,base,rate in [('A',7000000,3000000,3),('B',2000000,3000000,5),('C',8000000,2000000,5),('D',4000000,None,None),('Zero',0,0,0)]:
    user=get_user_model().objects.create_user(name);user.groups.add(group)
    if sales:Sale.objects.create(reference='Repair-'+name,marketer=user,created_by=admin,updated_by=admin,date=date(2025,1,12),status='confirmed',amount=sales)
    if base is not None:CommissionPolicy.objects.create(marketer=user,period=period,base=base,rate=rate)
for i in range(20):
    user=get_user_model().objects.create_user(f'Page-fixture-{i}')
    CommissionPolicy.objects.create(marketer=user,period=period,base=0,rate=0)
    a=get_user_model().objects.get(username='A')
    Sale.objects.create(reference=f'Page-draft-{i}',marketer=a,created_by=admin,updated_by=admin,date=date(2025,1,15),amount=1,status='draft')
print('Fixture ready; Repair January period:',period.pk)
