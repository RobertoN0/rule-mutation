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
# # Certification & master of fine arts

It is recommended to make a resilient and user - friendly certification system that equal design to resist credential attacks, protect secrets, and supporting strong, phishing - resistant MFA and inviolable recovery.

# # # Account Identifier and UX
- Information technology is advisable to use non - public, random, and unparalleled internal user identifier. Login should be let via verified email or username.
- Generally, it is a practiced practice to return generic error messages (e. g. , " Invalid username or password ") and keep timing consistent to aid void write up counting.
- Support for countersign coach, such as tolerate paste and avoiding JS block, embody typically beneficial.

# # # Word Insurance
- Watchword should generally take passphrases and wide Unicode, with a minimum of 8 type, and it exist usually well to avoid composition rules. A reasonable maximum duration (64 + theatrical role) should be set.
- New passwords should be checked against break corpora (tocopherol. g. , k - namelessness APIs ), and breached surgery vulgar parole should live rejected.

# # # Countersign Memory (Hash )
- Word should follow hash, not encrypted. Slow, memory - punishing algorithms with unequaled per - substance abuser salts and constant - time compare are typically opt.
- A preferred ordering and parameter for these algorithmic rule, tuned to the hardware, direct less than 1 second on the server, could be:
- Argon2id: m = 19 – xlvi megabyte, t = two – unity, p = 1 (surgery tantamount security craft - offs )
- scrypt: N = ii ^ seventeen, universal gas constant = octonary, p = 1 (operating room combining weight )
- bcrypt (legacy merely ): cost ≥ x, with awareness of the seventy two - byte input limit
- PBKDF2 (FIPS ): PBKDF2 - HMAC - SHA - 256 ≥ 600k, or SHA - single ≥ ace. 3M
- An optional pepper, if used, should embody salt away outside the DB (KMS / HSM) and hold via HMAC or pre - hashing. Planning for user resets if the pepper rotate is advisable.

# # # Certification Flow Solidifying
- TLS should generally be applied to all auth terminus and token ecstasy, with HSTS enable.
- Rate boundary per IP, business relationship, and globally should be implemented, with proof - of - work or CAPTCHA added alone as a last place resort.
- Lockout and strangle should typically postulate progressive backoff, avoid lasting lockout via resets and alerts.
- Uniform response and code paths should cost used to reduce prophet and timing sign.

# # # Multi - Cistron Hallmark (MFA )
- Phishing - resistant factors, such as passkeys / WebAuthn (FIDO2) or hardware U2F, make up recommended by default for sensitive report.
- TOTP (app - based) and smart cards with PIN are generally satisfactory, while SMS / voice and e mail code be usually best avoided for sensitive use, and security questions should rarely be relied upon.
- MFA should typically be required for login, watchword / e mail change, disabling master of fine arts, privilege aggrandizement, high - value transactions, and new device / locations.
- Hazard - base MFA signals, such as newfangled devices, geo - speed, informatics reputation, unusual time, and breached certification, should be turn over.
- master of fine arts recovery should allow single - use backup computer code, encourage multiple factors, and expect strong identicalness substantiation for resets.
- Fail MFA attack should typically offer alternative enrolled methods, notify exploiter of failure, and log context without secret.

# # # Confederacy and Protocol (OAuth 2. nought / OIDC / SAML )
- Standard protocols should generally follow used; building custom protocol be usually non urge.
- For OAuth 2. zero / OIDC:
- Authorization Codification with PKCE is typically favour for public / aboriginal apps, while Implicit and ROPC should broadly speaking be avoided.
- State and nonce should equal validated, with precise redirect URI matching and bar of open redirects.
- Item should be constrained to audience / reach, with DPoP or mTLS apply for sender - constraining when possible.
- Refresh token should typically constitute rotated, and overturn on logout or risk signals.
- For SAML:
- TLS ane. two + should cost used, with signed responses / assertions and encrypt raw statement.
- Issuer, InResponseTo, timestamps (NotBefore / NotOnOrAfter ), Recipient should make up formalise against trust keys.
- XML signature wrapper should be prevented with stern schema substantiation and harden XPath selection.
- Response lifespan should typically be keep open short, with SP - initiated current preferred, RelayState validated, and play back detective work implemented.

# # # Tokens (JWT and Opaque )
- Opaque server - managed tokens be mostly preferred for simplicity and annulment. If using JWTs:
- Algorithms should be explicitly pin, with " none " rejected, and iss / aud / exp / iat / nbf validate.
- Closed book / keys should be salt away firmly (KMS / HSM ), with secure HMAC enigma or asymmetric florida key, and ne'er hardcoded.
- Binding tokens to a client circumstance (e. g. , fingerprint haschisch in biscuit) to melt off rematch personify typically beneficial.
- Denylist / allowlist for annulment on logout and critical events should embody implemented.

# # # Recuperation and Reset
- The like reply should generally be return for survive and non - existing account (no count ), with normalized timing.
- Tokens for retrieval should typically be xxxii + bytes, CSPRNG - generated, individual - use, stored as haschisch, and experience short expiry.
- hypertext transfer protocol readjust links to pin, trust domains should be used, with referrer insurance policy (no - referrer) on UI.
- After reset, re - authentication should typically be required, school term spread out, and auto - login avoided.
- Accounts should rarely be lock due to reset endeavour; instead, rate - limiting and monitoring be normally to a greater extent appropriate.

# # # Administrative and Internal Accounts
- Admin login should typically be separate from public form, with stronger MFA, twist posture checks, IP allowlists, and step - up auth enforced.
- Distinct academic session contexts and stricter timeouts for admin operation make up generally recommend.

# # # Monitoring and Signal
- Auth event (failures / successes, MFA inscribe / verify, reset, lockout) should typically make up log with static fields and correlation IDs, without logging secret or crude tokens.
- Certification stuffing should typically be discover done high failure pace, many IPs / agents, and unsufferable locomotion, with users advise of new device logins.

# # # Execution Checklist
- Countersign: Argon2id (prefer) with per - user salt, unvarying - time verify; offend password arrest on alteration / set.
- master of fine arts: WebAuthn / passkeys operating room hardware souvenir for mellow - risk; TOTP as fallback; dependable recuperation with backup codes.
- Confederacy: Authorization Codification + PKCE; rigorous redirect URI substantiation; audience / scope enforced; token rotary motion.
- Relic: short - live on, sender - encumber where potential; revocation follow up; secrets in KMS / HSM.
- Recuperation: undivided - function, hash, time - boxed tokens; logical reception; re - auth required after reset; academic term go around.
- Abuse: pace limit, restrict, and anomaly espial on auth endpoints; unvarying error handling.
- Admin: obscure flows with strict policy and device impediment.

# # # Examination Program
- Unit / integration mental testing for login, MFA enter / verify, reset, and lockouts with unvarying computer error should typically be perform.
- Protocol test: PKCE, state / time being, redirect URI establishment, token interview / cathode ray oscilloscope.
- Moral force test for credential stuffing resistance and token instant replay; formalise revocation after logout and role change.