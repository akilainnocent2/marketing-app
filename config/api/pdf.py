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

def build_pdf(request,kind,qs,cols,finance=None):
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
    safe={k:v for k,values in request.GET.lists() for v in [', '.join(values)] if k in ['q','from','to','marketer','status','min','max','potential','sort','location','period','type','payment','receipt'] and v}
    if finance:
        if 'marketer' in safe:safe['marketer']=', '.join(str(r['marketer']) for r in finance['rows']) or 'Empty selection'
        safe['period']=finance['basis']
    story += [p('Filters: '+('; '.join(f'{k}: {v}' for k,v in safe.items()) or 'All authorized records')),p(f'Records: {qs.count()}'),Spacer(1,12)]
    if kind in ['sales','expenditures']:
        status='confirmed' if kind=='sales' else 'recorded'
        story += [p(f'Filtered detail subtotal: TZS {total(qs):,.2f}'),p(f'{status.title()} detail total: TZS {total(qs.filter(status=status)):,.2f}'),Spacer(1,12)]
    if kind=='sales':
        story += [Paragraph('Whole-period commission basis',styles['Heading3']),p('Detail filters do not restart the threshold. Each entitlement below uses every confirmed sale for that marketer within the saved period.'),Spacer(1,8)]
        if finance is None:
            from .reporting import report_context
            finance=report_context(request.user,request.GET)
        story.append(p(finance['basis']))
        summaries=[('Selected marketers',finance['selected'])]
        if finance['show_global']:summaries.append(('All authorized marketers',finance['global_summary']))
        for label,summary in summaries:
            story.append(Paragraph(label,styles['Heading3']))
            story.append(p(f"{summary['count']} marketers · Confirmed sales: TZS {summary['sales']:,.2f}"))
            if finance['period']:
                title='Earned commission' if summary['complete'] else 'Calculated commission subtotal'
                story.append(p(f"Sales above bases: TZS {summary['excess']:,.2f} · {title}: TZS {summary['commission']:,.2f}"))
                story.append(p(f"Assigned base thresholds: TZS {summary['base']:,.2f} · Sales covered by bases: TZS {summary['covered']:,.2f}"))
                effective=f"{summary['effective_rate']:.2f}%" if summary['effective_rate'] is not None else 'Not applicable — no sales above base'
                story.append(p('Configured rate: '+summary['rate_label']+' · '+ '; '.join(f"{r['rate']}%: {r['count']} marketers" for r in summary['rates'])))
                story.append(p('Effective rate on sales above bases: '+effective+' · weighted configured outcome, not a new policy rate'))
                if not summary['complete']:story.append(p(f"{summary['unconfigured_count']} marketers need commission configuration; complete total pending. TZS {summary['unconfigured_sales']:,.2f} confirmed sales awaiting configuration. Base, excess and commission describe the configured subset."))
        rows=[[p(x) for x in ['Marketer / period','Eligible sales','Base','Excess','Rate','Commission']]]
        for c in finance['rows']:
            rows.append([p(f"{c['marketer']} · {finance['basis']}"),p(f"{c['sales']:,.2f}"),p(f"{c['base']:,.2f}" if c['configured'] else c['state']),p(f"{c['excess']:,.2f}" if c['configured'] else '—'),p(f"{c['rate']}%" if c['configured'] else '—'),p(f"{c['commission']:,.2f}" if c['configured'] else '—')])
            if c['configured']:
                story.append(p(f"{c['marketer']}: ({c['sales']:,.2f} − {c['base']:,.2f}) × {c['rate']:g}% = {c['commission']:,.2f} TZS (excess clamped to zero)"))
        if len(rows)>1:story.append(styled_table(rows,doc.width,[.29,.15,.15,.15,.09,.17]))
        else:story.append(p('No marketers selected.'))
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
