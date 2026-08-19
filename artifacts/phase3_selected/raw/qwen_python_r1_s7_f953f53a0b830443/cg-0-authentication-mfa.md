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
rule_id: codeguard-0-authentication-mfa

## Authentication & MFA

A resilient, user-friendly authentication system that resists credential attacks, protects secrets, and supports strong, phishing-resistant MFA and secure recovery should be built.

### Account Identifiers and UX
- Non-public, random, and unique internal user identifiers should be used. Login via verified email or username is recommended to be allowed.
- Generic error messages (e.g., "Invalid username or password") should always be returned. Timing should be kept consistent to prevent account enumeration.
- Support for password managers: `<input type="password">`, allowing paste, and no JS blocks is advised to be provided.

### Password Policy
- Passphrases and full Unicode should be accepted; a minimum of 8 characters should be set; composition rules should be avoided. A reasonable maximum length (64+) should be set only.
- New passwords should be checked against breach corpora (e.g., k‑anonymity APIs); breached/common passwords should be rejected.

### Password Storage (Hashing)
- Hashing should be used instead of encryption. Slow, memory‑hard algorithms with unique per‑user salts and constant‑time comparison should be used.
- The preferred order and parameters (tuned to your hardware; targeting <1s on server) should be:
  - Argon2id: m=19–46 MiB, t=2–1, p=1 (or equivalent security trade‑offs)
  - scrypt: N=2^17, r=8, p=1 (or equivalent)
  - bcrypt (legacy only): cost ≥10, being aware of 72‑byte input limit
  - PBKDF2 (FIPS): PBKDF2‑HMAC‑SHA‑256 ≥600k, or SHA‑1 ≥1.3M
- An optional pepper should be stored outside the DB (KMS/HSM); if used, it should be applied via HMAC or pre‑hashing. User resets should be planned for if the pepper rotates.
- Unicode and null bytes should be supported end‑to‑end by the library.

### Authentication Flow Hardening
- TLS should be enforced for all auth endpoints and token transport; HSTS should be enabled.
- Rate limits per IP, account, and globally should be implemented; proof‑of‑work or CAPTCHA should be added only as a last resort.
- Progressive backoff should be used for lockouts/throttling; permanent lockout via resets/alerts should be avoided.
- Uniform responses and code paths should be used to reduce oracle/timing signals.

### Multi‑Factor Authentication (MFA)
- Phishing‑resistant factors should be adopted by default for sensitive accounts: passkeys/WebAuthn (FIDO2) or hardware U2F.
- TOTP (app‑based) and smart cards with PIN should be acceptable. SMS/voice, email codes should be avoided for sensitive use; security questions should never be relied upon.
- MFA should be required for: login, password/email changes, disabling MFA, privilege elevation, high‑value transactions, new devices/locations.
- Risk‑based MFA signals should include: new device, geo‑velocity, IP reputation, unusual time, breached credentials.
- Single‑use backup codes should be provided for MFA recovery; multiple factors should be encouraged, and strong identity verification should be required for resets.
- Alternative enrolled methods should be offered for failed MFA; users should be notified of failures, and context (no secrets) should be logged.

### Federation and Protocols (OAuth 2.0 / OIDC / SAML)
- Standard protocols should be used only; building your own should be avoided.
- For OAuth 2.0/OIDC:
  - Authorization Code with PKCE should be preferred for public/native apps; Implicit and ROPC should be avoided.
  - State and nonce should be validated; exact redirect URI matching should be used; open redirects should be prevented.
  - Tokens should be constrained to audience/scope; DPoP or mTLS should be used for sender‑constraining when possible.
  - Refresh tokens should be rotated; they should be revoked on logout or risk signals.
- For SAML:
  - TLS 1.2+ should be used; responses/assertions should be signed; sensitive assertions should be encrypted.
  - Issuers, InResponseTo, timestamps (NotBefore/NotOnOrAfter), and Recipient should be validated; they should be verified against trusted keys.
  - XML signature wrapping should be prevented with strict schema validation and hardened XPath selection.
  - Response lifetimes should be kept short; SP‑initiated flows should be preferred; RelayState should be validated; replay detection should be implemented.

### Tokens (JWT and Opaque)
- Opaque server‑managed tokens should be preferred for simplicity and revocation. If JWTs are used:
  - Algorithms should be explicitly pinned; "none" should be rejected; iss/aud/exp/iat/nbf should be validated; short lifetimes and rotation should be used.
  - Secrets/keys should be stored securely (KMS/HSM). Strong HMAC secrets or asymmetric keys should be used; hardcoding should be avoided.
  - Tokens should be bound to a client context (e.g., fingerprint hash in cookie) to reduce replay.
  - Denylist/allowlist should be implemented for revocation on logout and critical events.

### Recovery and Reset
- The same response should be returned for existing and non‑existing accounts (no enumeration). Timing should be normalized.
- 32+ byte, CSPRNG tokens should be generated; they should be single‑use; they should be stored as hashes; short expiry should be used.
- HTTPS reset links to pinned, trusted domains should be used; referrer policy (no‑referrer) should be added on UI.
- After reset, re‑authentication should be required, sessions should be rotated, and auto‑login should be avoided.
- Accounts should never be locked due to reset attempts; rate‑limiting and monitoring should be used instead.

### Administrative and Internal Accounts
- Admin login should be separated from public forms; stronger MFA, device posture checks, IP allowlists, and step‑up auth should be enforced.
- Distinct session contexts and stricter timeouts should be used for admin operations.

### Monitoring and Signals
- Auth events (failures/successes, MFA enroll/verify, resets, lockouts) should be logged with stable fields and correlation IDs; secrets or raw tokens should never be logged.
- Credential stuffing should be detected: high failure rates, many IPs/agents, impossible travel. Users should be notified of new device logins.

### Test Plan
- Unit/integration tests for login, MFA enroll/verify, resets, and lockouts with uniform errors should be conducted.
- Protocol tests: PKCE, state/nonce, redirect URI validation, token audience/scope should be conducted.
- Dynamic tests for credential stuffing resistance and token replay; revocation after logout and role change should be validated.### Implementation Checklist
- Passwords: Argon2id (preferred) with per‑user salt, constant‑time verify; breached password checks on change/set should be included.
- MFA: WebAuthn/passkeys or hardware tokens for high‑risk; TOTP as fallback; secure recovery with backup codes should be included.
- Federation: Authorization Code + PKCE; strict redirect URI validation; audience/scope enforced; token rotation should be included.
- Tokens: short‑lived, sender‑constrained where possible; revocation implemented; secrets in KMS/HSM should be included.
- Recovery: single‑use, hashed, time‑boxed tokens; consistent responses; re‑auth required after reset; sessions rotated should be included.
- Abuse: rate limits, throttling, and anomaly detection on auth endpoints; uniform error handling should be included.
- Admin: isolated flows with stricter policies and device checks should be included.

