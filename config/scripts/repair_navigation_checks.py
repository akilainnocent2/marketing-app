"""Extra request-level checks against the isolated repair browser fixture."""
import json
from pathlib import Path
import os
BASE=os.getenv('BASE_URL','http://127.0.0.1:8000')
from playwright.sync_api import sync_playwright
OUT=Path('evidence/repair-2026-09-07')
with sync_playwright() as p:
    browser=p.chromium.launch(args=['--no-sandbox']);page=browser.new_page(viewport={'width':1536,'height':1000});page.set_default_timeout(15000)
    requests=[];errors=[]
    page.on('request',lambda r:requests.append({'url':r.url,'type':r.resource_type,'navigation':r.is_navigation_request()}))
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(BASE+'/accounts/login/');page.fill('[name=username]','repair_admin');page.fill('[name=password]','Local-Test-Only!573');page.click('button[type=submit]');page.wait_for_url('**/dashboard/')
    page.goto(BASE+'/dashboard/?period=2')
    start=len(requests);page.locator('.marketers-section a[data-region-link]').filter(has_text='Next').click();page.wait_for_function("location.search.includes('page=2')")
    assert 'TZS 480,000.00' in page.locator('.finance-summary').nth(1).inner_text()
    assert not any(r['navigation'] for r in requests[start:])
    page.goto(BASE+'/marketing/sales/?period=2&marketer=2&marketer=3&columns=reference&columns=amount')
    start=len(requests);page.locator('.list-card .pagination a').filter(has_text='Next').click();page.wait_for_function("location.search.includes('page=2')")
    assert page.url.count('marketer=')==2 and page.url.count('columns=')==2
    page.fill('.list-card [name=q]','Page-draft');page.locator('.list-card .filters button[type=submit]').click();page.wait_for_function("location.search.includes('q=Page-draft')")
    assert page.url.count('marketer=')==2 and page.url.count('columns=')==2
    assert 'TZS 120,000.00' in page.locator('.finance-summary').first.inner_text()
    assert not any(r['navigation'] for r in requests[start:])
    # Hold A's old response, submit B, then release A: B must remain the canonical result.
    page.goto(BASE+'/dashboard/?period=2')
    pending=[]
    def delay(route):
        if 'marketer=2' in route.request.url and 'marketer=3' not in route.request.url:
            pending.append((route,route.fetch()))
        else:route.continue_()
    page.route('**/dashboard/?*',delay)
    page.locator('.marketer-picker summary').click();page.select_option('[data-report-filter] select[name=marketer]',label='A');page.locator('[data-report-filter] button').filter(has_text='Apply').click();page.wait_for_timeout(200);assert pending
    page.select_option('[data-report-filter] select[name=marketer]',label='B');page.locator('[data-report-filter]').evaluate('(f)=>f.requestSubmit()')
    page.wait_for_function("document.querySelector('.finance-summary dd').textContent.includes('2,000,000.00')")
    for route,response in pending:
        try:route.fulfill(response=response)
        except Exception:pass # The obsolete fetch may already have been aborted.
    page.wait_for_timeout(250)
    assert '2,000,000.00' in page.locator('.finance-summary dd').first.inner_text()
    page.unroute('**/dashboard/?*')
    # Ordinary module link still performs document navigation.
    start=len(requests);page.locator('.sidebar a').filter(has_text='Customers').first.click();page.wait_for_url('**/marketing/customers/')
    assert any(r['navigation'] and r['type']=='document' for r in requests[start:])
    assert not errors,errors
    (OUT/'navigation-results.json').write_text(json.dumps({'card_pagination':True,'table_pagination':True,'repeated_filters_columns':True,'detail_filters_preserve_finance':True,'stale_response_ignored':True,'module_document_navigation':True,'javascript_errors':errors,'requests':requests},indent=2))
    browser.close()
