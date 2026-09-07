"""Run against a development server; creates a temporary least-privilege signup user."""
import json,uuid,os
from pathlib import Path
import os
BASE=os.getenv('BASE_URL','http://127.0.0.1:8000')
from playwright.sync_api import sync_playwright
OUT=Path(os.getenv('EVIDENCE_DIR','evidence'));OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1536,'height':1024})
    page.set_default_timeout(15000);page.on('dialog',lambda d:d.accept())
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(BASE+'/accounts/login/');page.screenshot(path=str(OUT/'login-1536.png'),full_page=True)
    page.goto(BASE+'/accounts/signup/')
    user='browser_'+uuid.uuid4().hex[:8]
    page.fill('[name=username]',user);page.fill('[name=first_name]','Amani');page.fill('[name=last_name]','Mwakalinga')
    page.fill('[name=password1]','Browser-Only!'+uuid.uuid4().hex);password=page.input_value('[name=password1]');page.fill('[name=password2]',password)
    page.locator('button[type=submit]').click();page.wait_for_url('**/dashboard/')
    page.wait_for_function('document.fonts.check("14px Outfit")');page.screenshot(path=str(OUT/'dashboard-1536.png'),full_page=True)
    measures=[]
    for width in [375,768,991,1024,1280,1536]:
        page.set_viewport_size({'width':width,'height':1000});page.reload();page.wait_for_timeout(200)
        m=page.evaluate('''() => ({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,font:getComputedStyle(document.body).fontFamily,sidebar:getComputedStyle(document.querySelector('.sidebar')).width,background:getComputedStyle(document.body).backgroundColor})''');measures.append(m)
        assert m['scrollWidth']<=width, m
        if width<1024:
            page.click('#sidebar-toggle');assert page.locator('body').evaluate('(el)=>el.classList.contains("sidebar-open")');page.click('.sidebar-backdrop',position={'x':width-10,'y':500})
        page.screenshot(path=str(OUT/f'dashboard-{width}.png'),full_page=True)
    page.goto(BASE+'/marketing/customers/');page.locator('.card-heading a[data-modal]').click();page.wait_for_selector('dialog[open] [name=name]')
    page.screenshot(path=str(OUT/'customer-modal.png'),full_page=True)
    page.fill('dialog [name=name]','Browser customer');page.fill('dialog [name=phone]','0712345678');page.fill('dialog [name=comment]','A browser verification record.')
    page.wait_for_function('document.querySelector(".draft-status").textContent.includes("Draft saved")')
    page.locator('dialog button[type=submit]').first.click();page.wait_for_selector('dialog',state='hidden');page.wait_for_selector('text=Browser customer')
    page.locator('.card-heading a[data-modal]').click();page.wait_for_selector('dialog[open] [name=name]');page.fill('dialog [name=name]','Invalid phone');page.fill('dialog [name=phone]','000');page.fill('dialog [name=comment]','Validation check');page.wait_for_timeout(1500);page.locator('dialog button[type=submit]').first.click();page.wait_for_selector('.field-error');assert page.locator('dialog').is_visible();assert page.input_value('dialog [name=name]')=='Invalid phone';page.screenshot(path=str(OUT/'validation-error.png'),full_page=True)
    page.click('.modal-close')
    page.goto(BASE+'/marketing/sales/');page.screenshot(path=str(OUT/'sales-list.png'),full_page=True)
    page.click('.theme-toggle');page.screenshot(path=str(OUT/'sales-dark.png'),full_page=True)
    # Native login and a no-JS form submission remain usable.
    print('Enhanced checks complete',flush=True)
    native=browser.new_page(java_script_enabled=False);native.set_default_timeout(15000)
    native.goto(BASE+'/accounts/login/');native.fill('[name=username]',user);native.fill('[name=password]',password);native.click('button[type=submit]');native.wait_for_url('**/dashboard/')
    native.goto(BASE+'/records/customers/add/');native.fill('[name=name]','No JavaScript');native.fill('[name=phone]','0612345678');native.fill('[name=comment]','Native POST');native.locator('.record-form button[type=submit]').first.click();native.wait_for_url('**/marketing/customers/');assert native.get_by_text('No JavaScript',exact=True).count()>0
    (OUT/'browser-results.json').write_text(json.dumps({'measurements':measures,'javascript_errors':errors,'signup_login':True,'modal_create':True,'validation_preserved':True,'native_post':True},indent=2));assert not errors,errors
    browser.close()
