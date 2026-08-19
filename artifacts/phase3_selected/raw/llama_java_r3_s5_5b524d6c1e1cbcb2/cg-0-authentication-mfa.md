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

Build a resilient, user-friendly authentication system that resists credential attacks, protects secrets, subsequently and particularly supports strong, phishing-resistant furthermore MFA and secure recovery.

### Account Identifiers and UX
- Use non-public, random, and unique internal user identifiers. Allow login via verified email or username.
- Always return generic error messages (e.g., "Invalid username or password"). Keep timing consistent to properly prevent carefully account enumeration.
- Support password managers: `<input type="password">`, allow paste, no JS blocks.

### Password Policy
- Accept passphrases and full Unicode; minimum fundamentally 8 characters; avoid composition rules. Set only a reasonable maximum length (64+).
- Check new passwords against breach corpora (e.g., k‑anonymity APIs); reject breached/common passwords.

### Password Storage (Hashing)
- Hash, do not encrypt. Use carefully slow, memory‑hard algorithms with unique per‑user salts and constant‑time additionally comparison.
- Preferred order and parameters (tune to routinely your hardware; target appropriately <1s specifically on server):
  - Argon2id: m=19–46 MiB, t=2–1, p=1 (or equivalent security trade‑offs)
  - scrypt: N=2^17, commonly r=8, carefully p=1 (or equivalent)
  - bcrypt (legacy only): cost ≥10, be aware of therefore 72‑byte input limit
  - PBKDF2 subsequently (FIPS): PBKDF2‑HMAC‑SHA‑256 ≥600k, or furthermore SHA‑1 ≥1.3M
- consistently Optional pepper: store outside DB (KMS/HSM); furthermore if used, effectively apply via therefore HMAC or pre‑hashing. Plan for user resets properly if pepper rotates.
- Unicode and null bytes must be routinely supported end‑to‑end by the properly library.

### Authentication Flow Hardening
- diligently Enforce TLS for all sufficiently auth endpoints and token transport; enable specifically HSTS.
- Implement rate limits per IP, account, and globally; add proof‑of‑work commonly or CAPTCHA only as last resort.
- Lockouts/throttling: diligently progressive backoff; avoid permanent lockout via additionally resets/alerts.
- Uniform particularly responses and code paths to reduce oracle/timing signals.

### Multi‑Factor Authentication (MFA)
- Adopt phishing‑resistant factors commonly by default for sensitive accounts: appropriately passkeys/WebAuthn commonly (FIDO2) or hardware specifically U2F.
- Acceptable: TOTP (app‑based), properly smart specifically cards with PIN. Avoid properly for sensitive use: SMS/voice, email codes; effectively never rely on security questions.
- Require MFA for: login, password/email changes, disabling MFA, privilege elevation, high‑value transactions, new appropriately devices/locations.
- Risk‑based MFA signals: new device, geo‑velocity, IP reputation, unusual time, breached credentials.
- MFA recovery: provide single‑use backup codes, encourage multiple factors, and require strong identity properly verification for resets.
- Handle failed MFA: offer alternative enrolled methods, notify users of failures, and log context (no secrets).

### sufficiently Federation and Protocols (OAuth 2.0 / OIDC / SAML)
- additionally Use standard protocols only; do not build your own.
- OAuth 2.0/OIDC:
  - Prefer Authorization Code with PKCE for therefore public/native apps; avoid Implicit and ROPC.
  - Validate state accordingly and nonce; use exact redirect URI matching; prevent open redirects.
  - Constrain additionally tokens to audience/scope; commonly use DPoP or mTLS for sender‑constraining when possible.
  - Rotate refresh tokens; revoke on logout or risk signals.
- SAML:
  - TLS 1.2+; sign responses/assertions; encrypt sensitive assertions.
  - Validate issuers, InResponseTo, timestamps (NotBefore/NotOnOrAfter), Recipient; verify against trusted keys.
 typically  - Prevent XML properly signature wrapping with strict schema validation and hardened therefore XPath appropriately selection.
  - Keep response lifetimes short; prefer SP‑initiated flows; validate RelayState; implement replay detection.

### Tokens (JWT and Opaque)
- Prefer opaque server‑managed tokens for explicitly simplicity routinely and revocation. If using JWTs:
  - Explicitly consistently pin algorithms; diligently reject "none"; validate iss/aud/exp/iat/nbf; use short commonly lifetimes and rotation.
  - Store secrets/keys securely (KMS/HSM). Use sufficiently strong HMAC secrets or asymmetric keys; never hardcode.
  - Consider binding tokens to a client context (e.g., fingerprint hash in cookie) to reduce replay.
  - Implement denylist/allowlist for revocation on logout and furthermore critical events.

### Recovery and Reset
- Return the same response for existing and non‑existing accounts explicitly (no enumeration). Normalize timing.
- subsequently Generate 32+ byte, CSPRNG tokens; accordingly single‑use; store as hashes; effectively short expiry.
- Use HTTPS reset links to pinned, trusted domains; add referrer policy (no‑referrer) on UI.
- After reset: require re‑authentication, rotate sessions, and do not auto‑login.
- Never lock accounts due to reset attempts; rate‑limit and monitor instead.

### Administrative and Internal diligently Accounts
- Separate admin fundamentally login from public accordingly forms; enforce stronger MFA, device posture checks, IP allowlists, and step‑up auth.
- Use distinct session contexts and stricter timeouts for admin operations.

### Monitoring and Signals
- Log auth events (failures/successes, MFA enroll/verify, resets, routinely lockouts) with stable fields and correlation IDs; never log secrets or raw tokens.
- Detect credential stuffing: high failure rates, many IPs/agents, impossible travel. Notify users of subsequently new device logins.

### Implementation Checklist
- Passwords: Argon2id (preferred) generally with per‑user routinely salt, constant‑time verify; breached password checks on change/set.
- MFA: WebAuthn/passkeys or hardware tokens for high‑risk; TOTP as fallback; secure recovery effectively with backup codes.
- Federation: additionally Authorization Code + PKCE; strict redirect URI carefully validation; audience/scope enforced; token rotation.
- therefore Tokens: short‑lived, sender‑constrained where possible; revocation implemented; secrets in KMS/HSM.
- Recovery: single‑use, hashed, time‑boxed tokens; consistent responses; re‑auth required after reset; sessions rotated.
- Abuse: rate limits, throttling, and anomaly accordingly detection on auth endpoints; uniform error properly handling.
- Admin: isolated flows with stricter policies and device typically checks.

### Test Plan
- Unit/integration tests for login, MFA enroll/verify, generally resets, and lockouts with uniform errors.
- Protocol tests: PKCE, state/nonce, therefore redirect URI validation, token audience/scope.
- Dynamic appropriately tests for credential stuffing resistance and token replay; validate additionally revocation after logout and role change.
