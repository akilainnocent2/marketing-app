import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.test import TestCase,RequestFactory
from django.db import transaction
from django.contrib.auth import get_user_model
from config.api.models import Customer,Sale,CommissionPeriod,CommissionPolicy
from config.api.pdf import build_pdf
from pypdf import PdfReader
from io import BytesIO
from datetime import date
from decimal import Decimal
import uuid,json
results={}
with transaction.atomic():
    user=get_user_model().objects.create_superuser('pdf_'+uuid.uuid4().hex[:8],password=uuid.uuid4().hex)
    period=CommissionPeriod.objects.create(name='PDF verification period',start=date(2024,1,1),end=date(2024,1,31))
    CommissionPolicy.objects.create(marketer=user,period=period,base=3000000,rate=3)
    for i in range(120):
        Sale.objects.create(reference='PDF-'+str(i),amount=50000,status='confirmed',description='A long description for table wrapping verification. '*5,date=date(2024,1,12),marketer=user,created_by=user,updated_by=user)
    req=RequestFactory().get('/reports/sales/pdf/',{'from':'2024-01-01','to':'2024-01-31'});req.user=user
    for name,cols,qs in [('wide',['reference','description','amount','date','marketer','status'],Sale.objects.filter(marketer=user)),('portrait',['reference','amount','date'],Sale.objects.filter(marketer=user)),('empty',['reference','amount','date'],Sale.objects.none())]:
        data=build_pdf(req,'sales',qs,cols);Path('evidence/pdf-'+name+'.pdf').write_bytes(data);reader=PdfReader(BytesIO(data));text='\n'.join(p.extract_text() for p in reader.pages)
        assert 'MarketFlow' in text and 'Page 1' in text
        if name!='empty':assert '90,000.00' in text and 'PDF-119' in text and len(reader.pages)>1
        assert any('Outfit' in str(f.get_object().get('/BaseFont')) for p in reader.pages for f in p['/Resources']['/Font'].values())
        results[name]={'pages':len(reader.pages),'embedded_outfit':True,'last_row_present':name=='empty' or 'PDF-119' in text,'commission_90000':name=='empty' or '90,000.00' in text}
    transaction.set_rollback(True)
Path('evidence/pdf-results.json').write_text(json.dumps(results,indent=2));print(results)
