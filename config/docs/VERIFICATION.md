# Verification record

Actual checks performed in this environment (7 September 2026):

- Django application checks and migrations applied successfully. Three application migrations; no pending model changes.
- 25 Django tests passed. Tests cover the four commission examples, accumulation, void/draft exclusion, zero base and half-up rounding, cross-user access/filters/drafts/receipts, assignment forgery, native POST/CSRF, duplicate creates, stale draft/record versions, grant escalation, staff restriction, closed periods, policy revision reasons, overlapping periods, signed bulk preview tampering/commit/retry, report scope, deactivation/revocation, and POST logout.
- Tailwind 3.4.17 compiled from the normalized source config; static collection succeeded. Node syntax check of the shared enhancement script passed. Production assets and local fonts are committed.
- Mtaa 1.5 runtime hierarchy inspected and imported twice. Final distinct source count: 84,827. Kinondoni's 20 actual ward names verified; postcode metadata is absent from imported choices.
- Real Chromium browser checks: signup, login, dashboard, customer dialog create, autosave, validation error/input preservation, dark theme, full-page navigation, and no-JavaScript login/customer POST. No JavaScript page errors in the successful run.
- Dashboard widths: 375, 768, 991, 1024, 1280, 1536 px. Document scroll width matched viewport at every width. Outfit loaded; sidebar measured 290px and background #F9FAFB. Mobile sidebar open/close checked below 1024px.
- Real browser failure checks passed for 500/403/409 responses, aborted network requests, delayed-response spinner/muting, duplicate Enter-style submissions, overlay cleanup, and expired-session redirect. See `evidence/error-results.json`.
- Reference demo ran from its lockfile; captured dashboard, form elements, basic table, profile/modal and signin. `evidence/reference-results.json` recorded no page errors.
- PDFs generated with 120 records: portrait (6 pages), wide long-description (25 pages), and empty (1 page). Checked embedded Outfit, page numbers, last row inclusion and TZS 90,000 whole-period commission. First/last pages rasterized; first pages visually inspected for wrapping and margins. Fixtures roll back.

Evidence lives in `evidence/`: `browser-results.json`, responsive screenshots, reference screenshots, PDF documents, page rasterizations and `pdf-results.json`. Browser fixtures are explicitly created by `scripts/browser_checks.py`; use a disposable development database when running it yourself.

## Remaining acceptance work / limitations

This is a working implementation, **not completion of every item in the supplied acceptance matrix**:

- Exact pixel fidelity has not passed. TailAdmin tokens, font, shell dimensions, core controls and 7/5 composition are ported, but application-specific layout, branding, login illustration and chart composition differ. Responsive overflow checks focus on the dashboard; every module/dialog at every width is not exhaustively verified.
- No PostgreSQL concurrency suite or database-level period exclusion constraint. Transactions, uniqueness and versions are implemented and tested sequentially on SQLite. Concurrent write stress, cross-process draft CAS/idempotency and overlapping period creation need production-database verification/hardening.
- Settings support custom-location publication and type/location activation, but not full recursive merge workflows. There is no separate business-preferences editor, recurring policy scheduler, open-ended period model, or explicit record-ownership reassignment workflow.
- Search endpoints are paginated, but enhanced dropdown UI currently shows the first 30 matches; refine search for later results. There is no “select all filtered marketers” bulk workflow. Bulk selection is explicit, and never silently means all users.
- Reports provide overview/performance cards, dataset detail, date/search/status/amount/potential/period filters, columns and PDF. Not all requested advanced filters have dedicated controls; some allowlisted filters are URL-only. No complete trend/comparison chart suite, expenditure-by-type visualization, partial-period chronological commission allocation, or separate performance PDF screen. Whole-period commission is included in sales PDFs.
- Automatic validation is strongest at final Django form validation, with phone blur validation and draft persistence; not every field has a separate prevalidation endpoint. Receipt draft uploads are intentionally deferred until final submit. Closing unsaved data offers discard/cancel plus in-form retry, not a three-way keep/discard/retry dialog.
- Draft restoration covers latest owner/form/target draft; there is no multi-draft chooser. Optimistic versions reject stale saves, but conflict reconciliation is reopen/resume, not field-by-field merging.
- SMTP/password-reset delivery, real reverse-proxy deployments, multi-worker rate-limit behavior, and exhaustive timeout/error-path browser coverage are not verified. Representative session expiry, network, permission, conflict and server-error paths passed. No production deployment was performed.

These are material follow-up items before claiming full acceptance or production readiness. Do not interpret a passing `manage.py check`, browser smoke test, or the appearance of a screen as evidence that these remaining cases passed.
