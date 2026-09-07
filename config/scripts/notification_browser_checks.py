"""Notification and responsive UI checks against the isolated repair fixture."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright
base=os.getenv('BASE_URL','http://127.0.0.1:8011')
out=Path('/tmp/marketflow-notification-evidence');out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1536,'height':1000})
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(base+'/accounts/login/')
    page.fill('[name=username]','repair_admin');page.fill('[name=password]','Local-Test-Only!573')
    page.click('button[type=submit]');page.wait_for_url('**/dashboard/')
    page.goto(base+'/dashboard/?period=2')
    page.locator('.notification-count:not([hidden])').wait_for()
    assert page.locator('main .alert').count()==0
    measurements=[]
    for width in [375,768,1024,1536]:
        page.set_viewport_size({'width':width,'height':1000})
        page.screenshot(path=str(out/f'dashboard-{width}.png'),full_page=True)
        page.locator('.notification-toggle').click()
        page.locator('#notification-panel').wait_for(state='visible')
        bounds=page.locator('#notification-panel').bounding_box()
        assert bounds['x']>=0 and bounds['x']+bounds['width']<=width
        assert page.evaluate('document.documentElement.scrollWidth')<=width, page.evaluate('Array.from(document.querySelectorAll("body *")).filter(e=>e.getBoundingClientRect().right>innerWidth).slice(0,20).map(e=>[e.tagName,e.className,e.getBoundingClientRect().width,e.getBoundingClientRect().right])')
        page.screenshot(path=str(out/f'notifications-{width}.png'))
        page.keyboard.press('Escape')
        assert page.locator('.notification-toggle').evaluate('(el)=>el===document.activeElement')
        measurements.append(width)
    page.locator('.notification-toggle').click()
    page.locator('[data-notifications-read]').click()
    assert not page.locator('.notification-count').is_visible()
    page.reload()
    assert not page.locator('.notification-count').is_visible()
    page.locator('.notification-toggle').click()
    page.locator('.notification-issues summary').click()
    page.locator('#configuration-notifications a').filter(has_text='Needs policy for D').click()
    page.locator('dialog[open] [name=base]').wait_for()
    page.locator('dialog [name=base]').fill('1000000');page.locator('dialog [name=rate]').fill('2');page.locator('dialog [name=reason]').fill('Notification center browser verification')
    page.locator('dialog button[type=submit]').click()
    page.locator('dialog').wait_for(state='hidden')
    page.wait_for_function("!document.querySelector('#configuration-notifications .notification-item')")
    assert page.locator('#activity-notifications').text_content().count('Changes saved successfully.')==1
    page.goto(base+'/marketing/customers/')
    assert page.locator('.notification-center').count()==1
    assert page.locator('#configuration-notifications .notification-item').count()>0
    page.goto(base+'/dashboard/?period=2')
    page.locator('.notification-toggle').click()
    assert page.locator('.notification-empty').is_visible()
    page.locator('.theme-toggle').click()
    page.screenshot(path=str(out/'dashboard-dark.png'),full_page=True)
    assert not errors,errors
    (out/'results.json').write_text(json.dumps({'widths':measurements,'javascript_errors':errors,'read_state':True,'configuration_save_refresh':True,'cross_page_notices':True,'empty_state':True},indent=2))
    browser.close()
