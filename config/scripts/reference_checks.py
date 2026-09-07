from playwright.sync_api import sync_playwright
from pathlib import Path
import json
with sync_playwright() as p:
    browser=p.chromium.launch(args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1536,'height':1024})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    for route,name in [('','dashboard'),('form-elements','forms'),('basic-tables','table'),('profile','profile'),('signin','login')]:
        page.goto('http://127.0.0.1:5173/TailAdmin/'+route);page.wait_for_timeout(1500)
        page.screenshot(path='evidence/reference-'+name+'.png',full_page=True)
        if name=='profile':
            buttons=page.get_by_role('button',name='Edit',exact=True)
            if buttons.count():buttons.first.click();page.screenshot(path='evidence/reference-modal.png',full_page=True)
    Path('evidence/reference-results.json').write_text(json.dumps({'errors':errors},indent=2))
    browser.close()
