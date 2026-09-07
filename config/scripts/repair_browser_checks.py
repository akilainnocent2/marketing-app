"""Fresh financial/fragment evidence. Run only against the isolated repair fixture DB."""
import json
from pathlib import Path
import os
BASE=os.getenv('BASE_URL','http://127.0.0.1:8000')
from playwright.sync_api import sync_playwright
OUT=Path('evidence/repair-2026-09-07');OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1536,'height':1024});page.set_default_timeout(15000)
    errors=[];requests=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:requests.append({'url':r.url,'method':r.method,'type':r.resource_type,'navigation':r.is_navigation_request()}))
    page.goto(BASE+'/accounts/login/')
    page.fill('[name=username]','repair_admin');page.fill('[name=password]','Local-Test-Only!573');page.click('button[type=submit]');page.wait_for_url('**/dashboard/')
    page.goto(BASE+'/dashboard/?period=2')
    page.wait_for_selector('text=TZS 420,000.00');page.wait_for_function('document.fonts.check("14px Outfit")')
    measurements=[]
    for width in [375,768,1024,1536]:
        page.set_viewport_size({'width':width,'height':1000})
        page.wait_for_timeout(350)
        page.screenshot(path=str(OUT/f'finance-{width}.png'),full_page=True)
        page.screenshot(path=str(OUT/f'finance-viewport-{width}.png'))
        dimensions=page.evaluate('({width:innerWidth,scrollWidth:document.documentElement.scrollWidth})');measurements.append(dimensions);assert dimensions['scrollWidth']<=width,dimensions
    page.click('.theme-toggle');page.screenshot(path=str(OUT/'finance-dark.png'),full_page=True);page.click('.theme-toggle')
    start=len(requests)
    page.locator('.marketer-picker summary').click()
    page.select_option('[data-report-filter] select[name=marketer]',label='A')
    page.locator('[data-report-filter] button').filter(has_text='Apply').click()
    page.wait_for_function("document.querySelector('.finance-summary dd').textContent.includes('TZS 7,000,000.00')")
    assert 'TZS 420,000.00' in page.locator('.finance-summary').nth(1).inner_text()
    assert '3%' in page.locator('.finance-summary').first.inner_text()
    page.locator('.marketer-picker summary').click()
    page.select_option('[data-report-filter] select[name=marketer]',label=['A','B'])
    page.locator('[data-report-filter] button').filter(has_text='Apply').click()
    page.wait_for_timeout(500)
    page.wait_for_function("document.querySelector('.finance-summary dd').textContent.includes('TZS 9,000,000.00')")
    page.go_back();page.wait_for_function("document.querySelector('.finance-summary dd').textContent.includes('TZS 7,000,000.00')")
    page.locator('a[data-region-link]').filter(has_text='Reset marketers').click()
    page.wait_for_selector('.marketer-card a:has-text("Needs policy for D")')
    page.locator('.marketer-card a').filter(has_text='Needs policy for D').click();page.wait_for_selector('dialog[open] [name=base]')
    page.wait_for_function("document.querySelector('.policy-preview').textContent.includes('4,000,000.00')")
    for width in [375,768,1024,1536]:
        page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(350);page.screenshot(path=str(OUT/f'policy-modal-{width}.png'))
    page.fill('dialog [name=base]','1000000');page.fill('dialog [name=rate]','2');page.fill('dialog [name=reason]','Approved regression setup')
    page.wait_for_function("document.querySelector('.policy-preview').textContent.includes('60,000.00')")
    page.locator('dialog button[type=submit]').click();page.wait_for_selector('dialog',state='hidden')
    page.wait_for_selector('text=TZS 480,000.00')
    action_requests=requests[start:];assert not any(r['navigation'] for r in action_requests),action_requests
    page.goto(BASE+'/marketing/sales/?period=2&marketer=2&marketer=3')
    page.wait_for_selector('.list-card');start=len(requests)
    page.locator('th a[data-region-link]').first.click();page.wait_for_function("location.search.includes('sort=')")
    assert len(page.locator('html').all())==1
    assert not any(r['navigation'] for r in requests[start:])
    # Bulk shared popup, exact selected target, signed preview, apply.
    page.goto(BASE+'/settings/commissions/')
    page.locator('a[data-modal]').filter(has_text='Bulk assignment').click();page.wait_for_selector('dialog [name=marketers]')
    page.select_option('dialog [name=marketers]',label='A');page.select_option('dialog [name=period]',label='Repair January')
    page.fill('dialog [name=base]','3000000');page.fill('dialog [name=rate]','3');page.fill('dialog [name=reason]','Regression bulk review')
    start=len(requests);page.locator('dialog button[type=submit]').click();page.wait_for_selector('dialog [name=commit]')
    page.set_viewport_size({'width':375,'height':900});page.screenshot(path=str(OUT/'bulk-mobile.png'),full_page=True)
    page.locator('dialog [name=commit]').click();page.wait_for_selector('dialog',state='hidden')
    assert not any(r['navigation'] for r in requests[start:])
    assert not errors,errors
    (OUT/'finance-browser-results.json').write_text(json.dumps({'measurements':measurements,'javascript_errors':errors,'financial_action_requests':action_requests,'selected_global':True,'policy_setup_no_navigation':True,'bulk_no_navigation':True,'sort_no_navigation':True,'back_forward':True},indent=2))
    browser.close()
