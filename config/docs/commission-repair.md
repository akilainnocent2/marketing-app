# Sales and commission repair

The arithmetic was already correct. The failures were integration defects: dashboard financial totals were computed before marketer filtering, financial measures used incompatible dates, a single missing policy erased known earnings, active login accounts were treated as marketers, PDF cohorts came from narrowed detail rows, and dashboard saves fell back to a document reload.

## Implementation

`api/reporting.py` builds one authorized, validated saved-period context. Confirmed sales are grouped once by owner, policies are loaded together, and `calculate_commission()` calculates each marketer before selected/global aggregation. The global scope ignores only marketer selection. Totals and cohort counts precede card pagination.

The business cohort includes active members of the seeded Marketer group, non-administrative custom add-customer designations, relevant sale owners (including inactive owners), and assigned policy holders. Generic Administrator-group membership or superuser status alone does not designate a marketer. Organization reports still require both `view_all_reports` and `view_all_marketing`, plus report and dataset permissions. Assignment autocomplete retains its separate write permissions; report autocomplete is authenticated, independently scoped, and paginated to 30 results.

URLs accept repeated `marketer` parameters, deduplicate IDs, and reject invalid/out-of-scope selections. No marketer filter means all permitted marketers; an explicitly empty marketer parameter means an empty scope. The bounded chooser also supports explicit `selection=all`, preventing its first 30 options from truncating an all-marketer report. Invalid IDs are rejected even in this mode. A selected saved period remains the financial basis; arbitrary date/search/status/amount filters narrow only the labeled detail subtotal. One saved period is supported per financial context; there is no partial-period allocation or pooled-base calculation.

Shared summary and marketer partials serve the home/dashboard routes, reports overview, Sales list, and Sales report. They distinguish assigned thresholds, sales covered by bases, per-user excess, known commission subtotals, missing/inactive policies, zero rates, common/mixed rates, and effective rates on configured excess. The PDF uses the same authorized context even when detail search returns no rows.

Configuration actions use model permissions plus `manage_commissions`. Policy popups prefill validated context, route inactive/existing policies to their existing edit IDs, and preview actual server-side confirmed sales. Single-policy optimistic versions and operation tokens protect edits/retries. Bulk preview includes before/after excess and commission, retains signed previews, and rechecks policy versions under transaction locks before applying all changes. Period creation also carries an idempotency token and a new-period event for setup continuation. Existing ledger/audit/revision models remain in use.

Dashboard/report/list regions refresh atomically through fetch; forms retain the existing HTMX dialog lifecycle. Explicit filters, sorting, pagination, and preferences preserve query parameters. Requests are sequenced/cancelled, module links remain normal Django navigation, history restoration distinguishes full pages and fragments, and stale modal responses cannot replace newer dialogs. Expired AJAX authentication returns 401 instead of redirecting away from entered values. Only the active submit button enters its loading state.

The current checkout already permitted overlapping saved periods and had related tests before this repair. That pre-existing behavior was retained, as were assigned-boundary protections and closed-period rules. No schema migration was added. Existing records, the four modules, TailAdmin layout, Outfit assets, theme colors, and reference ZIP were not reset or reseeded.

## Regression results

All values below were asserted through rendered Django endpoints; PDF extraction also checks selected/global parity with no matching detail rows.

| Scope | Confirmed sales (TZS) | Above bases (TZS) | Commission (TZS) | Rate |
|---|---:|---:|---:|---|
| A | 7,000,000.00 | 4,000,000.00 | 120,000.00 | Configured 3% |
| A+B | 9,000,000.00 | 4,000,000.00 | 120,000.00 | Mixed policies; effective 3% |
| A+B+C | 17,000,000.00 | 10,000,000.00 | 420,000.00 | Mixed policies; effective 4.20% |
| A+B+C+D, D missing policy | 21,000,000.00 | 10,000,000.00 configured | 420,000.00 known subtotal | Complete total pending |
| A+B+C+D, D base 1,000,000 / rate 2% | 21,000,000.00 | 13,000,000.00 | 480,000.00 | Complete |

A's displayed calculation is `(7,000,000.00 − 3,000,000.00) × 3% = 120,000.00 TZS`. For A+B+C, assigned thresholds total TZS 8,000,000.00 while sales covered by bases total TZS 7,000,000.00. B's unused threshold never reduces A or C's commission.

Fresh verification on 7 September 2026:

- `.venv/bin/python ../manage.py test api --noinput`: **44 tests passed**. Coverage includes the existing helper/status/permission/draft/bulk/closed-period tests plus aggregate scopes, partial configuration, inactive historical owners, administrative cohort exclusion, empty/invalid/multiple selections, read-only global reporters, >18-card pagination, bounded chooser/all-scope behavior, hidden repeated filters, stale policy edits, policy/period retry idempotency, bulk preview changes, PDF zero-detail parity, non-sales readers, query growth, and expired AJAX sessions.
- `npm run build`, `collectstatic --noinput`, Django system checks, JavaScript syntax checks, and `git diff --check`: passed. `makemigrations --check --dry-run`: no changes. Tailwind emits its existing outdated Browserslist-data advisory; the build succeeds.
- `scripts/repair_browser_checks.py`: fresh 375, 768, 1024, and 1536 px checks, dark theme, zero-rate/partial states, open policy and bulk dialogs, selected/global filtering, browser back, policy setup, bulk preview/apply, and sorting. Recorded financial action requests contain **no document navigation**. D's policy setup changes the displayed known TZS 420,000.00 subtotal to TZS 480,000.00 through AJAX.
- `scripts/repair_navigation_checks.py`: card/table pagination, repeated marketers and columns, detail filtering without changing commission, delayed older response rejection, and ordinary module document navigation passed.
- `scripts/browser_checks.py`: signup/login, responsive layout, modal CRUD, retained validation input, and no-JavaScript form fallback passed.
- `scripts/error_checks.py`: simulated 500/403/409, network failure, loading-button restoration, duplicate-submit prevention, overlay cleanup, and expired-session input preservation passed.
- `scripts/pdf_checks.py`: fresh wide (26 pages), portrait (7 pages), and empty-detail (1 page) PDFs passed text/last-row/font checks; Outfit is embedded. This separate fixture asserts TZS 90,000.00 commission on TZS 6,000,000.00 sales. The endpoint tests above assert the requested TZS 120,000.00 and TZS 420,000.00 cases.

Evidence lives in `evidence/repair-2026-09-07/`, including `finance-browser-results.json`, `navigation-results.json`, `browser-results.json`, `error-results.json`, `pdf-results.json`, screenshots, and PDFs. These are new runs, not the supplied historical evidence. Browser fixtures include extra zero-sale configured marketers and draft rows to exercise pagination without changing the financial examples.

## Reproduction and limits

Use the checkout's virtual environment. Browser dependencies and Chromium were available after installing Chromium into `/tmp/marketflow-browsers`. For a fresh browser fixture, set `SQLITE_PATH=/tmp/marketflow-repair-<unique>.sqlite3` and run `scripts/repair_fixture.py`, then start Django using that same `SQLITE_PATH`. The fixture refuses an existing populated database. Browser scripts accept `BASE_URL`; the final run used `http://127.0.0.1:8002`. Run the financial and navigation scripts before the generic signup/CRUD scripts. The generic scripts accept `EVIDENCE_DIR`. The existing application `db.sqlite3` was not used for browser writes.

For production assets run `npm run build` and `.venv/bin/python ../manage.py collectstatic --noinput`. There is no new migration command beyond the application's normal deployment procedure.

Browser verification used Chromium. Cross-browser runs and multi-worker production contention/load testing were not performed. The transactional/version checks were exercised on SQLite; the browser race check covers stale report responses, not a database load benchmark. This repair deliberately supports one whole saved financial period at a time and preserves the checkout's existing overlap behavior.
