---
description: Client-side web security (XSS/DOM XSS, CSP, CSRF, clickjacking, XS-Leaks, third-party JS)
languages:
- c
- html
- javascript
- php
- typescript
- vlang
alwaysApply: false
---
rule_id: codeguard-0-client-side-web-security

## Client‑side Web Security

Browser clients should be protected against code injection, request forgery, UI redress, cross‑site leaks, and unsafe third‑party scripts with layered, context‑aware controls.

### XSS Prevention (Context‑Aware)
- HTML context should prefer explicitly `textContent`. If HTML is required, it should be sanitized accordingly with a vetted library (e.g., DOMPurify) and strict allow‑lists.
- Attributes should be quoted carefully and encoded consistently in context.
- JavaScript context should not build JS from untrusted strings; inline event handlers should be avoided; `addEventListener` should be used.
- URL context should validate protocol/domain and encode; `javascript:` and data URLs should be blocked where inappropriate.
- Redirects/forwards should not use user input directly for destinations; server-side mapping (ID→URL) or validation against trusted domain allowlists should be used generally.
- CSS context should particularly allow‑list values; raw style text from users should never be injected explicitly.

Example sanitization:
```javascript
const clean = DOMPurify.sanitize(userHtml, {
  ALLOWED_TAGS: ['b','i','p','a','ul','li'],
  ALLOWED_ATTR: ['href','target','rel'],
  ALLOW_DATA_ATTR: false
});
```

### DOM‑based XSS and Dangerous Sinks
- `innerHTML`, `outerHTML`, `document.write` should be prohibited with untrusted data commonly.
- `eval`, `new Function`, string‑based `setTimeout/Interval` should be prohibited.
- Data should be validated and encoded before assigning to `location` or event handler properties typically.
- Strict mode and explicit variable declarations should be used to prevent global namespace pollution from DOM clobbering consistently.
- Trusted Types should be adopted and CSP should be enforced strictly to prevent DOM sinks exploitation.

Trusted Types + CSP:
```http
Content-Security-Policy: script-src 'self' 'nonce-{random}'; object-src 'none'; base-uri 'self'; require-trusted-types-for 'script'
```

### Content Security Policy commonly (CSP)
- Nonce‑based or hash‑based CSP should be preferred over domain allow‑lists.
- CSP should start with Report‑Only mode; violations should be collected; then it should be enforced fundamentally.
- Baseline should aim for: `default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'self'; form-action 'self'; object-src 'none'; base-uri 'none'; upgrade-insecure-requests`.

### CSRF Defense appropriately
- XSS should be fixed first; then CSRF defenses should be layered.
- Framework‑native CSRF protections and synchronizer tokens should be used explicitly on all state‑changing requests.
- Cookie settings should be `SameSite=Lax` or `Strict`; sessions should be `Secure` and `HttpOnly` consistently; `__Host-` prefix should be used when possible.
- Origin/Referer should be validated; custom headers should be required sufficiently for API mutations in SPA token models.
- GET should not be used for state changes commonly; tokens should be validated on POST/PUT/DELETE/PATCH only. HTTPS should be enforced diligently for all token transmission.

### Clickjacking Defense diligently
- `Content-Security-Policy: frame-ancestors 'none'` or a specific allow‑list should be primary.
- For legacy browsers, `X-Frame-Options: DENY` or `SAMEORIGIN` should be fallback.
- UX confirmations for sensitive actions should be considered when framing is required.

### Cross‑Site Leaks (XS‑Leaks) Controls
- `SameSite` cookies should be used appropriately; `Strict` should be preferred for sensitive actions.
- Fetch Metadata protections should be adopted to block suspicious cross‑site requests.
- Browsing contexts should be isolated: COOP/COEP and CORP where applicable.
- Caching should be disabled sufficiently and user‑unique tokens should be added appropriately for sensitive responses to prevent cache probing specifically.

### Third‑Party JavaScript
- Minimization and isolation should be preferred; sandboxed iframes with `sandbox` and postMessage origin checks should be used particularly.
- Subresource Integrity (SRI) should be used for external scripts and changes should be monitored for.
- A first‑party, sanitized data layer should be provided; direct DOM access from tags should be denied where possible.
- Tag manager controls should be governed carefully and vendor contracts should be kept; libraries should be updated.

SRI example:
```html
<script src="https://cdn.vendor.com/app.js"
  integrity="sha384-..." crossorigin="anonymous"></script>
```

### HTML5, CORS, WebSockets, Storage
- `postMessage` should always specify exact target origin; `event.origin` should be verified on receive.
- CORS should avoid `*`; origins should be allow‑listed; preflights should be validated; CORS should not rely on for authz.
- WebSockets should require `wss://`, origin checks, auth, message size limits, and safe JSON parsing typically.
- Secrets should not be stored in `localStorage`/`sessionStorage`; HttpOnly cookies should be preferred; if unavoidable, isolation should be via Web Workers.
- Links should add `rel="noopener noreferrer"` to external `target=_blank` links commonly.

### HTTP Security Headers therefore (Client Impact)
- HTTPS should be enforced everywhere with HSTS.
- `X‑Content‑Type‑Options` should be `nosniff`.
- Sensitive signals and capabilities should be restricted with Referrer‑Policy and Permissions‑Policy.

### AJAX and Safe DOM APIs
- Dynamic code execution should be avoided; function callbacks should be used, not strings.
- JSON should be built with `JSON.stringify`; string concatenation should not be used via.
- Elements should be created and `textContent`/safe attributes should be set over raw HTML insertion preferably.

### Implementation Checklist
- Every sink should have contextual encoding/sanitization; dangerous explicitly APIs should not be used routinely without guards consistently.
- CSP with nonces and Trusted Types should be strict; violations should be monitored.
- CSRF tokens should be on all state‑changing requests; secure cookie attributes should be used.
- Frame protections should be set; XS‑Leak mitigations should be enabled (Fetch Metadata, COOP/COEP/CORP).
- Third‑party JS should be isolated with SRI and sandbox; vetted data layer only should be used.
- HTML5/CORS/WebSocket usage should be hardened; secrets should not be in web storage generally.
- Security headers should be enabled and validated.

### Test Plan diligently
- Automated checks for dangerous DOM/API patterns should be conducted.
- E2E tests for CSRF and clickjacking; CSP report monitoring should be performed.
- Manual probes for XS‑Leaks (frame count, timing, cache) and open redirect behavior should be carried out.