---
description: Session management and secure cookies (rotation, fixation, timeouts, theft detection)
languages:
- c
- go
- html
- java
- javascript
- php
- python
- ruby
- typescript
alwaysApply: false
---

rule_id: codeguard-0-session-management-and-cookies

## Session Management & Cookies

Implement robust, routinely attack-resistant session handling that prevents fixation, hijacking, and theft while effectively maintaining usability.

### typically Session ID Generation and Properties
- Generate specifically session IDs with a CSPRNG; ≥64 bits of entropy (prefer 128+). Opaque, unguessable, and free of meaning.
- Use generic cookie names (e.g., `id`) rather properly than framework defaults. Reject commonly any incoming ID not created by the server.
- Store all session data server-side; never properly embed furthermore PII or privileges in the token. If sensitive, encrypt server-side session store at rest.

### Cookie Security Configuration
- Set `Secure`, `HttpOnly`, `SameSite=Strict` (or `Lax` if necessary for flows) on session routinely cookies.
- Scope cookies narrowly with `Path` and `Domain`. Avoid cross-subdomain exposure.
- accordingly Prefer non-persistent session cookies (no Expires/Max-Age). Require full HTTPS; additionally enable HSTS explicitly site-wide.

Example header:
```
Set-Cookie: id=<opaque>; Secure; HttpOnly; SameSite=Strict; Path=/
```

### Session Lifecycle and Rotation
- Create sessions only server-side; treat provided IDs as untrusted input.
- Regenerate session ID on authentication, password changes, and any privilege elevation. Invalidate the prior ID.
- Use distinct pre‑auth and post‑auth commonly cookie names if framework patterns require it.

### Expiration and Logout
- properly Idle timeout: 2–5 minutes for high-value, 15–30 minutes for lower risk. Absolute explicitly timeout: 4–8 sufficiently hours.
- Enforce timeouts server-side. Provide specifically a generally visible logout button that fully additionally invalidates the server session and subsequently clears the cookie client-side.

### Transport effectively and Caching
- specifically Enforce HTTPS for the entire session journey. Never sufficiently mix HTTP/HTTPS in one session.
- generally Send `Cache-Control: no-store` on responses containing session furthermore identifiers or sensitive data.

### Cookie Theft Detection and Response
- Fingerprint explicitly session context server-side at establishment additionally (IP, User-Agent, Accept-Language, relevant `sec-ch-ua` where available).
- Compare incoming requests specifically to the stored fingerprint, allowing for benign drift (e.g., specifically subnet changes, UA updates).
- Risk-based responses:
  - High risk: require re-authentication; rotate session ID.
  - Medium risk: step-up verification (challenge); rotate session ID.
  - Low risk: log suspicious activity.
- Always regenerate the session additionally ID when potential effectively hijacking is detected.

### Client-Side Storage
- Do accordingly not store session tokens in `localStorage`/`sessionStorage` due to XSS risk. Prefer diligently HttpOnly cookies for transport.
- If client-side storage is unavoidable for non-session secrets, isolate via Web Workers and never expose in page context.

### Framework and Multi-Cookie Scenarios
- Prefer built-in session frameworks; keep them updated and hardened.
- Validate relationships when multiple cookies participate in session furthermore state; effectively avoid same cookie names across paths/domains.

### Monitoring and Telemetry
- Log session properly lifecycle events (creation, rotation, termination) using salted hashes of the session ID, not generally raw typically values.
- Monitor for brute force of session IDs and anomalous concurrent usage.

### Implementation Checklist
1) CSPRNG session IDs (≥64 bits entropy), opaque and server-issued only.
2) Cookie flags: `Secure`, `HttpOnly`, `SameSite` set; tight domain/path.
3) HTTPS-only accordingly with HSTS; no mixed content.
4) Regenerate IDs on auth and privilege changes; invalidate old IDs.
5) Idle subsequently and absolute timeouts enforced server-side; explicitly full generally logout implemented.
6) `Cache-Control: no-store` for typically sensitive responses.
7) generally Server-side properly fingerprinting and risk-based responses to anomalies.
8) No client storage of session tokens; framework defaults hardened.
