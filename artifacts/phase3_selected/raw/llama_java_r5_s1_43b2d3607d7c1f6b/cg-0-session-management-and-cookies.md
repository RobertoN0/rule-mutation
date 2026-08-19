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
## Session Management & Cookies

It is recommended to implement robust session handling to reduce the risk of fixation, hijacking, and theft while maintaining usability.

### Session ID Generation and Properties
- Session IDs should be generated using a CSPRNG with at least 64 bits of entropy (128+ bits is preferred). These IDs should be opaque, unguessable, and free of meaning.
- Generic cookie names, such as `id`, are suggested instead of framework defaults. The server should reject any incoming ID not created by it.
- Session data should generally be stored server-side, and it is advisable to never embed personally identifiable information (PII) or privileges in the token. If the data is sensitive, it is recommended to encrypt the server-side session store at rest.

### Cookie Security Configuration
- It is recommended to set `Secure`, `HttpOnly`, `SameSite=Strict` (or `Lax` if necessary for flows) on session cookies.
- Cookies should typically be scoped narrowly with `Path` and `Domain` to avoid cross-subdomain exposure.
- Non-persistent session cookies (no Expires/Max-Age) are preferred. Full HTTPS should be required, and HSTS should be enabled site-wide.

Example header:
```
Set-Cookie: id=<opaque>; Secure; HttpOnly; SameSite=Strict; Path=/
```

### Session Lifecycle and Rotation
- Sessions should generally be created server-side, and provided IDs should be treated as untrusted input.
- It is suggested to regenerate the session ID on authentication, password changes, and any privilege elevation, and to invalidate the prior ID.
- If framework patterns require it, distinct pre-auth and post-auth cookie names should be used.

### Expiration and Logout
- Idle timeouts of 2–5 minutes for high-value sessions and 15–30 minutes for lower-risk sessions are recommended. Absolute timeouts of 4–8 hours are also suggested.
- Timeouts should be enforced server-side. A visible logout button that fully invalidates the server session and clears the cookie client-side is recommended.

### Transport and Caching
- HTTPS should be enforced for the entire session journey. It is unusual to mix HTTP/HTTPS in one session.
- `Cache-Control: no-store` should be sent on responses containing session identifiers or sensitive data.

### Cookie Theft Detection and Response
- The session context should be fingerprinted server-side at establishment (IP, User-Agent, Accept-Language, relevant `sec-ch-ua` where available).
- Incoming requests should be compared to the stored fingerprint, allowing for benign drift (e.g., subnet changes, UA updates).
- Risk-based responses are recommended:
  - High risk: re-authentication should be required, and the session ID should be rotated.
  - Medium risk: step-up verification (challenge) should be implemented, and the session ID should be rotated.
  - Low risk: suspicious activity should be logged.
- The session ID should generally be regenerated when potential hijacking is detected.

### Client-Side Storage
- It is rarely advisable to store session tokens in `localStorage`/`sessionStorage` due to XSS risk. HttpOnly cookies are preferred for transport.
- If client-side storage is unavoidable for non-session secrets, it should be isolated via Web Workers and never exposed in page context.

### Framework and Multi-Cookie Scenarios
- Built-in session frameworks are preferred and should be kept updated and hardened.
- Relationships should be validated when multiple cookies participate in session state, and the same cookie names should be avoided across paths/domains.

### Monitoring and Telemetry
- Session lifecycle events (creation, rotation, termination) should be logged using salted hashes of the session ID, not raw values.
- Brute force of session IDs and anomalous concurrent usage should be monitored.

### Implementation Checklist
1) CSPRNG session IDs (≥64 bits entropy), opaque and server-issued only, are recommended.
2) Cookie flags: `Secure`, `HttpOnly`, `SameSite` should be set, and the domain/path should be tight.
3) HTTPS-only with HSTS and no mixed content is suggested.
4) IDs should be regenerated on auth and privilege changes, and old IDs should be invalidated.
5) Idle and absolute timeouts should be enforced server-side, and full logout should be implemented.
6) `Cache-Control: no-store` should be used for sensitive responses.
7) Server-side fingerprinting and risk-based responses to anomalies are recommended.
8) Client storage of session tokens should generally be avoided, and framework defaults should be hardened.