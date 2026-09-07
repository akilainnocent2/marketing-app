# TailAdmin reference mapping

The original ZIP at `api/templates/TailAdmin-1.0.0.zip` is untouched. Its extracted source identifies package version 2.0.1 and uses React/Vite; extraction is isolated in ignored `reference/TailAdmin-1.0.0/`. `npm ci` used the original reference lockfile to run the comparison. Its dependency audit reported vulnerabilities; those demo dependencies are not in the deployed Django runtime.

| Reference | Django implementation |
|---|---|
| `tailwind.config.js`, `src/index.css` | `tailwind.config.cjs`, `assets/input.css`, compiled `tailwind.css`; full reference token palette |
| AppLayout, AppSidebar, SidebarContext, Backdrop | `base.html`, `partials/sidebar.html`, responsive shell controller |
| AppHeader, UserDropdown, ThemeToggle/ThemeContext | `partials/header.html`, persistent local theme and native account disclosure |
| Home, EcommerceMetrics, MonthlySalesChart, MonthlyTarget | `dashboard.html`: 12-column 7/5 composition, real metrics, server-rendered chart/gauge |
| ComponentCard, breadcrumb, tables, buttons, alerts/badges | shared card/list/form templates and `app.css` |
| InputField, TextArea, Select, Switch | shared field template and Django widgets; asynchronous dependent search enhancement |
| Modal and UserInfoCard | native dialog with TailAdmin 24px radius, backdrop, focus return and scrollable fields |
| AuthPageLayout and SignInForm | `auth.html`, native login/signup, split white/brand-950 composition |
| `src/icons` | locally served reference SVG set; broken angle icons replaced with valid source chevron/arrow |

Outfit is packaged locally at 400/500/600/700 weights, not dependent on Google Fonts at runtime. Input height is 44px, cards 16px radius, modal 24px radius, expanded sidebar 290px and collapsed 90px. Single sidebar breakpoint: 1024px. Primary #465FFF, hover #3641F5, background #F9FAFB, border #E4E7EC, input border #D0D5DD. MIT/OFL notices are packaged alongside assets.

Reference screenshots cover dashboard, forms, table, profile/modal and login at 1536px. Application captures cover corresponding styles and all six requested responsive widths. These are **not pixel-identical screenshots**: application-specific navigation, page headings, branding, login artwork, and data/chart compositions differ. Core measurements and palette were checked, but a full exact-fidelity acceptance audit across every module remains outstanding.
