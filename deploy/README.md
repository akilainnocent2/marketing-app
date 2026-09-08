# Marketing VPS deployment

Live URL: https://marketing.britishschool.ac.tz

- Unit: `marketing.service`, enabled at boot; Gunicorn binds to `127.0.0.1:8117`.
- Code: `/root/myapps/marketing-app`, mounted read-only at `/opt/marketing` for the service.
- Python: app-local `.venv`; no system Python or database upgrades.
- Settings: `config.production`; secrets: `/etc/marketing/marketing.env` (root-only).
- PostgreSQL database and role: `marketing`. Migrations and initialization completed.
- Public static files: `/var/www/marketing/static`, served by Nginx.
- Private media/cache: `/var/lib/marketing`, managed by the service.
- Nginx site: `/etc/nginx/sites-available/marketing`.
- Certificate: `/etc/letsencrypt/live/marketing.britishschool.ac.tz`.
- Renewal: existing `certbot.timer`; marketing-specific deploy hook reloads Nginx after renewal.

Verified public HTTPS, origin HTTPS, HTTP redirect, login/signup pages, unauthenticated dashboard redirect, exact CSS/JS content, completed migrations, and stable service. Authenticated business workflows were not exercised. No administrator account was created during deployment.

`verify.py` checks public pages and compares referenced static assets with deployed files. Run with `.venv/bin/python deploy/verify.py`.

`install.sh` is for an initial installation only. `finish-install.sh` was used to resume the partial installation; it is not an idempotent updater and should not be rerun on this completed deployment.

Changes were scoped to marketing. Other applications, databases, and virtual environments were not modified. Shared Nginx was configuration-tested and gracefully reloaded.
