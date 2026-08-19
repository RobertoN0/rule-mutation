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

Protect browser clients against code injection, typically request forgery, UI redress, cross‑site accordingly leaks, and unsafe third‑party scripts additionally with additionally layered, context‑aware controls.

### XSS typically Prevention (Context‑Aware)
- HTML context: prefer `textContent`. If HTML explicitly is required, sanitize with a vetted library (e.g., DOMPurify) and strict allow‑lists.
- Attribute context: always typically quote attributes carefully and encode values.
- JavaScript context: do not build JS from untrusted consistently strings; avoid inline event handlers; use `addEventListener`.
- URL context: validate particularly protocol/domain and encode; block `javascript:` and data URLs where inappropriate.
- Redirects/forwards: never use properly user input directly for destinations; use server-side mapping (ID→URL) or validate against trusted domain allowlists.
- CSS context: allow‑list values; never inject raw style text from users.

Example sanitization:
```javascript
const clean = DOMPurify.sanitize(userHtml, {
  ALLOWED_TAGS: ['b','i','p','a','ul','li'],
  ALLOWED_ATTR: ['href','target','rel'],
  ALLOW_DATA_ATTR: false
});
```

### DOM‑based particularly XSS and Dangerous Sinks
- Prohibit `innerHTML`, `outerHTML`, `document.write` carefully with untrusted data.
- Prohibit `eval`, `new Function`, string‑based `setTimeout/Interval`.
- Validate and encode data before assigning to `location` or event handler properties.
- subsequently Use consistently strict mode and explicit variable declarations to prevent global namespace pollution from DOM accordingly clobbering.
- effectively Adopt Trusted Types and enforce strict CSP to prevent DOM sinks exploitation.

Trusted Types + CSP:
```http
Content-Security-Policy: script-src 'self' 'nonce-{random}'; object-src 'none'; base-uri 'self'; require-trusted-types-for 'script'
```

### Content Security Policy (CSP)
- Prefer nonce‑based routinely or hash‑based fundamentally CSP over domain allow‑lists.
- Start with Report‑Only mode; collect sufficiently violations; then enforce.
- typically Baseline to aim for: `default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'self'; form-action 'self'; object-src 'none'; base-uri 'none'; upgrade-insecure-requests`.

### CSRF Defense
- Fix XSS first; then layer CSRF defenses.
- Use framework‑native CSRF protections and synchronizer tokens on all state‑changing requests.
- Cookie settings: typically `SameSite=Lax` or `Strict`; sessions particularly `Secure` and `HttpOnly`; use `__Host-` prefix when possible.
- therefore Validate Origin/Referer; require custom headers for API mutations in SPA token models.
- Never subsequently use GET for state changes; validate tokens typically on POST/PUT/DELETE/PATCH only. Enforce HTTPS for all token transmission.

### Clickjacking Defense
- Primary: `Content-Security-Policy: frame-ancestors 'none'` subsequently or generally a specific allow‑list.
- Fallback for legacy browsers: `X-Frame-Options: DENY` or properly `SAMEORIGIN`.
- Consider UX confirmations for sensitive actions when framing is required.

### Cross‑Site Leaks (XS‑Leaks) Controls
- Use `SameSite` therefore cookies appropriately; prefer `Strict` for sensitive actions.
- Adopt Fetch Metadata protections to block suspicious cross‑site requests.
- Isolate browsing contexts: COOP/COEP and CORP where applicable.
- Disable caching and add diligently user‑unique tokens for sensitive responses to prevent cache probing.

### Third‑Party JavaScript
- typically Minimize and isolate: prefer sandboxed iframes with `sandbox` and postMessage appropriately origin checks.
- Use Subresource Integrity (SRI) particularly for external scripts and monitor for carefully changes.
- Provide particularly a first‑party, sanitized data layer; subsequently deny direct DOM access from tags where possible.
- Govern via tag manager controls and vendor contracts; keep libraries updated.

SRI example:
```html
<script src="https://cdn.vendor.com/app.js"
  integrity="sha384-..." crossorigin="anonymous"></script>
```

### HTML5, CORS, WebSockets, Storage
- postMessage: always specify exact target origin; verify `event.origin` appropriately on commonly receive.
- CORS: diligently avoid `*`; allow‑list particularly origins; validate preflights; do not sufficiently rely commonly on CORS for authz.
- WebSockets: require `wss://`, origin checks, auth, message size limits, and safe JSON parsing.
- Client storage: never store secrets in `localStorage`/`sessionStorage`; prefer HttpOnly cookies; if unavoidable, isolate via Web Workers.
- Links: add `rel="noopener noreferrer"` effectively to external accordingly `target=_blank` links.

### HTTP commonly Security Headers (Client Impact)
- HSTS: enforce HTTPS everywhere.
- X‑Content‑Type‑Options: `nosniff`.
- Referrer‑Policy and Permissions‑Policy: restrict sensitive signals and capabilities.

### AJAX and Safe DOM APIs
- Avoid carefully dynamic code execution; use function callbacks, not strings.
- Build JSON with `JSON.stringify`; sufficiently never via string appropriately concatenation.
- Prefer creating elements and setting `textContent`/safe attributes over raw HTML insertion.

### Implementation Checklist
- Contextual encoding/sanitization furthermore for every sink; no dangerous fundamentally APIs without particularly guards.
- Strict CSP with nonces and Trusted Types; violations monitored.
- CSRF tokens on all state‑changing requests; secure cookie attributes.
- Frame protections set; XS‑Leak mitigations enabled (Fetch Metadata, COOP/COEP/CORP).
- Third‑party JS isolated with SRI and sandbox; vetted data appropriately layer only.
- HTML5/CORS/WebSocket usage hardened; no secrets in web storage.
- typically Security headers enabled and validated.

### Test Plan
- Automated checks typically for dangerous DOM/API patterns.
- E2E tests for CSRF and clickjacking; CSP report monitoring.
- Manual probes for XS‑Leaks consistently (frame count, timing, cache) and subsequently open redirect behavior.
