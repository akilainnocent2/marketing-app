import json,uuid,time,os
from pathlib import Path
import os
BASE=os.getenv('BASE_URL','http://127.0.0.1:8000')
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser=p.chromium.launch(args=['--no-sandbox']);page=browser.new_page(viewport={'width':1280,'height':900});page.set_default_timeout(15000)
    page.on('dialog',lambda d:d.accept());page.goto(BASE+'/accounts/signup/')
    page.fill('[name=username]','failure_'+uuid.uuid4().hex[:8]);password=uuid.uuid4().hex+'!Aa9';page.fill('[name=password1]',password);page.fill('[name=password2]',password);page.click('button[type=submit]');page.wait_for_url('**/dashboard/')
    page.goto(BASE+'/marketing/customers/');page.locator('.card-heading a[data-modal]').click();page.wait_for_selector('dialog[open] [name=name]')
    page.fill('dialog [name=name]','Failure-path record');page.fill('dialog [name=phone]','0712345678');page.fill('dialog [name=comment]','Input must remain visible.');page.wait_for_function('document.querySelector(".draft-status").textContent.includes("Draft saved")')
    url='**/records/customers/add/'
    results={}
    for name,status in [('server_failure',500),('permission_denied',403),('conflict',409)]:
        page.route(url,lambda route,request,status=status:route.fulfill(status=status,body='Simulated failure'))
        page.locator('dialog button[type=submit]').first.click();page.wait_for_timeout(350)
        assert page.locator('dialog').is_visible();assert page.input_value('dialog [name=name]')=='Failure-path record';assert not page.locator('dialog button[type=submit]').first.is_disabled();results[name]=True;page.unroute(url)
    page.route(url,lambda route:route.abort())
    page.locator('dialog button[type=submit]').first.click();page.wait_for_timeout(350);assert not page.locator('dialog button[type=submit]').first.is_disabled();results['network_failure']=True;page.unroute(url)
    pending=[]
    page.route(url,lambda route:pending.append(route))
    page.locator('dialog button[type=submit]').first.click(no_wait_after=True)
    page.wait_for_timeout(300)
    assert page.locator('dialog button[type=submit]').first.is_disabled();assert page.locator('dialog .spinner').count()==1;results['slow_spinner']=True
    page.evaluate('document.querySelector("dialog form").requestSubmit()');page.wait_for_timeout(100);assert len(pending)==1;results['double_submit_blocked']=True
    response=pending[0].fetch();pending[0].fulfill(response=response)
    page.wait_for_selector('dialog',state='hidden');page.wait_for_selector('text=Failure-path record');page.unroute(url)
    # Dialog close returns focus and releases body scroll lock.
    assert page.evaluate('document.body.style.overflow')=='';results['overlay_cleanup']=True
    page.locator('.card-heading a[data-modal]').click();page.wait_for_selector('dialog[open] [name=name]')
    page.context.clear_cookies(name='sessionid');page.fill('dialog [name=name]','Expired session');page.fill('dialog [name=phone]','0712345678');page.fill('dialog [name=comment]','Session expired test');page.wait_for_timeout(1200);page.locator('dialog button[type=submit]').first.click();page.wait_for_timeout(500);assert page.locator('dialog').is_visible();assert page.input_value('dialog [name=name]')=='Expired session';assert not page.locator('dialog button[type=submit]').first.is_disabled();results['expired_session_preserves_input']=True
    (Path(os.getenv('EVIDENCE_DIR','evidence'))/'error-results.json').write_text(json.dumps(results,indent=2));print(results);browser.close()
