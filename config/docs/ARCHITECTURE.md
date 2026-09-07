# Architecture and permissions

`registry.py` is an explicit dataset/field/form map, not arbitrary ORM dispatch. `selectors.py` owns row scopes and eligible users; `forms.py` owns validation and grant ceilings; `services.py` owns commission calculation, revisions and audit writes. `views.py` coordinates authorized transactions. There is one Django app label, `api`, at `config.api`.

| Capability | Default Administrator | Default Marketer / signup |
|---|---|---|
| Customer CRUD | All with action permission plus scope | Own records |
| Sales draft CRUD | All with action permission plus scope | Own drafts |
| Confirm/correct confirmed sales | `api.confirm_sale` | No |
| Record/correct/void expenditure | All with action permission plus scope | Own |
| Commission policies and periods | `api.manage_commissions` plus model action | Own assigned policy view |
| Organization records | `api.view_all_marketing`, `api.manage_all_marketing` | No |
| Ownership selection | `api.assign_marketer` plus manage-all | Server-assigned self |
| Reports | `api.view_reports` + model view | Own |
| Organization reports | `api.view_all_reports` + view-all-marketing + model view | No |
| PDF | `api.export_reports` + report/model view | Own |
| Audit logs | `api.view_auditlog` | No |
| User/group grants | Django auth action permissions, actor's grant ceiling | No |
| Native admin / superuser editing | Superuser only | No |

Group names seed policy but never authorize a route. `is_staff` alone grants no business access. Non-superusers cannot assign permissions or groups outside their existing effective ceiling, edit staff/stronger accounts, or modify groups that already exceed that ceiling. The last active superuser cannot be deactivated/deleted. Native model permission rows remain Django-owned.

Sales and customer IDs are always obtained through an authorized queryset before mutation. A sale's customer must share its marketer. Existing ownership changes are rejected rather than silently reassigning historical records. Financial/history references use PROTECT. Audit history has view-only model permissions and no edit/delete application route.

Django sessions, CSRF, password APIs, local next redirect validation, and login/logout/failure signals are retained. Source references: [Django authentication](https://docs.djangoproject.com/en/5.2/topics/auth/default/) and [ModelBackend](https://docs.djangoproject.com/en/5.2/ref/contrib/auth/#django.contrib.auth.backends.ModelBackend). Django 5.2.17 LTS was selected from the [supported releases](https://www.djangoproject.com/download/) on 7 September 2026.
