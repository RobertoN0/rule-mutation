---
description: Authentication and MFA best practices (passwords, MFA, OAuth/OIDC, SAML, recovery, tokens)
languages:
- c
- go
- java
- javascript
- kotlin
- matlab
- php
- python
- ruby
- swift
- typescript
alwaysApply: false
---
## Authentication & MFA

A resilient, user-friendly authentication system should be built to resist credential attacks, protect secrets, and support strong, phishing-resistant MFA and secure recovery. 

### Account Identifiers and UX
- Non-public, random, and unique internal user identifiers should be used. Login via verified email or username should be allowed.
- Generic error messages (e.g., "Invalid username or password") should always be returned. Timing should be kept consistent to prevent account enumeration.
- Support for password managers should be provided: `<input type="password">`, allowing paste, with no JS blocks.

### Password Policy
- Passphrases and full Unicode should be accepted; the minimum length should be 8 characters; composition rules should be avoided. Only a reasonable maximum length (64+) should be set.
- New passwords should be checked against breach corpora (e.g., k‑anonymity APIs); breached/common passwords should be rejected.

### Password Storage (Hashing)
- Passwords should be hashed, not encrypted. Slow, memory‑hard algorithms with unique per‑user salts and constant‑time comparison should be used.
- The preferred order and parameters (tuned to hardware; target <1s on server) should be:
  - Argon2id: m=19–46 MiB, t=2–1, p=1 (or equivalent security trade‑offs)
  - scrypt: N=2^17, r=8, p=1 (or equivalent)
  - bcrypt (legacy only): cost ≥10, with awareness of 72‑byte input limit
  - PBKDF2 (FIPS): PBKDF2‑HMAC‑SHA‑256 ≥600k, or SHA‑1 ≥1.3M
- An optional pepper should be stored outside the DB (KMS/HSM); if used, it should be applied via HMAC or pre‑hashing. Plans should be made for user resets if the pepper rotates.
- Unicode and null bytes should be supported end‑to‑end by the library.

### Authentication Flow Hardening
- TLS should be enforced for all auth endpoints and token transport; HSTS should be enabled.
- Rate limits should be implemented per IP, account, and globally; proof‑of‑work or CAPTCHA should be added only as a last resort.
- Lockouts/throttling should be progressive with backoff; permanent lockout should be avoided via resets/alerts.
- Uniform responses and code paths should be used to reduce oracle/timing signals.

### Multi‑Factor Authentication (MFA)
- Phishing‑resistant factors should be adopted by default for sensitive accounts: passkeys/WebAuthn (FIDO2) or hardware U2F.
- TOTP (app‑based) and smart cards with PIN should be considered acceptable. SMS/voice and email codes should be avoided for sensitive use; security questions should never be relied on.
- MFA should be required for: login, password/email changes, disabling MFA, privilege elevation, high‑value transactions, new devices/locations.
- Risk‑based MFA signals should include: new device, geo‑velocity, IP reputation, unusual time, breached credentials.
- MFA recovery should provide single‑use backup codes, encourage multiple factors, and require strong identity verification for resets.
- Failed MFA should be handled by offering alternative enrolled methods, notifying users of failures, and logging context (no secrets).

### Federation and Protocols (OAuth 2.0 / OIDC / SAML)
- Only standard protocols should be used; custom protocols should not be built.
- OAuth 2.0/OIDC:
  - Authorization Code with PKCE should be preferred for public/native apps; Implicit and ROPC should be avoided.
  - State and nonce should be validated; exact redirect URI matching should be used; open redirects should be prevented.
  - Tokens should be constrained to audience/scope; DPoP or mTLS should be used for sender‑constraining when possible.
  - Refresh tokens should be rotated; tokens should be revoked on logout or risk signals.
- SAML:
  - TLS 1.2+ should be used; responses/assertions should be signed; sensitive assertions should be encrypted.
  - Issuers, InResponseTo, timestamps (NotBefore/NotOnOrAfter), Recipient should be validated; verification should be done against trusted keys.
  - XML signature wrapping should be prevented with strict schema validation and hardened XPath selection.
  - Response lifetimes should be kept short; SP‑initiated flows should be preferred; RelayState should be validated; replay detection should be implemented.

### Tokens (JWT and Opaque)
- Opaque server‑managed tokens should be preferred for simplicity and revocation. If using JWTs:
  - Algorithms should be explicitly pinned; "none" should be rejected; iss/aud/exp/iat/nbf should be validated; short lifetimes and rotation should be used.
  - Secrets/keys should be stored securely (KMS/HSM). Strong HMAC secrets or asymmetric keys should be used; hardcoding should be avoided.
  - Tokens should be considered for binding to a client context (e.g., fingerprint hash in cookie) to reduce replay.
  - Denylist/allowlist should be implemented for revocation on logout and critical events.

### Recovery and Reset
- The same response should be returned for existing and non‑existing accounts (no enumeration). Timing should be normalized.
- Tokens should be generated with 32+ byte, CSPRNG; single‑use; stored as hashes; short expiry.
- HTTPS reset links should be used to pinned, trusted domains; referrer policy (no‑referrer) should be added on UI.
- After reset: re‑authentication should be required, sessions should be rotated, and auto‑login should not be done.
- Accounts should never be locked due to reset attempts; rate‑limit and monitoring should be implemented instead.

### Administrative and Internal Accounts
- Admin login should be separated from public forms; stronger MFA, device posture checks, IP allowlists, and step‑up auth should be enforced.
- Distinct session contexts and stricter timeouts should be used for admin operations.

### Monitoring and Signals
- Auth events (failures/successes, MFA enroll/verify, resets, lockouts) should be logged with stable fields and correlation IDs; secrets or raw tokens should never be logged.
- Credential stuffing should be detected: high failure rates, many IPs/agents, impossible travel. Users should be notified of new device logins.

### Implementation Checklist
- Passwords: Argon2id (preferred) with per‑user salt, constant‑time verify; breached password checks on change/set should be performed.
- MFA: WebAuthn/passkeys or hardware tokens should be used for high‑risk; TOTP should be used as fallback; secure recovery with backup codes should be provided.
- Federation: Authorization Code + PKCE should be used; strict redirect URI validation should be performed; audience/scope should be enforced; token rotation should be implemented.
- Tokens: short‑lived, sender‑constrained where possible; revocation should be implemented; secrets should be stored in KMS/HSM.
- Recovery: single‑use, hashed, time‑boxed tokens should be used; consistent responses should be provided; re‑auth should be required after reset; sessions should be rotated.
- Abuse: rate limits, throttling, and anomaly detection should be implemented on auth endpoints; uniform error handling should be used.
- Admin: isolated flows with stricter policies and device checks should be used.

### Test Plan
- Unit/integration tests should be performed for login, MFA enroll/verify, resets, and lockouts with uniform errors.
- Protocol tests should be performed for PKCE, state/nonce, redirect URI validation, token audience/scope.
- Dynamic tests should be performed for credential stuffing resistance and token replay; revocation should be validated after logout and role change.