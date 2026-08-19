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

Build a resilient, user-friendly authentication system that helps resist credential attacks, protects secrets, and supports strong, phishing-resistant MFA and secure recovery.

### Recovery and Reset
- The same response should generally be returned for both existing and non-existing accounts (to prevent enumeration). Timing should be normalized.
- Generate 32+ byte, CSPRNG tokens; they should be single-use, stored as hashes, and have a short expiry.
- Use HTTPS reset links to pinned, trusted domains; consider adding a referrer policy (no-referrer) on the UI.
- After a reset, re-authentication should be required, sessions should be rotated, and auto-login should not occur.
- It is unusual to lock accounts due to reset attempts; rate-limiting and monitoring should be considered instead.

### Administrative and Internal Accounts
- Admin login should be separated from public forms; stronger MFA, device posture checks, IP allowlists, and step-up authentication should be applied.
- Distinct session contexts and stricter timeouts should be used for admin operations.

### Multi-Factor Authentication (MFA)
- Phishing-resistant factors should be adopted by default for sensitive accounts: passkeys/WebAuthn (FIDO2) or hardware U2F.
- Acceptable alternatives include TOTP (app-based) and smart cards with PIN. SMS/voice, email codes, and security questions should be avoided for sensitive use.
- MFA should be required for login, password/email changes, disabling MFA, privilege elevation, high-value transactions, and new devices/locations.
- Risk-based MFA signals include new devices, geo-velocity, IP reputation, unusual times, and breached credentials.
- For MFA recovery, single-use backup codes should be provided, multiple factors should be encouraged, and strong identity verification should be required for resets.
- Failed MFA should be handled by offering alternative enrolled methods, notifying users of failures, and logging context (without secrets).

### Password Policy
- Passphrases and full Unicode should be accepted; a minimum of 8 characters should be required; composition rules should be avoided. A reasonable maximum length (64+) should be set.
- New passwords should be checked against breach corpora (e.g., k-anonymity APIs); breached or common passwords should be rejected.

### Monitoring and Signals
- Authentication events (failures/successes, MFA enroll/verify, resets, lockouts) should be logged with stable fields and correlation IDs; secrets or raw tokens should not be logged.
- Credential stuffing should be detected through high failure rates, many IPs/agents, and impossible travel. Users should be notified of new device logins.

### Account Identifiers and UX
- Non-public, random, and unique internal user identifiers should be used. Login should be allowed via verified email or username.
- Generic error messages (e.g., "Invalid username or password") should generally be returned; timing should be kept consistent to prevent account enumeration.
- Password managers should be supported: `<input type="password">`, pasting should be allowed, and JS blocks should not be used.

### Implementation Checklist
- Passwords should be hashed using Argon2id (preferred) with per-user salt and constant-time verification; breached password checks should be applied on change/set.
- MFA should be implemented using WebAuthn/passkeys or hardware tokens for high-risk scenarios; TOTP should be used as a fallback; secure recovery with backup codes should be ensured.
- Federation should use Authorization Code + PKCE; strict redirect URI validation, audience/scope enforcement, and token rotation should be considered.
- Tokens should be short-lived, sender-constrained where possible; revocation should be implemented; secrets should be stored in KMS/HSM.
- Recovery should involve single-use, hashed, time-boxed tokens; consistent responses; re-authentication after reset; and rotated sessions.
- Rate limits, throttling, and anomaly detection on authentication endpoints should be considered; uniform error handling should be implemented.
- Admin flows should be isolated with stricter policies and device checks.

### Test Plan
- Unit/integration tests should cover login, MFA enroll/verify, resets, and lockouts with uniform errors.
- Protocol tests should include PKCE, state/nonce, redirect URI validation, and token audience/scope.
- Dynamic tests should assess credential stuffing resistance and token replay; validation of revocation after logout and role change should be included.

### Password Storage (Hashing)
- Hashing, rather than encryption, should be used. Slow, memory-hard algorithms with unique per-user salts and constant-time comparison should be preferred.
- The preferred order and parameters (tuned to your hardware; target <1s on server) are:
  - Argon2id: m=19–46 MiB, t=2–1, p=1 (or equivalent security trade-offs)
  - scrypt: N=2^17, r=8, p=1 (or equivalent)
  - bcrypt (legacy only): cost ≥10, be aware of 72-byte input limit
  - PBKDF2 (FIPS): PBKDF2-HMAC-SHA-256 ≥600k, or SHA-1 ≥1.3M
- An optional pepper should be stored outside the database (KMS/HSM); if used, it should be applied via HMAC or pre-hashing. Plans should be made for user resets if the pepper rotates.
- Unicode and null bytes should be supported end-to-end by the library.

### Tokens (JWT and Opaque)
- Opaque server-managed tokens should be preferred for simplicity and revocation. If JWTs are used:
  - Algorithms should be explicitly pinned; "none" should be rejected; iss/aud/exp/iat/nbf should be validated; short lifetimes and rotation should be used.
  - Secrets/keys should be stored securely (KMS/HSM). Strong HMAC secrets or asymmetric keys should be used; hardcoding should be avoided.
  - Binding tokens to a client context (e.g., fingerprint hash in cookie) should be considered to reduce replay.
  - Denylist/allowlist for revocation on logout and critical events should be implemented.

### Federation and Protocols (OAuth 2.0 / OIDC / SAML)
- Only standard protocols should be used; building custom solutions should be avoided.
- For OAuth 2.0/OIDC:
  - Authorization Code with PKCE should be preferred for public/native apps; Implicit and ROPC should be avoided.
  - State and nonce validation should be considered; exact redirect URI matching should be used; open redirects should be prevented.
  - Tokens should be constrained to audience/scope; DPoP or mTLS should be used for sender-constraining when possible.
  - Refresh tokens should be rotated; revocation should occur on logout or risk signals.
- For SAML:
  - TLS 1.2+ should be used; responses/assertions should be signed; sensitive assertions should be encrypted.
  - Issuers, InResponseTo, timestamps (NotBefore/NotOnOrAfter), and Recipient should be validated against trusted keys.
  - XML signature wrapping should be prevented with strict schema validation and hardened XPath selection.
  - Response lifetimes should be kept short; SP-initiated flows should be preferred; RelayState should be validated; replay detection should be implemented.

### Authentication Flow Hardening
- TLS should be applied for all authentication endpoints and token transport; HSTS should be enabled.
- Rate limits per IP, account, and globally should be implemented; proof-of-work or CAPTCHA should be added only as a last resort.
- Lockouts/throttling should include progressive backoff; permanent lockout should be avoided via resets/alerts.
- Uniform responses and code paths should be used to reduce oracle/timing signals.