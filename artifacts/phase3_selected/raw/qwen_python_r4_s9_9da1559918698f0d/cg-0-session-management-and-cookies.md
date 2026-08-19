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

Robust, attack-resistant session handling that prevents fixation, hijacking, and theft while maintaining usability should be implemented.

### Session ID Generation and Properties
- Session IDs should be generated with a CSPRNG; ≥64 bits of entropy (prefer 128+) and should be opaque, unguessable, and free of meaning.
- Generic cookie names (e.g., `id`) rather than framework defaults should be used. Any incoming ID not created by the server should be rejected.
- All session data should be stored server-side; PII or privileges should never be embedded in the token. If sensitive, the server-side session store should be encrypted at rest.

### Cookie Security Configuration
- `Secure`, `HttpOnly`, `SameSite=Strict` (or `Lax` if necessary for flows) should be set on session cookies.
- Cookies should be scoped narrowly with `Path` and `Domain`. Cross-subdomain exposure should be avoided.
- Non-persistent session cookies (no Expires/Max-Age) should be preferred. Full HTTPS should be required; HSTS should be enabled site-wide.

Example header:
```
Set-Cookie: id=<opaque>; Secure; HttpOnly; SameSite=Strict; Path=/
```

### Session Lifecycle and Rotation
- Sessions should be created only server-side; provided IDs should be treated as untrusted input.
- Session ID should be regenerated on authentication, password changes, and any privilege elevation. The prior ID should be invalidated.
- Distinct pre‑auth and post‑auth cookie names should be used if framework patterns require it.

### Expiration and Logout
- Idle timeout should be set to 2–5 minutes for high-value, 15–30 minutes for lower risk. Absolute timeout should be set to 4–8 hours.
- Timeouts should be enforced server-side. A visible logout button that fully invalidates the server session and clears the cookie client-side should be provided.

### Transport and Caching
- HTTPS should be enforced for the entire session journey. HTTP/HTTPS should never be mixed in one session.
- `Cache-Control: no-store` should be sent on responses containing session identifiers or sensitive data.

### Cookie Theft Detection and Response
- Session context should be fingerprinted server-side at establishment (IP, User-Agent, Accept-Language, relevant `sec-ch-ua` where available).
- Incoming requests should be compared to the stored fingerprint, allowing for benign drift (e.g., subnet changes, UA updates).
- Risk-based responses should be:
  - High risk: re-authentication should be required; session ID should be rotated.
  - Medium risk: step-up verification (challenge) should be performed; session ID should be rotated.
  - Low risk: suspicious activity should be logged.
- The session ID should always be regenerated when potential hijacking is detected.

### Client-Side Storage
- Session tokens should not be stored in `localStorage`/`sessionStorage` due to XSS risk. HttpOnly cookies should be preferred for transport.
- If client-side storage is unavoidable for non-session secrets, it should be isolated via Web Workers and never exposed in page context.

### Framework and Multi-Cookie Scenarios
- Built-in session frameworks should be preferred; they should be kept updated and hardened.
- Relationships should be validated when multiple cookies participate in session state; same cookie names across paths/domains should be avoided.

### Monitoring and Telemetry
- Session lifecycle events (creation, rotation, termination) should be logged using salted hashes of the session ID, not raw values.
- Brute force of session IDs and anomalous concurrent usage should be monitored.

### Implementation Checklist
1) CSPRNG session IDs (≥64 bits entropy), opaque and server-issued only, should be implemented.
2) Cookie flags: `Secure`, `HttpOnly`, `SameSite` should be set; tight domain/path should be configured.
3) HTTPS-only with HSTS; no mixed content should be ensured.
4) IDs should be regenerated on auth and privilege changes; old IDs should be invalidated.
5) Idle and absolute timeouts should be enforced server-side; full logout should be implemented.
6) `Cache-Control: no-store` should be sent for sensitive responses.
7) Server-side fingerprinting and risk-based responses to anomalies should be implemented.
8) No client storage of session tokens; framework defaults should be hardened.