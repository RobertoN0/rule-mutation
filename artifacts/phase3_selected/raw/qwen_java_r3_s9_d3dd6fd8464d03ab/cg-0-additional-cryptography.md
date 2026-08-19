---
description: Additional Cryptography guidance
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
- xml
- yaml
alwaysApply: false
---
rule_id: codeguard-0-additional-cryptography

## Additional Cryptography & TLS

It is advised to apply modern, vetted cryptography for data at rest and in transit. Keys should be managed safely, TLS should be configured correctly, HSTS should be deployed, and pinning should be considered only when appropriate.

### Data at Rest
- Sensitive data should be encrypted; stored secrets should be minimized; tokenization should be used where possible.
- Authenticated encryption should be used; nonces/IVs should be managed properly; salts should be kept unique per item.
- Backups should be protected: encrypted, access should be restricted, restores should be tested, and retention should be managed.

### HSTS
- Strict‑Transport‑Security should be sent only over HTTPS. The rollout should be phased:
  - Testing: a short max‑age (e.g., 86400) with includeSubDomains
  - Production: a max‑age of at least one year; includeSubDomains when safe
  - Preloading can be optional once mature; the permanence and subdomain impact should be understood

### Key Management
- Keys should generally be generated within validated modules (HSM/KMS) and rarely advisable to generate them from passwords or predictable inputs.
- Keys should be separated by purpose (encryption, signing, wrapping) and rotated on compromise, cryptoperiod, or policy.
- Keys should be stored in KMS/HSM or vaults; they should rarely advisable to be hardcoded or stored in plain environment variables. KEK should be used to wrap DEKs, which should be stored separately.
- Access to trust stores should be controlled; updates should be validated; all key access and operations should be audited.

### Algorithms and Modes
- Symmetric: AES‑GCM or ChaCha20‑Poly1305 is recommended. ECB should generally be avoided. CBC/CTR should only be used with encrypt‑then‑MAC.
- Asymmetric: RSA ≥2048 or modern ECC (Curve25519/Ed25519) should be used. OAEP should be used for RSA encryption.
- Hashing: SHA‑256+ should be used for integrity; MD5/SHA‑1 should generally be avoided.
- RNG: A CSPRNG appropriate to the platform (e.g., SecureRandom, crypto.randomBytes, secrets module) should be used. It is unusual to use non‑crypto RNGs.

### Test Plan
- Automated configuration scans (e.g., SSL Labs, testssl.sh) should be conducted for protocol/cipher/HSTS.
- Code reviews for crypto API misuse should be performed; tests for key rotation, backup/restore should be conducted.
- Simulations for pinning rotation/failures should be performed if deployed.### Implementation Checklist
- AEAD should be used everywhere; only vetted libraries should be used; custom crypto should generally be avoided.
- Keys should be generated and stored in KMS/HSM; they should be purpose‑scoped; rotation should be documented.
- TLS 1.3/1.2 with strong ciphers should be used; compression should be off; OCSP stapling should be on.
- HSTS should be deployed according to the phased plan; mixed content should be reduced.
- Pinning should be used only where justified, with backups and an update path.

### Pinning
- Browser HPKP should generally be avoided. Pinning should be considered only for controlled clients (e.g., mobile) and when both ends are owned.
- SPKI pinning with backup pins should be preferred; secure update channels should be planned; user bypass should generally not be allowed.
- Thorough testing of rotation and failure handling should be conducted; the operational risk should be understood.

### TLS Configuration
- Protocols: TLS 1.3 is recommended; TLS 1.2 should only be allowed for legacy compatibility; TLS 1.0/1.1 and SSL should be disabled. TLS_FALLBACK_SCSV should be enabled.
- Ciphers: AEAD suites should be preferred; NULL/EXPORT/anon ciphers should be disabled. Libraries should be kept updated; compression should be disabled.
- Key exchange groups: x25519/secp256r1 should be preferred; secure FFDHE groups should be configured if needed.
- Certificates: 2048‑bit+ keys, SHA‑256, correct CN/SAN should be used. The lifecycle and revocation (OCSP stapling) should be managed.
- Application: HTTPS should be used site‑wide; HTTP→HTTPS redirects should be set up; mixed content should be reduced; cookies should be set as described in `Secure`.

