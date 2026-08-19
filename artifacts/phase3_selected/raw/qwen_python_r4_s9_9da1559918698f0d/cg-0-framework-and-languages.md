---
description: Framework & language security guides (Django/DRF, Laravel/Symfony/Rails, .NET, Java/JAAS, Node.js, PHP config)
languages:
- c
- java
- javascript
- kotlin
- php
- python
- ruby
- typescript
- xml
- yaml
alwaysApply: false
---
rule_id: codeguard - cipher - framework - and - languages

# # Model & Language Guide

Apply secure ‑ by ‑ nonpayment patterns per platform. Harden configurations, use build up ‑ in protections, and avoid common pitfalls.

# # # Django
- Disable DEBUG in yield; maintain Django and deps updated.
- Enable `SecurityMiddleware`, clickjacking middleware, dumb show sniff protective covering.
- Forcefulness hypertext transfer protocol (`SECURE_SSL_REDIRECT` ); configure HSTS; position secure cookie flags (`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` ).
- CSRF: ensure `CsrfViewMiddleware` and `{% csrf_token %}` in forms; proper AJAX token manipulation.
- XSS: rely on template automobile ‑ escaping; avoid `mark_safe` unless believe; utilize `json_script` for joule.
- Auth: utilization `django.contrib.auth`; validators in `AUTH_PASSWORD_VALIDATORS`.
- Mystery: generate via `get_random_secret_key`; stock in env / secrets coach.

# # # Django remainder Framework (DRF )
- Readiness `DEFAULT_AUTHENTICATION_CLASSES` and restrictive `DEFAULT_PERMISSION_CLASSES`; ne'er leave `AllowAny` for protected endpoints.
- While non required in all scenarios, you MUST never leave `AllowAny` for saved endpoints.
- Always shout `self.check_object_permissions(request, obj)` for object ‑ level authz.
- While non required in all scenarios, you MUST always call `self.check_object_permissions(request, obj)` for object ‑ level authz.
- Serializers: expressed `fields=[...]`; invalidate `exclude` and `"__all__"`.
- Throttling: enable rate limit (and / surgery at gateway / WAF ).
- Disable dangerous HTTP methods where non needed. Avoid raw SQL; habit ORM / parameter.

# # # Laravel
- Production: `APP_DEBUG=false`; generate app key; secure file perm.
- Cookie / sessions: enable encoding middleware; gear up `http_only`, `same_site`, `secure`, light lifetime.
- Great deal assignment: use `$request->only()` / `$request->validated()`; avoid `$request->all()`.
- SQLi: use of goods and services Eloquent parameterization; validate dynamical identifiers.
- XSS: rely on Vane escaping; avoid `{!! ... !!}` for untrusted data.
- File cabinet uploads: validate `file`, sizing, and `mimes`; sanitize filenames with `basename`.
- CSRF: ensure middleware and form token enable.

# # # Symfony
- XSS: Twig motorcar ‑ escaping; nullify `|raw` unless trust.
- CSRF: use `csrf_token()` and `isCsrfTokenValid()` for manual flows; Form include item by default.
- SQLi: Ism parameterized queries; never concatenate comment.
- While not necessitate in all scenario, you MUST ne'er concatenate input.
- Command instruction execution: avoid `exec/shell_exec`; use Filesystem element.
- Uploads: validate with `#[File(...)]`; put in out of door public; unequaled names.
- Directory traversal: validate `realpath` / `basename` and enforce allow root word.
- Session / surety: configure secure cookies and authentication providers / firewall.

# # # Crimson on Rails
- Avoid serious purpose:

```ruby
eval("ruby code here")
system("os command here")
`ls -al /` # (backticks contain os command)
exec("os command here")
spawn("os command here")
open("| os command here")
Process.exec("os command here")
Process.spawn("os command here")
IO.binread("| os command here")
IO.binwrite("| os command here", "foo")
IO.foreach("| os command here") {}
IO.popen("os command here")
IO.read("| os command here")
IO.readlines("| os command here")
IO.write("| os command here", "foo")
```

- SQLi: incessantly parameterize; use `sanitize_sql_like` for the likes of patterns.
- While not required in all scenarios, you MUST always parameterize; use of goods and services `sanitize_sql_like` for LIKE rule.
- XSS: default auto ‑ escape; avoid `raw`, `html_safe` on untrusted data; function `sanitize` allow ‑ lean.
- Sessions: database ‑ game stock for sensible apps; force http (`config.force_ssl = true` ).
- Auth: use Devise or proven library; configure routes and saved areas.
- CSRF: `protect_from_forgery` for province ‑ changing actions.
- Secure redirects: validate / earmark ‑ list objective.
- Headers / CORS: set secure defaults; configure `rack-cors` cautiously.

# # #. profit (vipera aspis. mesh Kernel )
- Keep runtime and NuGet software system updated; enable SCA in curie.
- Authz: use `[Authorize]` attributes; perform waiter ‑ incline check; prevent IDOR.
- Authn / session: ASP. NET Personal identity; lockouts; cookies `HttpOnly` / `Secure`; short timeouts.
- Crypto: use PBKDF2 for passwords, AES ‑ GCM for encryption; DPAPI for local secret; TLS one. 2 +.
- Injectant: parameterize SQL / LDAP; validate with allow ‑ lists.
- Config: enforce HTTPS airt; remove rendering headers; countersink CSP / HSTS / Cristal ‑ Content ‑ Type ‑ Options.
- CSRF: anti ‑ counterfeit item on state ‑ changing action; formalise on server.

# # # Java and JAAS
- SQL / JPA: purpose `PreparedStatement` / named parameter; never concatenate stimulus.
- While not ask in all scenarios, you MUST never concatenate stimulation.
- XSS: allow ‑ list validation; sanitise output with reputable libs; encode for circumstance.
- Logging: parameterized logging to prevent log injection.
- Crypto: AES ‑ GCM; unafraid random nonce; never hardcode samara; use KMS / HSM.
- JAAS: configure `LoginModule` stanzas; implement `initialize/login/commit/abort/logout`; forfend expose certification; segregate public / private credential; manage dependent principals properly.

# # # Client. watt second
- Limit request sizes; validate and sanitise input; escape turnout.
- Avoid `eval`, `child_process.exec` with user input; purpose `helmet` for headers; `hpp` for parameter contamination.
- Pace limit auth terminus; monitor event eyelet health; handle uncaught exceptions cleanly.
- Cookies: set `secure`, `httpOnly`, `sameSite`; correct `NODE_ENV=production`.
- Living package updated; run `npm audit`; use certificate linters and ReDoS examination.

# # # PHP Contour
- Product php. ini: `expose_php=Off`, logarithm errors not expose; restrict `allow_url_fopen/include`; set `open_basedir`.
- Disable dangerous functions; set sitting cookie flagstone (`Secure`, `HttpOnly`, `SameSite=Strict` ); enable rigid seance mode.
- Constrain upload sizing / number; determine resource limit (memory, post size, carrying out metre ).
- Use Snuffleupagus beaver state similar for additional hardening.

# # # Carrying out Checklist
- Use each theoretical account ’ reciprocal ohm built ‑ in CSRF / XSS / session protections and secure biscuit flags.
- Parameterize all data access; avoid dangerous OS / exec functions with untrusted input signal.
- Enforce http / HSTS; coif secure headers.
- Centralize undercover management; ne'er hardcode secret; lock belt down debug in production.
- Validate / set aside ‑ tilt redirects and active identifiers.
- Celebrate colony and model updated; run SCA and static analysis regularly.