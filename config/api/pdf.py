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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle, KeepTogether, CondPageBreak
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


def build_dashboard_pdf(report):
    """Management report, separate from the existing configurable list export."""
    from datetime import date
    font = Path(settings.APP_ROOT) / 'api/static/app/fonts/Outfit-Regular.ttf'
    face = 'Helvetica'
    if font.exists():
        if 'Outfit' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('Outfit', str(font)))
        face = 'Outfit'
    output = BytesIO()
    size = landscape(A4)
    doc = SimpleDocTemplate(output, pagesize=size, leftMargin=36, rightMargin=36,
                            topMargin=34, bottomMargin=44,
                            title='MarketFlow · Dashboard Performance Report',
                            author=report['prepared_by'])
    ink, blue, muted = [colors.HexColor(c) for c in ('#1d2939', '#465fff', '#667085')]
    normal = ParagraphStyle('DashboardBody', fontName=face, fontSize=10, leading=15, textColor=ink)
    heading = ParagraphStyle('DashboardSection', parent=normal, fontSize=16, leading=21,
                             spaceBefore=18, spaceAfter=8, keepWithNext=True)
    label = ParagraphStyle('DashboardLabel', parent=normal, fontSize=9, leading=13, textColor=muted)
    value = ParagraphStyle('DashboardValue', parent=normal, fontSize=19, leading=25, textColor=blue)
    cell = ParagraphStyle('DashboardCell', parent=normal, fontSize=9, leading=13)
    money_cell = ParagraphStyle('DashboardMoney', parent=cell, alignment=2)

    def p(text, style=normal):
        return Paragraph(escape(str(text)), style)

    def money(amount):
        return f'TZS {amount:,.2f}' if amount is not None else 'Not permitted'

    scope, metrics = report['scope'], report['metrics']
    story = [p('MarketFlow', ParagraphStyle('DashboardBrand', parent=normal, fontSize=27,
                                            leading=34, textColor=blue)),
             p('Dashboard Performance Report', heading),
             p(report['marketer'] + ' · ' + scope.period.name),
             p(f'{scope.period.start:%d %b %Y} – {scope.period.end:%d %b %Y}'),
             p('Location: ' + report['location']),
             p('Generated ' + report['generated_at'].strftime('%d %B %Y, %H:%M %Z')
               + ' · Prepared by ' + report['prepared_by'], label),
             p('Dashboard summary · Amounts in TZS', heading)]
    configured = metrics['configured']
    unavailable = 'Not configured' if metrics['sales'] is not None else 'Not permitted'
    kpis = [('Total Sales', money(metrics['sales'])),
            ('Total Expenditure', money(metrics['expenditure'])),
            ('Amount After Base', money(metrics['excess']) if configured else unavailable),
            ('Commission Rate', f"{metrics['rate']:g}%" if configured else unavailable),
            ('Total Commission', money(metrics['commission']) if configured else unavailable),
            ('Total Customers', f"{metrics['customers']:,}" if metrics['customers'] is not None else 'Not permitted')]
    kpi_cells = [[p(title, label), p(amount, value)] for title, amount in kpis]
    grid = LongTable([kpi_cells[:3], kpi_cells[3:]], colWidths=[doc.width / 3] * 3)
    grid.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f2f5ff')),
        ('BOX', (0, 0), (-1, -1), .5, colors.HexColor('#dce4ff')),
        ('INNERGRID', (0, 0), (-1, -1), 4, colors.white),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 14), ('RIGHTPADDING', (0, 0), (-1, -1), 14),
        ('TOPPADDING', (0, 0), (-1, -1), 12), ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
    ]))
    story += [grid, Spacer(1, 12)]
    if configured:
        story.append(p('Base Amount: ' + money(metrics['base'])))
    else:
        story.append(p('Commission policy not configured' if metrics['sales'] is not None
                       else 'Sales and commission: not permitted'))
    story.append(p(report['explanation'], label))
    if configured:
        story.append(p(f"max({money(metrics['sales'])} − {money(metrics['base'])}, 0) × {metrics['rate']:g}% = {money(metrics['commission'])}", label))
    story += [p('Expenditure does not reduce commission. Sales and commission cover all eligible period sales across locations.', label),
              p('The selected location and its permitted descendants filter expenditure and customers only.', label)]
    ratios = {'Sales': [.25, .37, .22, .16],
              'Expenditure': [.23, .15, .19, .16, .12, .15],
              'Customers': [.32, .23, .29, .16]}
    for section in report['sections']:
        title = section['title']
        count = len(section['rows'])
        noun = {'Sales': 'sale', 'Expenditure': 'expenditure record', 'Customers': 'customer'}[title]
        summary = f'{count:,} {noun}' + ('' if count == 1 else 's')
        if title in ('Sales', 'Expenditure') and section['available']:
            summary += ' · ' + money(metrics[title.lower()])
        section_heading = p(title, ParagraphStyle('DashboardDetailHeading', parent=heading, keepWithNext=False))
        count_line = p(summary if section['available'] else 'Not permitted',
                       ParagraphStyle('DashboardCount', parent=label, spaceAfter=8))
        if not section['rows']:
            story += [CondPageBreak(100), section_heading, count_line]
            story.append(p('No records in this scope.' if section['available'] else 'Your permissions do not include these records.', cell))
            continue
        rows = [[p(header, money_cell if header == 'Amount' else cell) for header in section['headers']]]
        for record in section['rows']:
            cells = []
            for header, item in zip(section['headers'], record):
                text = money(item) if header == 'Amount' else item.strftime('%d %b %Y') if isinstance(item, date) else item
                cells.append(p(text, money_cell if header == 'Amount' else cell))
            rows.append(cells)
        table = styled_table(rows, doc.width, ratios[title])
        # Very long, wrapped fields may split within a row as well as between rows.
        table.splitInRow = 1
        # Reserve the heading, count, header and first row without keeping an
        # entire multi-page table together (which wastes the preceding page).
        first_height = styled_table(rows[:2], doc.width, ratios[title]).wrap(doc.width, doc.height)[1]
        story += [CondPageBreak(min(doc.height, first_height + 80)), section_heading, count_line, table]

    def footer(canvas, document):
        canvas.setStrokeColor(colors.HexColor('#e4e7ec'))
        canvas.line(36, 34, size[0] - 36, 34)
        canvas.setFont(face, 9)
        canvas.setFillColor(muted)
        canvas.drawString(36, 21, 'MarketFlow · Confidential · Amounts in TZS')
        canvas.drawRightString(size[0] - 36, 21, f'Page {document.page}')

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
