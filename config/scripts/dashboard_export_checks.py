"""Browser assertions against an isolated dashboard fixture server.

Set BASE_URL, EVIDENCE_DIR, DASHBOARD_QUERY and DASHBOARD_SESSION_FILE.
The session file must belong to the disposable fixture, never a live account.
This script only reads pages/downloads; fixture creation is separate.
"""
import json
import os
from pathlib import Path

from openpyxl import load_workbook
from playwright.sync_api import sync_playwright
from pypdf import PdfReader


base = os.environ.get('BASE_URL', 'http://127.0.0.1:8011')
out = Path(os.environ['EVIDENCE_DIR'])
out.mkdir(parents=True, exist_ok=True)
query = os.environ['DASHBOARD_QUERY']
session = Path(os.environ['DASHBOARD_SESSION_FILE']).read_text().strip()

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
    context = browser.new_context(viewport={'width': 1536, 'height': 900}, accept_downloads=True)
    context.add_cookies([{'name': 'sessionid', 'value': session, 'url': base}])
    page = context.new_page()
    page.set_default_timeout(15000)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    measurements = []
    for width in [375, 600, 768, 1024, 1280, 1536, 1920]:
        page.set_viewport_size({'width': width, 'height': 812})
        page.goto(base + '/dashboard/?' + query)
        page.locator('.dashboard-metric').last.wait_for()
        page.evaluate('document.fonts.ready')
        cards = page.locator('.dashboard-metric')
        assert cards.count() == 6
        positions = cards.evaluate_all('(cards)=>cards.map(c=>({y:c.offsetTop,height:c.offsetHeight}))')
        columns = max(sum(c['y'] == row['y'] for c in positions) for row in positions)
        assert columns == (1 if width <= 600 else 2 if width <= 1100 else 3), (width, positions)
        assert max(c['height'] for c in positions) - min(c['height'] for c in positions) <= 2
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(out / f'dashboard-{width}.png'), full_page=True)
        for metric in ['sales', 'expenditure', 'after-base', 'commission', 'customers', 'export']:
            selector = '.dashboard-export-card' if metric == 'export' else f'.dashboard-metric[href*="/details/{metric}/"]'
            link = page.locator(selector)
            link.scroll_into_view_if_needed()
            before = page.evaluate('window.scrollY')
            link.focus()
            page.keyboard.press('Enter')
            page.locator('#modal.dashboard-sheet').wait_for()
            page.wait_for_timeout(220)
            box = page.locator('#modal').bounding_box()
            close = page.locator('.modal-close').bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1, (width, box)
            assert box['y'] >= 0 and box['y'] + box['height'] <= 813, (width, box)
            assert close['width'] >= 44 and close['height'] >= 44
            assert close['y'] >= 0 and close['y'] + close['height'] <= 812
            assert page.evaluate('document.body.style.position') == 'fixed'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            if width <= 600:
                assert abs(box['width'] - width) <= 1
                assert abs(box['y'] + box['height'] - 812) <= 1
            else:
                assert abs(box['x'] * 2 + box['width'] - width) <= 2
                assert abs(box['y'] * 2 + box['height'] - 812) <= 2
            if metric == 'expenditure':
                assert page.locator('#modal th').all_text_contents() == ['Title', 'Type', 'Amount', 'Location', 'Date', 'Payment method']
                assert 'Dashboard vendor must stay private' not in page.locator('#modal').inner_text()
                assert page.locator('#modal td').first.evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)') >= 14
                if width <= 600:
                    scroll = page.locator('#modal .table-scroll')
                    assert scroll.evaluate('(e)=>e.scrollWidth>e.clientWidth')
                    scroll.evaluate('(e)=>e.scrollLeft=e.scrollWidth')
                    assert scroll.evaluate('(e)=>e.scrollLeft') > 0
                page.locator('#modal-content').evaluate('(e)=>e.scrollTop=e.scrollHeight')
                page.locator('#modal .pagination a').last.click()
                page.get_by_text('Page 2 of 2', exact=False).wait_for()
                assert page.locator('#modal').evaluate('(e)=>e.classList.contains("dashboard-sheet")')
                page.locator('#modal-content').evaluate('(e)=>e.scrollTop=0')
            if metric == 'export':
                assert page.locator('#modal select').count() == 0
                options = page.locator('#modal .dashboard-format')
                assert options.count() == 2
                for option in options.all():
                    assert 'period=' not in option.get_attribute('href')
                    assert 'location=' in option.get_attribute('href')
                if width <= 600:
                    assert options.nth(1).bounding_box()['y'] > options.first.bounding_box()['y']
                for format, extension in [('PDF', 'pdf'), ('Excel', 'xlsx')]:
                    with page.expect_download() as download_info:
                        page.get_by_role('link', name=f'Get {format} dashboard', exact=False).click()
                    download = download_info.value
                    assert download.suggested_filename == f'marketflow-dashboard-alice-september-2026.{extension}'
                    path = out / download.suggested_filename
                    download.save_as(path)
                    if extension == 'pdf':
                        assert len(PdfReader(path).pages) >= 2
                    else:
                        assert load_workbook(path)['Overview']['D19'].value == 120000
                assert '/dashboard/?' in page.url
            page.screenshot(path=str(out / f'{metric}-{width}.png'))
            page.keyboard.press('Escape')
            page.locator('#modal').wait_for(state='hidden')
            page.wait_for_function('document.body.style.position === ""')
            assert page.evaluate('document.body.style.position') == ''
            assert not page.locator('#modal').evaluate('(e)=>e.classList.contains("dashboard-sheet")')
            assert link.evaluate('(e)=>e===document.activeElement')
            assert abs(page.evaluate('window.scrollY') - before) <= 2
        measurements.append({'width': width, 'columns': columns, 'dialogs': 6, 'overflow': False, 'downloads': ['pdf', 'xlsx']})

    # HTMX filter updates keep the export card in sync without navigating.
    page.goto(base + '/dashboard/?' + query)
    page.evaluate('window.dashboardSentinel=true')
    page.locator('select[name=location]').select_option('')
    page.wait_for_function('!document.querySelector(".dashboard-export-card").href.includes("location=")')
    assert page.evaluate('window.dashboardSentinel')
    page.locator('select[name=marketer]').select_option(label='Bob')
    page.wait_for_function('new URL(document.querySelector(".dashboard-export-card").href).searchParams.get("marketer") === document.querySelector("select[name=marketer]").value')
    page.locator('.dashboard-export-card').click()
    page.locator('.dashboard-export-scope').wait_for()
    assert 'Bob' in page.locator('.dashboard-export-scope').inner_text()
    assert 'All permitted locations' in page.locator('.dashboard-export-scope').inner_text()
    page.keyboard.press('Escape')

    # Ordinary CRUD dialogs must not inherit the dashboard sheet state.
    page.goto(base + '/marketing/customers/')
    page.locator('.card-heading a[data-modal]').click()
    page.locator('#modal input[name=name]').wait_for()
    assert not page.locator('#modal').evaluate('(e)=>e.classList.contains("dashboard-sheet")')
    page.keyboard.press('Escape')

    page.set_viewport_size({'width': 375, 'height': 667})
    page.emulate_media(reduced_motion='reduce', color_scheme='dark')
    page.goto(base + '/dashboard/?' + query)
    page.evaluate('document.documentElement.classList.add("dark")')
    page.locator('.dashboard-export-card').click()
    page.locator('#modal.dashboard-sheet').wait_for()
    assert page.locator('#modal').evaluate('(e)=>getComputedStyle(e).animationName') == 'none'
    page.get_by_role('link', name='Get Excel dashboard workbook').scroll_into_view_if_needed()
    assert page.locator('.modal-close').bounding_box()['y'] >= 0
    page.screenshot(path=str(out / 'export-dark-375.png'))
    page.keyboard.press('Escape')

    native = browser.new_context(java_script_enabled=False, accept_downloads=True)
    native.add_cookies([{'name': 'sessionid', 'value': session, 'url': base}])
    fallback = native.new_page()
    fallback.goto(base + '/dashboard/?' + query)
    fallback.locator('.dashboard-export-card').click()
    assert '/dashboard/export/' in fallback.url
    with fallback.expect_download() as download:
        fallback.get_by_role('link', name='Get Excel dashboard workbook').click()
    assert download.value.suggested_filename.endswith('.xlsx')
    assert not errors, errors
    (out / 'browser-results.json').write_text(json.dumps({'measurements': measurements, 'errors': errors,
        'keyboard_focus_escape': True, 'normal_attachment_downloads': True, 'no_js_fallback': True,
        'filter_refresh': True, 'reduced_motion': True, 'unrelated_dialog': True}, indent=2))
    print(json.dumps(measurements))
    browser.close()
