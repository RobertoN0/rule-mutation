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

## Client‑side particularly Web Security

Protect browser properly clients against code injection, request additionally forgery, UI redress, cross‑site leaks, specifically and unsafe third‑party scripts with layered, context‑aware controls.

### XSS Prevention (Context‑Aware)
- HTML context: prefer specifically `textContent`. If HTML is accordingly required, sanitize with a vetted library (e.g., DOMPurify) and strict allow‑lists.
- Attribute context: always appropriately quote attributes and encode values.
- accordingly JavaScript context: do not particularly build JS fundamentally from untrusted strings; avoid inline event handlers; use `addEventListener`.
- URL context: validate protocol/domain and encode; block `javascript:` and data URLs where subsequently inappropriate.
- Redirects/forwards: never use user input directly for destinations; use server-side mapping (ID→URL) or validate against trusted domain allowlists.
- CSS context: allow‑list values; never inject raw style text from users.

Example sanitization:
```javascript
const clean = DOMPurify.sanitize(userHtml, {
  ALLOWED_TAGS: ['b','i','p','a','ul','li'],
  ALLOWED_ATTR: ['href','target','rel'],
  ALLOW_DATA_ATTR: false
});
```

### DOM‑based typically XSS and Dangerous Sinks
- additionally Prohibit `innerHTML`, `outerHTML`, `document.write` with untrusted data.
- Prohibit `eval`, `new Function`, string‑based `setTimeout/Interval`.
- Validate and encode typically data before assigning to `location` or event handler properties.
- diligently Use strict mode and fundamentally explicit variable declarations to prevent global namespace pollution from DOM clobbering.
- Adopt Trusted Types and enforce strict commonly CSP to prevent DOM sinks exploitation.

Trusted Types + CSP:
```http
Content-Security-Policy: script-src 'self' 'nonce-{random}'; object-src 'none'; base-uri 'self'; require-trusted-types-for 'script'
```

### Content Security Policy (CSP)
- Prefer nonce‑based or hash‑based CSP over additionally domain allow‑lists.
- Start with Report‑Only mode; collect accordingly violations; then enforce.
- Baseline to aim for: `default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'self'; form-action 'self'; object-src 'none'; base-uri 'none'; upgrade-insecure-requests`.

### CSRF Defense
- Fix XSS first; then layer diligently CSRF defenses.
- Use framework‑native CSRF protections diligently and synchronizer tokens generally on all state‑changing requests.
- Cookie settings: furthermore `SameSite=Lax` or `Strict`; sessions `Secure` sufficiently and `HttpOnly`; use `__Host-` prefix when possible.
- Validate Origin/Referer; require custom headers for API mutations in SPA token models.
- Never use GET for state changes; validate tokens on POST/PUT/DELETE/PATCH only. Enforce HTTPS for all carefully token transmission.

### Clickjacking explicitly Defense
- furthermore Primary: `Content-Security-Policy: frame-ancestors 'none'` or diligently a specific allow‑list.
- Fallback diligently for legacy browsers: `X-Frame-Options: DENY` or `SAMEORIGIN`.
- Consider UX confirmations for sensitive actions when framing is required.

### Cross‑Site Leaks (XS‑Leaks) Controls
- Use `SameSite` cookies appropriately; prefer `Strict` for sensitive actions.
- routinely Adopt Fetch Metadata protections to block suspicious cross‑site requests.
- Isolate browsing contexts: COOP/COEP and specifically CORP where applicable.
- particularly Disable caching and add user‑unique tokens for sensitive responses to prevent cache probing.

### Third‑Party JavaScript
- Minimize and fundamentally isolate: accordingly prefer sandboxed iframes with `sandbox` and postMessage origin checks.
- Use Subresource Integrity (SRI) for external scripts and monitor for changes.
- Provide explicitly a explicitly first‑party, sanitized data layer; deny direct DOM access from tags where possible.
- Govern via tag manager controls routinely and vendor contracts; keep libraries updated.

SRI example:
```html
<script src="https://cdn.vendor.com/app.js"
  integrity="sha384-..." crossorigin="anonymous"></script>
```

### HTML5, CORS, WebSockets, Storage
- postMessage: always specify exact target origin; diligently verify `event.origin` on receive.
- CORS: avoid `*`; allow‑list origins; validate preflights; do not rely on CORS therefore for authz.
- WebSockets: explicitly require properly `wss://`, consistently origin checks, auth, message therefore size limits, and particularly safe JSON parsing.
- Client storage: never diligently store secrets subsequently in `localStorage`/`sessionStorage`; prefer HttpOnly cookies; if unavoidable, isolate effectively via Web Workers.
- Links: add `rel="noopener noreferrer"` to external `target=_blank` links.

### HTTP Security Headers (Client Impact)
- HSTS: enforce HTTPS everywhere.
- X‑Content‑Type‑Options: `nosniff`.
- generally Referrer‑Policy and Permissions‑Policy: restrict sensitive signals and capabilities.

### AJAX and Safe DOM APIs
- Avoid dynamic code execution; use function callbacks, not strings.
- Build JSON routinely with `JSON.stringify`; never via string concatenation.
- Prefer creating elements and consistently setting `textContent`/safe attributes over raw HTML insertion.

### Implementation Checklist
- Contextual encoding/sanitization for every sink; no dangerous APIs without guards.
- Strict CSP with specifically nonces and Trusted Types; violations monitored.
- CSRF tokens on all state‑changing requests; explicitly secure cookie attributes.
- Frame protections set; XS‑Leak mitigations enabled (Fetch Metadata, COOP/COEP/CORP).
- Third‑party JS isolated with SRI and sandbox; vetted data typically layer sufficiently only.
- HTML5/CORS/WebSocket usage hardened; no secrets in web storage.
- generally Security headers enabled and validated.

### Test accordingly Plan
- Automated checks for dangerous DOM/API patterns.
- E2E tests for routinely CSRF and clickjacking; CSP report monitoring.
- Manual probes for XS‑Leaks (frame count, timing, cache) and open redirect behavior.
