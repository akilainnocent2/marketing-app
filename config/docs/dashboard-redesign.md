# Dashboard redesign verification

The previous dashboard delegated to the report view and shared its multi-marketer/period finance summary. That coupled the home page to selected/global rollups, historical period GET parameters, browser period propagation, performance grids, and report configuration notifications. The commission formula itself was already correct. Expenditure location filtering existed in the backend but was absent from the list columns and filter UI.

The dashboard now resolves a single authorized marketer and the configured default period on the server. Its only business filters are Marketer and Location. Ordinary marketers automatically see themselves; forged selections fail validation. Organization readers retain the existing requirement for both `view_all_reports` and `view_all_marketing`. Automatic selection prefers the current user when in the cohort, otherwise the first active cohort member in existing ordering. No active member produces an explicit empty state.

Five semantic full-card links open the existing native dialog. Sales, expenditure, and customer lists use the same query builders as their cards and paginate at 20 records. Totals cover all matching pages. Basis and commission links show concise calculation details. Direct links return full authenticated pages; HTMX returns fragments. Unauthorized model permissions remain enforced even when calling the endpoint directly. Receipt URLs are not included.

Confirmed sales, Amount After Base, and earned Commission always cover the selected marketer's complete configured period. Location scopes recorded expenditure and finalized customers, including permitted descendants through the existing five-level hierarchy. Customers and expenditure are dated within the configured period, matching the prior period-scoped dashboard semantics. A short note identifies the Location filter's effect. Location lookup responses remain capped at 30 rows; the page does not render the full location dataset.

The existing Decimal calculation remains unchanged:

```python
eligible = max(confirmed_sales - base, Decimal('0.00'))
commission = (eligible * rate / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
```

Thus 7,000,000 sales minus 3,000,000 base at 3% yields 4,000,000 eligible and 120,000 earned. Below-base sales yield zero. Expenditure never reduces commission. Detailed reporting retains its independent per-policy aggregation, historical periods, multiple-marketer scope, and PDFs.

`CommissionPeriod.is_default` is selectable in Settings and native maintenance admin. Saving a default period transactionally locks the period rows, clears the previous default, and saves the selection. A conditional unique database constraint protects against two defaults. The existing Settings audit event now includes default-status changes. `get_default_commission_period()` provides the reusable lookup; dashboard GET period values never participate in resolution.

Forward-only migration `0005_commissionperiod_is_default_and_more` adds the field, chooses an initial default without creating periods, then adds the constraint. Priority is a period containing today's local date, otherwise the newest open period, otherwise the newest available period; ties use descending primary key. Its data operation is idempotent. No periods means no default. Sales, policies, revisions, customers, expenditure, accounts, and groups are not rewritten.

Missing default shows a setup state instead of all-time totals. Authorized users can open an existing period's settings to select it, or create a period when none exists. Missing/inactive policy shows `Not configured`, with a prefilled existing policy form for authorized users or an administrator-contact message for ordinary users.

Changed files, relative to `config/api/`:

- `models.py`, `forms.py`, `admin.py`, `services.py`: default-period configuration and transactional persistence.
- `migrations/0005_commissionperiod_is_default_and_more.py`: schema, initial default selection, uniqueness constraint.
- `dashboard.py`: shared scope, queries, metrics, setup actions.
- `selectors.py`: shared permitted location descendant helper.
- `views.py`, `urls.py`: dashboard/detail routes, bounded dashboard marketer lookup, expenditure list completion, preserved report route.
- `registry.py`: expenditure Location and period default-status columns.
- `templates/api/dashboard.html`, `templates/api/dashboard_detail.html`.
- `templates/api/partials/dashboard_content.html`, `dashboard_filters.html`, `dashboard_metrics.html`, `dashboard_detail.html`, `dashboard_notifications.html`.
- `templates/api/partials/report_overview.html`: preserves the prior detailed overview for Reports.
- `templates/api/partials/list_content.html`, `notification_items.html`, `templatetags/ui.py`: location filter and dashboard-specific notifications without rebuilding organization report totals.
- `static/app/app.js`, `static/app/app.css`: asynchronous filters, period-state separation, location lookup reuse, pagination focus return, responsive cards and dialog styles.
- `test_dashboard.py`, `tests.py`: new dashboard regression coverage; detailed report expectations moved to report routes.

Verification used the existing virtual environment and the project's explicit isolated SQLite development option. The default PostgreSQL command could not start because the virtual environment lacks `psycopg`/`psycopg2`; PostgreSQL runtime and concurrent transactions were not exercised. No migration was applied to the application's existing database.

```bash
DB_ENGINE=sqlite3 config/.venv/bin/python manage.py check
DB_ENGINE=sqlite3 config/.venv/bin/python manage.py makemigrations --check --dry-run
DB_ENGINE=sqlite3 config/.venv/bin/python manage.py test config.api --noinput
node --check config/api/static/app/app.js
# From config/:
npm run build
```

Results: system check clean; no missing migrations; all 79 tests pass, including retained SSO, security, reporting/PDF, and commission administration tests; JavaScript syntax check passes; existing frontend build succeeds. The build reports an outdated Browserslist dataset, without a build failure.

The 18 new regression methods cover default switching and database uniqueness, real historical migration and fallback priority, default-period GET immunity, missing configuration, marketer selection, forged marketer/location IDs, status exclusions, Decimal rounding, expenditure independence, descendant filtering, list Location display, exact popup totals and pagination, authenticated fragment/direct routes, semantic cards, restricted readers, bounded lookups, and query counts independent of cohort size.

Chromium verification ran against `/tmp/marketflow-dashboard-visual.sqlite3`, a separate fixture database, with no JavaScript console errors. Verified administrator and ordinary users; configured and missing policies; missing default and modal setup; no sales; below/above-base sales; all five dialogs; popup totals; customer pagination; focus restoration; asynchronous marketer/location changes without document navigation; period-parameter immunity; and direct no-JavaScript navigation with forged-owner rejection. Desktop/mobile and dark mode were inspected. Widths 375, 768, 1024, 1536, and 1920 had no page-level horizontal overflow. Screenshots and JSON results are in `/tmp/marketflow-dashboard-evidence/`.

An unrelated whitespace edit appeared in `config/settings.py` during this session and was left untouched.
