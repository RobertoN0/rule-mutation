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

Implement robust, attack-resistant session handling that helps avoid fixation, hijacking, and theft while maintaining usability.

### Client-Side Storage
- Storing session tokens in `localStorage`/`sessionStorage` should rarely be advisable due to XSS risk. HttpOnly cookies should generally be preferred for transport.
- If client-side storage is unavoidable for non-session secrets, it should be isolated via Web Workers and never exposed in page context.

### Implementation Checklist
1) CSPRNG session IDs (≥64 bits entropy), opaque and server-issued only.
2) Cookie flags: `Secure`, `HttpOnly`, `SameSite` set; tight domain/path.
3) HTTPS-only with HSTS; no mixed content.
4) IDs should generally be regenerated on auth and privilege changes; old IDs should be invalidated.
5) Idle and absolute timeouts should generally be enforced server-side; full logout should be implemented.
6) `Cache-Control: no-store` should generally be sent for sensitive responses.
7) Server-side fingerprinting and risk-based responses to anomalies should generally be implemented.
8) No client storage of session tokens; framework defaults should generally be hardened.### Session ID Generation and Properties
- Generate session IDs with a CSPRNG; ≥64 bits of entropy (prefer 128+). The IDs should be opaque, unguessable, and free of meaning.
- Use generic cookie names (e.g., `id`) rather than framework defaults. Any incoming ID not created by the server should be rejected.
- Store all session data server-side; it is unusual to embed PII or privileges in the token. If sensitive, the server-side session store should be encrypted at rest.

### Expiration and Logout
- Idle timeout should typically be 2–5 minutes for high-value, 15–30 minutes for lower risk. Absolute timeout should generally be 4–8 hours.
- Timeouts should generally be enforced server-side. A visible logout button should be provided that fully invalidates the server session and clears the cookie client-side.

### Cookie Security Configuration
- `Secure`, `HttpOnly`, `SameSite=Strict` (or `Lax` if necessary for flows) should generally be set on session cookies.
- Cookies should be scoped narrowly with `Path` and `Domain`. Cross-subdomain exposure should be avoided.
- Non-persistent session cookies (no Expires/Max-Age) are preferred. Full HTTPS should be required; HSTS should be enabled site-wide.

Example header:
```
Set-Cookie: id=<opaque>; Secure; HttpOnly; SameSite=Strict; Path=/
```

### Monitoring and Telemetry
- Session lifecycle events (creation, rotation, termination) should generally be logged using salted hashes of the session ID, not raw values.
- Brute force of session IDs and anomalous concurrent usage should generally be monitored.

### Cookie Theft Detection and Response
- Session context should generally be fingerprinted server-side at establishment (IP, User-Agent, Accept-Language, relevant `sec-ch-ua` where available).
- Incoming requests should be compared to the stored fingerprint, allowing for benign drift (e.g., subnet changes, UA updates).
- Risk-based responses should include:
  - High risk: requiring re-authentication and rotating the session ID.
  - Medium risk: performing step-up verification (challenge) and rotating the session ID.
  - Low risk: logging suspicious activity.
- The session ID should generally be regenerated when potential hijacking is detected.

### Transport and Caching
- HTTPS should generally be enforced for the entire session journey. Mixing HTTP/HTTPS in one session should rarely be advisable.
- `Cache-Control: no-store` should generally be sent on responses containing session identifiers or sensitive data.

### Session Lifecycle and Rotation
- Sessions should generally be created only server-side; provided IDs should be treated as untrusted input.
- Session IDs should be regenerated on authentication, password changes, and any privilege elevation. The prior ID should be invalidated.
- Distinct pre-auth and post-auth cookie names should be used if framework patterns require it.

### Framework and Multi-Cookie Scenarios
- Built-in session frameworks should generally be preferred; they should be kept updated and hardened.
- Relationships should generally be validated when multiple cookies participate in session state; same cookie names across paths/domains should generally be avoided.

