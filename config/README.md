# MarketFlow

A Django multi-page marketing workspace with TailAdmin-derived styling, local Outfit fonts, Django session authentication, least-privilege signup, HTMX dialogs, and server-rendered reports. The supplied archive and the original parent `manage.py` are preserved.

## Run locally

Commands below run **from this directory (`config/`)**, alongside `settings.py`. Tested with Python 3.12 and Node 24; Node is only needed to rebuild static assets.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# Configure PostgreSQL credentials in .env before running migrations.
.venv/bin/python ../manage.py migrate
.venv/bin/python ../manage.py initialize
.venv/bin/python ../manage.py import_locations
.venv/bin/python ../manage.py createsuperuser
npm ci
npm run build
.venv/bin/python ../manage.py collectstatic --noinput
.venv/bin/python ../manage.py runserver 0.0.0.0:8000
```

Open `/accounts/login/` or `/accounts/signup/`. Signup assigns only fixed marketer capabilities; it cannot create staff, superusers, or permission administrators. Administrator-created users receive validated initial passwords through the styled Users dialog. No shared default credentials are provided. Development data, media, caches, environments, and extracted reference files are excluded from Git.

The `initialize` command creates Administrator/Marketer Django Groups only when absent, seeds expenditure types, and creates the current calendar-month period when it does not overlap an existing period. It never assigns sample commission rates or overwrites an existing group's intentional permissions. Run it after migrations because Django creates permission rows during `post_migrate`. New signup accounts receive a fixed least-privilege permission set directly, so later broadening the Marketer group cannot turn public signup into an escalation path.

## GitHub Codespaces

Run the server on `0.0.0.0:8000` using the command above, then open port 8000 from the Codespaces Ports panel. Settings automatically add the current Codespace hostname and HTTPS origin using GitHub’s environment variables, including when `.env` contains only localhost. CSRF protection stays enabled for login, forms, and AJAX requests. For another port, set `CODESPACE_APP_PORTS=8000,9000` and restart Django. Custom domains can be added to the comma-separated `ALLOWED_HOSTS` (hostnames) and `CSRF_TRUSTED_ORIGINS` (full origins including `https://`) settings.

## Business rules

The **initial configurable commission-period default is a calendar month in Africa/Dar_es_Salaam**. This is an operational starting assumption, not a confirmed business decision. Saved start/end dates are authoritative. Create future custom periods in Settings; boundaries cannot change after policy assignment. There is no automatic scheduler silently creating or remapping historical periods. A long custom period can represent cumulative operation with an explicit end date.

For each marketer and period, commission is `max(confirmed sales - base, 0) × rate / 100`, rounded to two decimal places with Decimal ROUND_HALF_UP. The threshold applies once per period. Expenses do not reduce the basis. Missing policies display “Not configured.” Confirmed sales can only be confirmed/corrected by holders of `confirm_sale`; corrections require a reason and retain before/after audit values. Deletes archive customers or void financial records. Closed commission periods block sale mutations and policy edits. Policy revisions preserve prior rates/bases.

Bulk assignment previews exactly the selected users, their existing policy values, and the replacement values. A signed, expiring preview checks the selection and policy versions again before an atomic, idempotent commit. Existing counted sales require a correction reason. No “all users” implicit selection exists.

## Routes and implementation

- `/dashboard/`: actual counts, monthly confirmed sales, expenditure, and whole-period commission cards.
- `/administration/users/`, `/administration/groups/`, `/administration/logs/`: searchable lists, user/group dialogs and a permission matrix. Logs are read-only.
- `/marketing/customers/`, `/marketing/sales/`, `/marketing/expenditures/`: scoped lists and create/detail/edit/archive/void dialogs.
- `/settings/commissions/`, `/settings/periods/`, `/settings/expenditure-types/`, `/settings/locations/`: settings dialogs; bulk assignment at `/settings/commissions/bulk/`.
- `/reports/`, `/reports/customers/`, `/reports/sales/`, `/reports/expenditures/`: report views. PDF exports at `/reports/<dataset>/pdf/`.
- `/accounts/profile/`, `/accounts/password/`: own profile and password actions. Logout is POST-only.

Navigation uses normal links; no React runtime, client router, global body swaps, or HTMX boosting. Direct form URLs work without JavaScript. HTMX requests receive fragments; validation uses an explicitly handled 422 contract. One enhancement module manages dialogs, requests, drafts, dependent locations, and downloads.

Important files: `api/models.py`, `api/migrations/`, `api/selectors.py`, `api/services.py`, `api/forms.py`, `api/views.py`, `api/pdf.py`, `api/templates/api/`, `api/static/app/app.js`, `api/static/app/app.css`, `tailwind.config.cjs`.

## Locations and drafts

The pinned MIT-licensed Mtaa 1.5 package is imported into stable local IDs; postcode metadata is excluded. The runtime was checked against Dar-es-salaam → Kinondoni → its 20 actual wards. The database contains 84,827 distinct normalized source entries, including 63,997 deepest local entries. Source coverage is not guaranteed complete or current. See `docs/MTAA-LICENSE.txt`.

Search is parent-scoped and paginated. Deliberate custom entry saves after entering custom mode, on blur/Enter/debounce; searching alone does not create records. Private custom entries are visible only to their creator and authorized administrators. Administrators can publish custom locations. A user's valid last selection and reuse preference persist separately from customer details.

Drafts are owned by the person typing, versioned, and excluded from business totals. Autosave does not upload receipt files; those upload on final submission. A consumed draft cannot be resurrected. Resuming an edit preserves the original record version. Retry tokens protect creation/finalization and bulk commits. Receipt files are validated and stored privately; only permission-checked download routes serve them.

Native selectors show at most 30 initial/selected choices; enhanced searches reach the remaining authorized options. Without JavaScript, core submissions work and deeper location is optional, but inline custom creation and full asynchronous lookup are unavailable. Pending unsaved edits require an explicit discard decision before closing.

## Reports and PDFs

Filters and selected columns are allowlisted; URLs preserve selection, and column preferences persist per user/dataset. The application distinguishes confirmed/recorded amounts from drafts and voids. Report-detail filtering never recalculates the commission threshold on a subset. Sales PDFs include a separate whole-period commission basis with eligible sales, base, excess, rate, and entitlement. Exports include all matching rows up to 5,000; narrow filters for larger outputs. Marketer cards paginate 18 per page, with earnings computed over the full authorized selection.

ReportLab generates portrait or landscape documents with embedded Outfit, repeating headers, wrapped text, and page numbering. No external URL/file fetching occurs during rendering. PDF runtime needs no browser or system renderer. TTF font source: Google Fonts `ofl/outfit`, instantiated at weight 400; the OFL license is in `api/static/app/fonts/OFL.txt`.

## Verification

```bash
.venv/bin/python ../manage.py check
.venv/bin/python ../manage.py makemigrations --check --dry-run
.venv/bin/python ../manage.py test config.api
npm run build
.venv/bin/python ../manage.py collectstatic --noinput
# Optional browser/PDF verification dependencies:
.venv/bin/pip install -r requirements-dev.lock
PLAYWRIGHT_BROWSERS_PATH=/tmp/marketing-browsers .venv/bin/playwright install --with-deps chromium
PLAYWRIGHT_BROWSERS_PATH=/tmp/marketing-browsers .venv/bin/python scripts/browser_checks.py
.venv/bin/python scripts/pdf_checks.py
```

Browser checks need a running local server and create clearly named browser verification accounts/records. Run against a disposable database (`SQLITE_PATH=/tmp/marketing-check.sqlite3`) for repeatable evaluation. PDF fixtures use a rolled-back transaction and do not persist. See `docs/VERIFICATION.md` for actual evidence and limitations.

## Deployment

Set a strong `SECRET_KEY`, `DEBUG=false`, HTTPS `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`, then collect static files. Use a production WSGI/ASGI host with the repository parent on Python's import path and target `config.wsgi:application`; do not use Django runserver in production. WhiteNoise serves static assets. Keep `private-media/` inaccessible to the web server's public file routes. Back up both the database and private media.

Secure session/CSRF cookies and HTTPS redirect turn on outside debug. Native `/admin/` is superuser-only maintenance; business models are deliberately not registered there. Auth rate limiting uses a shared filesystem cache keyed by direct peer IP and username, with a 15-minute window; deploy an edge rate limiter for distributed/high-traffic installations. No forwarded IP headers are trusted or copied to audit records by default. Audit summaries exclude passwords, tokens, phone numbers, comments, receipt contents and raw request bodies.

For SMTP, set `EMAIL_HOST`, credentials, port/TLS and `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`. This enables Django's standard token-based password-reset controls. The console email backend is development-only. No email was sent during verification.

PostgreSQL is the default database, named `marketing`, with connection settings configured through the variables in `.env.example`. The live service loads credentials from `/etc/marketing/marketing.env`. For isolated SQLite development, explicitly set `DB_ENGINE=sqlite3`. Verify concurrency/period-overlap constraints under PostgreSQL before high-concurrency use. This checkout does not claim PostgreSQL locking verification or high-concurrency production readiness. See the explicit remaining acceptance work in `docs/VERIFICATION.md`.
