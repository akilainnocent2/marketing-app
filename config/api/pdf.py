from io import BytesIO
from decimal import Decimal
from xml.sax.saxutils import escape
from pathlib import Path
from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle, KeepTogether
from .registry import REGISTRY
from .models import CommissionPeriod, Sale
from .services import commission
from .selectors import total

def build_pdf(request,kind,qs,cols):
    font=Path(settings.APP_ROOT)/'api/static/app/fonts/Outfit-Regular.ttf'
    face='Helvetica'
    if font.exists():
        if 'Outfit' not in pdfmetrics.getRegisteredFontNames(): pdfmetrics.registerFont(TTFont('Outfit',str(font)))
        face='Outfit'
    out=BytesIO();wide=len(cols)>5;size=landscape(A4) if wide else A4
    doc=SimpleDocTemplate(out,pagesize=size,rightMargin=36,leftMargin=36,topMargin=42,bottomMargin=45)
    styles=getSampleStyleSheet()
    for key in ['Normal','Title','Heading2','Heading3']:styles[key].fontName=face
    styles['Title'].textColor=colors.HexColor('#465fff');styles['Title'].alignment=0
    cellstyle=ParagraphStyle('cell',fontName=face,fontSize=9,leading=13,textColor=colors.HexColor('#344054'))
    p=lambda text:Paragraph(escape(str(text)),cellstyle)
    story=[Paragraph('MarketFlow',styles['Title']),Paragraph(REGISTRY[kind][2]+' report',styles['Heading2']),p('Generated '+timezone.localtime().strftime('%d %B %Y, %H:%M')+' · Africa/Dar_es_Salaam'),p('Prepared by '+(request.user.get_full_name() or request.user.username)),Spacer(1,12)]
    safe={k:v for k,v in request.GET.items() if k in ['q','from','to','marketer','status','min','max','potential','sort','location','period','type','payment','receipt'] and v}
    story += [p('Filters: '+('; '.join(f'{k}: {v}' for k,v in safe.items()) or 'All authorized records')),p(f'Records: {qs.count()}'),Spacer(1,12)]
    if kind in ['sales','expenditures']:
        status='confirmed' if kind=='sales' else 'recorded'
        story += [p(f'{status.title()} detail total: TZS {total(qs.filter(status=status)):,.2f}'),Spacer(1,12)]
    if kind=='sales':
        story += [Paragraph('Whole-period commission basis',styles['Heading3']),p('Detail filters do not restart the threshold. Each entitlement below uses every confirmed sale for that marketer within the saved period.'),Spacer(1,8)]
        users=list(qs.values_list('marketer_id',flat=True).distinct())
        periods=CommissionPeriod.objects.all()
        if request.GET.get('period'):periods=periods.filter(pk=request.GET['period'])
        if request.GET.get('from'): periods=periods.filter(end__gte=request.GET['from'])
        if request.GET.get('to'): periods=periods.filter(start__lte=request.GET['to'])
        rows=[[p(x) for x in ['Marketer / period','Eligible sales','Base','Excess','Rate','Commission']]]
        from django.contrib.auth import get_user_model
        for user in get_user_model().objects.filter(pk__in=users):
            for period in periods:
                c=commission(user,period)
                rows.append([p(f'{user} · {period.name} ({period.start} – {period.end})'),p(f"{c['sales']:,.2f}"),p(f"{c['base']:,.2f}" if c['configured'] else 'Not configured'),p(f"{c['excess']:,.2f}" if c['configured'] else '—'),p(f"{c['rate']}%" if c['configured'] else '—'),p(f"{c['commission']:,.2f}" if c['configured'] else '—')])
        if len(rows)>1: story.append(styled_table(rows,doc.width,[.29,.15,.15,.15,.09,.17]))
        else: story.append(p('No matching marketer-period commission data.'))
        story.append(Spacer(1,18))
    story.append(Paragraph('Detail records',styles['Heading3']))
    rows=[[p(c.replace('_',' ').title()) for c in cols]]
    for obj in qs.iterator():
        row=[]
        for col in cols:
            value=getattr(obj,col)
            if isinstance(value,Decimal): value=f'{value:,.2f}'
            if value is None:value='—'
            paragraph=p(value)
            if col in ['amount','base','rate']:
                paragraph.style=ParagraphStyle('money',parent=cellstyle,alignment=2)
            row.append(paragraph)
        rows.append(row)
    if len(rows)==1: story.append(p('No records match the selected filters.'))
    else:
        weights=[4 if c in ['description','comment'] else 2 if c in ['name','title','marketer','location'] else 1.5 for c in cols]
        story.append(styled_table(rows,doc.width,[w/sum(weights) for w in weights]))
    def footer(canvas,doc):
        canvas.setFont(face,9);canvas.setFillColor(colors.HexColor('#667085'))
        canvas.drawString(36,23,'MarketFlow · Confidential · Amounts in TZS')
        canvas.drawRightString(size[0]-36,23,f'Page {doc.page}')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()

def styled_table(rows,width,ratios=None):
    widths=[width*r for r in ratios] if ratios else [width/len(rows[0])]*len(rows[0])
    table=LongTable(rows,colWidths=widths,repeatRows=1,hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#ecf3ff')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f9fafb')]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9),('LINEBELOW',(0,0),(-1,0),.5,colors.HexColor('#d0d5dd'))]))
    return table
