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
rule_id: codeguard-0-framework-and-languages

## Framework & Language Guides

Secure‑by‑default patterns per platform should be applied. Configurations should be hardened, built‑in protections should be used, and common pitfalls should be avoided.

### Django
- DEBUG should be disabled in production; Django and deps should be kept updated.
- `SecurityMiddleware`, clickjacking middleware, and MIME sniffing protection should be enabled.
- HTTPS should be forced (`SECURE_SSL_REDIRECT`); HSTS should be configured; secure cookie flags (`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`) should be set.
- `CsrfViewMiddleware` and `{% csrf_token %}` in forms should be ensured; proper AJAX token handling should be done.
- Template auto‑escaping should be relied upon; `mark_safe` should be avoided unless trusted; `json_script` for JS should be used.
- `django.contrib.auth` should be used; validators in `AUTH_PASSWORD_VALIDATORS` should be included.
- Secrets should be generated via `get_random_secret_key`; they should be stored in env/secrets manager.

### Django REST Framework (DRF)
- `DEFAULT_AUTHENTICATION_CLASSES` and restrictive `DEFAULT_PERMISSION_CLASSES` should be set; `AllowAny` should never be left for protected endpoints.
- `self.check_object_permissions(request, obj)` should always be called for object‑level authz.
- Explicit `fields=[...]` should be used in serializers; `exclude` and `"__all__"` should be avoided.
- Rate limits (and/or at gateway/WAF) should be enabled for throttling.
- Unsafe HTTP methods should be disabled where not needed. Raw SQL should be avoided; ORM/parameters should be used.

### Laravel
- `APP_DEBUG=false` should be set in production; an app key should be generated; secure file perms should be secured.
- Encryption middleware should be enabled for cookies/sessions; `http_only`, `same_site`, `secure`, and short lifetimes should be set.
- `$request->only()` / `$request->validated()` should be used for mass assignment; `$request->all()` should be avoided.
- Eloquent parameterization should be used for SQLi; dynamic identifiers should be validated.
- Blade escaping should be relied upon for XSS; `{!! ... !!}` should be avoided for untrusted data.
- File uploads should be validated with `file`, size, and `mimes`; filenames should be sanitized with `basename`.
- Middleware and form tokens should be ensured for CSRF.

### Symfony
- Twig auto‑escaping should be relied upon for XSS; `|raw` should be avoided unless trusted.
- `csrf_token()` and `isCsrfTokenValid()` should be used for manual CSRF flows; Forms should include tokens by default.
- Doctrine parameterized queries should be used for SQLi; inputs should never be concatenated.
- `exec/shell_exec` should be avoided for command execution; the Filesystem component should be used.
- Uploads should be validated with `#[File(...)]`; they should be stored outside public; unique names should be used.
- `realpath`/`basename` and allowed roots should be validated and enforced for directory traversal.
- Secure cookies and authentication providers/firewalls should be configured for sessions/security.

### Ruby on Rails
- Dangerous functions should be avoided:

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

- SQLi should be parameterized; `sanitize_sql_like` should be used for LIKE patterns.
- Default auto‑escape should be relied upon for XSS; `raw`, `html_safe` on untrusted data should be avoided; `sanitize` allow‑lists should be used.
- Database‑backed store should be used for sessions in sensitive apps; HTTPS should be forced (`config.force_ssl = true`).
- Devise or proven libraries should be used for Auth; routes and protected areas should be configured.
- `protect_from_forgery` should be used for state‑changing actions for CSRF.
- Targets should be validated/allow‑listed for secure redirects.
- Secure defaults should be set for headers/CORS; `rack-cors` should be configured carefully.

### .NET (ASP.NET Core)
- Runtime and NuGet packages should be kept updated; SCA should be enabled in CI.
- `[Authorize]` attributes should be used for Authz; server‑side checks should be performed; IDOR should be prevented.
- ASP.NET Identity should be used for Authn/sessions; lockouts should be configured; cookies `HttpOnly`/`Secure` should be set; short timeouts should be used.
- PBKDF2 should be used for passwords, AES‑GCM for encryption; DPAPI should be used for local secrets; TLS 1.2+ should be used for Crypto.
- SQL/LDAP should be parameterized for Injection; allow‑lists should be used for validation.
- HTTPS redirects should be enforced for Config; version headers should be removed; CSP/HSTS/X‑Content‑Type‑Options should be set.
- Anti‑forgery tokens should be used on state‑changing actions for CSRF; validation should be done on server.

### Java and JAAS
- `PreparedStatement`/named parameters should be used for SQL/JPA; input should never be concatenated.
- Allow‑list validation should be used for XSS; output should be sanitized with reputable libs; encoding for context should be done.
- Parameterized logging should be used for Logging to prevent log injection.
- AES‑GCM should be used for Crypto; secure random nonces should be used; keys should never be hardcoded; KMS/HSM should be used.
- `LoginModule` stanzas should be configured for JAAS; `initialize/login/commit/abort/logout` should be implemented; credentials should be avoided from being exposed; public/private credentials should be segregated; subject principals should be managed properly.

### Node.js
- Request sizes should be limited; input should be validated and sanitized; output should be escaped.
- `eval`, `child_process.exec` with user input should be avoided; `helmet` should be used for headers; `hpp` should be used for parameter pollution.
- Auth endpoints should be rate limited; event loop health should be monitored; uncaught exceptions should be handled cleanly.
- Cookies should have `secure`, `httpOnly`, `sameSite` set; `NODE_ENV=production` should be set.
- Packages should be kept updated; `npm audit` should be run; security linters and ReDoS testing should be used.

### PHP Configuration
- `expose_php=Off`, log errors not display; `allow_url_fopen/include` should be restricted; `open_basedir` should be set for Production php.ini.
- Dangerous functions should be disabled; session cookie flags (`Secure`, `HttpOnly`, `SameSite=Strict`) should be set; strict session mode should be enabled.
- Upload size/number should be constrained; resource limits (memory, post size, execution time) should be set.
- Snuffleupagus or similar should be used for additional hardening.

### Implementation Checklist
- Each framework’s built‑in CSRF/XSS/session protections and secure cookie flags should be used.
- All data access should be parameterized; dangerous OS/exec functions with untrusted input should be avoided.
- HTTPS/HSTS should be enforced; secure headers should be set.
- Secret management should be centralized; secrets should never be hardcoded; debug should be locked down in production.
- Redirects and dynamic identifiers should be validated/allow‑listed.
- Dependencies and frameworks should be kept updated; SCA and static analysis should be run regularly.