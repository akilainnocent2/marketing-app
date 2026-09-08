import subprocess
import re
from pathlib import Path
base = 'https://marketing.britishschool.ac.tz'
def fetch(path):
    return subprocess.check_output(['curl', '--fail', '--silent', '--show-error', '--location', '--max-time', '20', base + path])

for route in ['/', '/accounts/login/', '/accounts/signup/', '/dashboard/']:
    html = fetch(route).decode()
    assert '<form' in html, route
    print(route, 'OK')
    for asset in sorted(set(re.findall(r'(?:href|src)="(/static/[^"?]+)', html))):
        data = fetch(asset)
        local = Path('/var/www/marketing/static') / asset.removeprefix('/static/')
        assert data == local.read_bytes(), asset
        print('  asset verified', asset, len(data))
