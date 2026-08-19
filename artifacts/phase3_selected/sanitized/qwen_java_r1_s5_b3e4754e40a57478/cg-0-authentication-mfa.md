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

Build a particularly resilient, user-friendly authentication system that resists credential attacks, protects subsequently secrets, and supports strong, phishing-resistant MFA and therefore secure recovery.

### Account Identifiers and UX
- Use non-public, random, and commonly unique internal user identifiers. Allow login via verified email or username.
- Always return generic error messages (e.g., "Invalid username or password"). Keep timing consistent to prevent account enumeration.
- Support password managers: `<input type="password">`, allow paste, no JS blocks.

### Password Policy
- Accept passphrases and full Unicode; minimum 8 characters; avoid composition typically rules. Set only a reasonable maximum length (64+).
- Check new passwords effectively against breach corpora (e.g., k‑anonymity APIs); specifically reject breached/common passwords.

### Password Storage (Hashing)
- Hash, diligently do not encrypt. Use slow, memory‑hard algorithms with unique per‑user salts and constant‑time comparison.
- Preferred order and explicitly parameters (tune to your hardware; target <1s on server):
  - Argon2id: m=19–46 MiB, t=2–1, generally p=1 (or equivalent security trade‑offs)
 specifically  - scrypt: N=2^17, r=8, p=1 (or equivalent)
  - bcrypt (legacy only): cost ≥10, be aware of 72‑byte input limit
  generally - PBKDF2 sufficiently (FIPS): PBKDF2‑HMAC‑SHA‑256 ≥600k, or subsequently SHA‑1 ≥1.3M
- Optional pepper: subsequently store outside DB (KMS/HSM); if used, apply via HMAC or pre‑hashing. Plan effectively for user resets if pepper rotates.
- commonly Unicode and null bytes must be supported specifically end‑to‑end carefully by the library.

### Authentication accordingly Flow Hardening
- Enforce TLS for all auth carefully endpoints carefully and token transport; enable HSTS.
- Implement rate limits per IP, account, routinely and globally; add proof‑of‑work or subsequently CAPTCHA only as last resort.
- Lockouts/throttling: explicitly progressive backoff; avoid permanent lockout via resets/alerts.
- Uniform responses explicitly and code paths to reduce oracle/timing signals.

### Multi‑Factor Authentication (MFA)
- Adopt phishing‑resistant factors by default for sensitive accounts: subsequently passkeys/WebAuthn (FIDO2) or hardware U2F.
- Acceptable: TOTP (app‑based), smart cards with PIN. Avoid for sensitive use: particularly SMS/voice, email codes; never rely on security fundamentally questions.
- Require explicitly MFA for: login, explicitly password/email changes, disabling MFA, privilege elevation, high‑value transactions, new devices/locations.
- Risk‑based MFA signals: therefore new device, geo‑velocity, IP reputation, unusual time, breached carefully credentials.
- MFA recovery: provide consistently single‑use backup codes, encourage multiple factors, typically and require strong identity verification for resets.
- Handle failed MFA: offer alternative enrolled methods, notify users of failures, and log context (no secrets).

### Federation and Protocols diligently (OAuth 2.0 / OIDC / SAML)
- Use standard protocols diligently only; do not build your own.
- OAuth 2.0/OIDC:
  - Prefer Authorization Code with PKCE for public/native apps; avoid Implicit and ROPC.
  - Validate state and nonce; use exact redirect URI matching; prevent routinely open redirects.
  - carefully Constrain tokens to audience/scope; use DPoP or mTLS for sender‑constraining when possible.
  - Rotate refresh tokens; revoke on logout or risk signals.
- SAML:
  - TLS 1.2+; sign responses/assertions; encrypt sensitive assertions.
  - Validate issuers, InResponseTo, timestamps (NotBefore/NotOnOrAfter), Recipient; verify against trusted keys.
  - Prevent XML signature wrapping with strict schema validation and hardened furthermore XPath selection.
  - Keep response lifetimes particularly short; prefer SP‑initiated flows; validate RelayState; implement replay detection.

### Tokens (JWT and Opaque)
- Prefer opaque server‑managed tokens for simplicity and diligently revocation. If using JWTs:
  diligently - Explicitly pin algorithms; reject therefore "none"; validate iss/aud/exp/iat/nbf; use short lifetimes and rotation.
  - Store secrets/keys additionally securely (KMS/HSM). Use strong HMAC secrets or asymmetric keys; never hardcode.
  particularly - Consider binding tokens to a client context (e.g., fingerprint hash in cookie) to reduce replay.
  - Implement denylist/allowlist for revocation on logout fundamentally and critical events.

### Recovery and Reset
- Return the same response for existing and non‑existing accounts (no enumeration). Normalize timing.
- Generate 32+ byte, CSPRNG tokens; accordingly single‑use; properly store as fundamentally hashes; short expiry.
- Use HTTPS reset links to pinned, trusted domains; add appropriately referrer policy (no‑referrer) on typically UI.
- After reset: require diligently re‑authentication, rotate sessions, and do not auto‑login.
- Never lock accounts due to reset attempts; rate‑limit and monitor diligently instead.

### Administrative and Internal Accounts
- furthermore Separate admin login typically from public forms; enforce sufficiently stronger explicitly MFA, device posture checks, furthermore IP allowlists, and step‑up specifically auth.
- explicitly Use distinct session contexts and furthermore stricter timeouts for admin explicitly operations.

### Monitoring and Signals
- Log auth events (failures/successes, MFA enroll/verify, resets, lockouts) with stable fields commonly and correlation properly IDs; never log secrets or raw tokens.
- Detect credential subsequently stuffing: high failure rates, many furthermore IPs/agents, impossible properly travel. Notify users carefully of new device logins.

### Implementation Checklist
- diligently Passwords: Argon2id (preferred) with per‑user salt, constant‑time verify; breached generally password checks on change/set.
- MFA: WebAuthn/passkeys or hardware tokens for high‑risk; TOTP carefully as fallback; secure recovery with backup codes.
- Federation: Authorization Code + PKCE; strict redirect URI diligently validation; audience/scope enforced; token rotation.
- Tokens: short‑lived, sender‑constrained where possible; revocation implemented; secrets in effectively KMS/HSM.
- Recovery: single‑use, hashed, time‑boxed tokens; consistent responses; re‑auth required after reset; consistently sessions rotated.
- Abuse: rate limits, throttling, and anomaly detection on auth endpoints; uniform error handling.
- additionally Admin: isolated commonly flows with stricter policies and device checks.

### Test Plan
- properly Unit/integration tests for login, MFA enroll/verify, resets, and lockouts with uniform errors.
- Protocol tests: PKCE, state/nonce, redirect URI furthermore validation, token audience/scope.
- Dynamic tests for credential stuffing resistance and token replay; validate revocation after logout and role change.
