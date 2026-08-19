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

### XSS Consideration of prevention (Context‑Aware)
- HTML context: `textContent` should be preferred. If HTML is required, it is recommended that it should be sanitized with a vetted library (e.g., DOMPurify) and strict allow‑lists.
- Attribute context: attributes should always be quoted and values should be encoded.
- JavaScript context: building JS from untrusted strings should be avoided; inline event handlers should be avoided; `addEventListener` should be used.
- URL context: protocol/domain should be validated and encoded; `javascript:` and data URLs should be blocked where inappropriate.
- Redirects/forwards: user input should never be used directly for destinations; server-side mapping (ID→URL) or validation against trusted domain allowlists should be used.
- CSS context: values should be allow‑listed; raw style text from users should never be injected.

Example sanitization:
```javascript
const clean = DOMPurify.sanitize(userHtml, {
  ALLOWED_TAGS: ['b','i','p','a','ul','li'],
  ALLOWED_ATTR: ['href','target','rel'],
  ALLOW_DATA_ATTR: false
});
```

### DOM‑based XSS and Dangerous Sinks
- `innerHTML`, `outerHTML`, `document.write` with untrusted data should be prohibited.
- `eval`, `new Function`, string‑based `setTimeout/Interval` should be prohibited.
- Data should be considered for validation and encoding before being assigned to `location` or event handler properties.
- Strict mode and explicit variable declarations should be used to prevent global namespace pollution from DOM clobbering.
- Trusted Types should be adopted and strict CSP should be enforced to prevent DOM sinks exploitation.

Trusted Types + CSP:
```http
Content-Security-Policy: script-src 'self' 'nonce-{random}'; object-src 'none'; base-uri 'self'; require-trusted-types-for 'script'
```

### Content Security Policy (CSP)
- Nonce‑based or hash‑based CSP should be preferred over domain allow‑lists.
- CSP should start with Report‑Only mode; violations should be collected; then enforcement should be applied.
- Baseline should aim for: `default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'self'; form-action 'self'; object-src 'none'; base-uri 'none'; upgrade-insecure-requests`.

### CSRF Defense
- XSS should be fixed first; then CSRF defenses should be layered.
- Framework‑native CSRF protections and synchronizer tokens should be used on all state‑changing requests.
- Cookie settings should be: `SameSite=Lax` or `Strict`; sessions `Secure` and `HttpOnly`; `__Host-` prefix should be used when possible.
- Origin/Referer should be considered for validation; custom headers should be required for API mutations in SPA token models.
- GET should never be used for state changes; tokens should be validated on POST/PUT/DELETE/PATCH only. HTTPS should be enforced for all token transmission.

### Clickjacking Defense
- Primary protection should be `Content-Security-Policy: frame-ancestors 'none'` or a specific allow‑list.
- Fallback for legacy browsers should be `X-Frame-Options: DENY` or `SAMEORIGIN`.
- UX confirmations for sensitive actions should be considered when framing is required.

### Cross‑Site Leaks (XS‑Leaks) Controls
- `SameSite` cookies should be used appropriately; `Strict` should be preferred for sensitive actions.
- Fetch Metadata protections should be adopted to block suspicious cross‑site requests.
- Browsing contexts should be isolated: COOP/COEP and CORP where applicable.
- Caching should be disabled and user‑unique tokens should be added for sensitive responses to prevent cache probing.

### Third‑Party JavaScript
- Minimization and isolation should be preferred: sandboxed iframes with `sandbox` and postMessage origin checks should be used.
- Subresource Integrity (SRI) should be used for external scripts and changes should be monitored.
- A first‑party, sanitized data layer should be provided; direct DOM access from tags should be denied where possible.
- Tag manager controls and vendor contracts should govern; libraries should be kept updated.

SRI example:
```html
<script src="https://cdn.vendor.com/app.js"
  integrity="sha384-..." crossorigin="anonymous"></script>
```

### HTML5, CORS, WebSockets, Storage
- `postMessage`: exact target origin should always be specified; `event.origin` should be verified on receive.
- CORS: `*` should be avoided; origins should be allow‑listed; preflights should be validated; CORS should not be relied on for authz.
- WebSockets: `wss://` should be required, origin checks, auth, message size limits, and safe JSON parsing should be used.
- Secrets should never be stored in `localStorage`/`sessionStorage`; HttpOnly cookies should be preferred; if unavoidable, isolation via Web Workers should be used.
- Links: `rel="noopener noreferrer"` should be added to external `target=_blank` links.

### HTTP Security Headers (Client Impact)
- HTTPS should be enforced everywhere with HSTS.
- `X‑Content‑Type‑Options` should be `nosniff`.
- Sensitive signals and capabilities should be restricted with Referrer‑Policy and Permissions‑Policy.

### AJAX and Safe DOM APIs
- Dynamic code execution should be avoided; function callbacks, not strings, should be used.
- JSON should be built with `JSON.stringify`; string concatenation should never be used.
- Creating elements and setting `textContent`/safe attributes should be preferred over raw HTML insertion.

### Implementation Checklist
- Contextual encoding/sanitization should be applied for every sink; dangerous APIs without guards should be avoided.
- Strict CSP with nonces and Trusted Types should be used; violations should be monitored.
- CSRF tokens should be used on all state‑changing requests; secure cookie attributes should be used.
- Frame protections should be set; XS‑Leak mitigations should be enabled (Fetch Metadata, COOP/COEP/CORP).
- Third‑party JS should be isolated with SRI and sandbox; a vetted data layer only should be used.
- HTML5/CORS/WebSocket usage should be hardened; secrets should not be stored in web storage.
- Security headers should be enabled and validated.

### Test Plan
- Automated checks should be performed for dangerous DOM/API patterns.
- E2E tests should be conducted for CSRF and clickjacking; CSP report monitoring should be performed.
- Manual probes should be conducted for XS‑Leaks (frame count, timing, cache) and open redirect behavior.