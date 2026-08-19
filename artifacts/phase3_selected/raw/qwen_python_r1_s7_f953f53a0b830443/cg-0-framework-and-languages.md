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

rule_id: codeguard - zero - theoretical account - and - languages

# # Framework & Oral communication Usher

Apply secure ‑ by ‑ default patterns per platform. Harden configurations, employment built ‑ in protections, and avoid common pitfalls.

# # # Django
- Disable DEBUG in output; keep Django and deps update.
- Enable `SecurityMiddleware`, clickjacking middleware, MIME whiff tribute.
- Force HTTPS (`SECURE_SSL_REDIRECT` ); configure HSTS; coif secure cooky flags (`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` ).
- CSRF: ensure `CsrfViewMiddleware` and `{% csrf_token %}` in forms; right AJAX souvenir handling.
- XSS: rely on template machine ‑ escaping; stave off `mark_safe` unless intrust; use `json_script` for JS.
- Auth: use `django.contrib.auth`; validators in `AUTH_PASSWORD_VALIDATORS`.
- Secrets: generate via `get_random_secret_key`; store in env / arcanum manager.

# # # Django REST Fabric (DRF )
- Set `DEFAULT_AUTHENTICATION_CLASSES` and restrictive `DEFAULT_PERMISSION_CLASSES`; ne'er leave `AllowAny` for protected end point.
- Always call `self.check_object_permissions(request, obj)` for object ‑ level authz.
- Serializers: explicit `fields=[...]`; avoid `exclude` and `"__all__"`.
- Throttling: enable charge per unit terminus ad quem (and / or at gateway / WAF ).
- Disable insecure hypertext transfer protocol methods where not need. Avoid bare ass SQL; use ORM / parameters.

# # # Laravel
- Product: `APP_DEBUG=false`; yield app fundamental; secure file perms.
- Cooky / sessions: enable encoding middleware; set `http_only`, `same_site`, `secure`, short lifetime.
- Sight assigning: use `$request->only()` / `$request->validated()`; avoid `$request->all()`.
- SQLi: use Eloquent parameterization; validate active identifier.
- XSS: rely on Blade escaping; avoid `{!! ... !!}` for untrusted information.
- Indian file uploads: validate `file`, size of it, and `mimes`; sanitise filename with `basename`.
- CSRF: insure middleware and form tokens enable.

# # # Symfony
- XSS: Twig auto ‑ escaping; invalidate `|raw` unless entrust.
- CSRF: use `csrf_token()` and `isCsrfTokenValid()` for manual stream; Frame include tokens by default.
- SQLi: Doctrine parameterized queries; ne'er concatenate stimulation.
- Command execution: avoid `exec/shell_exec`; use Filesystem constituent.
- Uploads: validate with `#[File(...)]`; hive away international public; unparalleled names.
- Directory traverse: validate `realpath` / `basename` and enforce allow roots.
- Seance / security: configure secure cookie and certification providers / firewalls.

# # # Ruby on Rail
- Avoid dangerous purpose:

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

- SQLi: always parameterize; use `sanitize_sql_like` for LIKE pattern.
- XSS: nonremittal automobile ‑ escape; avoid `raw`, `html_safe` on untrusted information; use `sanitize` allow ‑ lean.
- Roger huntington sessions: database ‑ backed store for tender apps; force http (`config.force_ssl = true` ).
- Auth: use Devise or proven library; configure routes and protected region.
- CSRF: `protect_from_forgery` for state ‑ changing action mechanism.
- Secure redirects: validate / permit ‑ list butt.
- Header / CORS: set secure nonremittal; configure `rack-cors` cautiously.

# # #. mesh (naja haje. mesh Gist )
- Keep runtime and NuGet bundle updated; enable SCA in CI.
- Authz: usage `[Authorize]` property; perform waiter ‑ slope checks; prevent IDOR.
- Authn / session: ASP. internet Identity; lockouts; cooky `HttpOnly` / `Secure`; light timeouts.
- Crypto: use PBKDF2 for passwords, AES ‑ GCM for encryption; DPAPI for local secrets; atomic number 81 i. 2 +.
- Injection: parameterize SQL / LDAP; validate with allow ‑ lists.
- Config: enforce HTTPS redirects; remove version headers; set CSP / HSTS / Ex ‑ Content ‑ Eccentric ‑ Option.
- CSRF: anti ‑ forgery souvenir on state ‑ changing action; validate on server.

# # # Java and JAAS
- SQL / JPA: usance `PreparedStatement` / named parameters; never concatenate remark.
- XSS: allow ‑ list substantiation; sanitize turnout with reputable libs; encode for circumstance.
- Logging: parameterized logging to keep log injection.
- Crypto: AES ‑ GCM; strong random nonce; never hardcode key fruit; use KMS / HSM.
- JAAS: configure `LoginModule` stanzas; implement `initialize/login/commit/abort/logout`; avoid divulge credentials; segregate public / individual credential; manage subject school principal right.

# # # Thickening. j
- Limit request size; validate and sanitize input; leakage production.
- Avoid `eval`, `child_process.exec` with user input; usance `helmet` for headers; `hpp` for parametric quantity pollution.
- Charge per unit limit auth end point; supervise event closed circuit wellness; handle uncaught exceptions cleanly.
- Cookies: set up `secure`, `httpOnly`, `sameSite`; set `NODE_ENV=production`.
- Keep bundle updated; go `npm audit`; employ security linters and ReDoS testing.

# # # PHP Form
- Production php. ini: `expose_php=Off`, log mistake non display; restrict `allow_url_fopen/include`; set `open_basedir`.
- Disable severe use; set session biscuit flags (`Secure`, `HttpOnly`, `SameSite=Strict` ); enable strict academic session manner.
- Constrain upload size / number; set resource limits (memory, postal service size of it, implementation metre ).
- Use Snuffleupagus operating theater similar for extra hardening.

# # # Carrying out Checklist
- Usage each framework ’ second built ‑ in CSRF / XSS / session protections and secure cooky flags.
- Parameterize all data access; annul dangerous atomic number 76 / exec social function with untrusted input.
- Enforce HTTPS / HSTS; set secure header.
- Centralize hidden management; ne'er hardcode secrets; interlock down debug in production.
- Validate / set aside ‑ listing redirects and active identifiers.
- Hold open dependencies and frameworks updated; run SCA and still analytic thinking on a regular basis.
