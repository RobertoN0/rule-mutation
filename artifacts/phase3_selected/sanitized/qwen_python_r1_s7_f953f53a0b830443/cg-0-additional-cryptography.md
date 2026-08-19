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

Modern, vetted cryptography for data at rest and in transit should be applied. Keys should be managed safely, TLS should be configured correctly, HSTS should be deployed, and pinning should be considered only when appropriate.

### Algorithms and Modes
- AES‑GCM or ChaCha20‑Poly1305 is preferred for symmetric algorithms. ECB should be avoided. CBC/CTR should only be used with encrypt‑then‑MAC.
- RSA ≥2048 or modern ECC (Curve25519/Ed25519) is recommended for asymmetric algorithms. OAEP should be used for RSA encryption.
- SHA‑256+ should be used for hashing to ensure integrity; MD5/SHA‑1 should be avoided.
- A CSPRNG appropriate to the platform (e.g., SecureRandom, crypto.randomBytes, secrets module) should be used for RNG. Non‑crypto RNGs should never be used.

### Key Management
- Keys should be generated within validated modules (HSM/KMS) and should never be derived from passwords or predictable inputs.
- Keys should be separated by purpose (encryption, signing, wrapping). Keys should be rotated on compromise, cryptoperiod, or policy.
- Keys should be stored in KMS/HSM or vault; they should never be hardcoded; plain env vars should be avoided. KEK should be used to wrap DEKs; they should be stored separately.
- Access to trust stores should be controlled; updates should be validated; all key access and operations should be audited.

### Data at Rest
- Sensitive data should be encrypted; stored secrets should be minimized; tokenization should be used where possible.
- Authenticated encryption should be used; nonces/IVs should be managed properly; salts should be kept unique per item.
- Backups should be protected: they should be encrypted, access should be restricted, restores should be tested, and retention should be managed.

### TLS Configuration
- TLS 1.3 should be preferred; TLS 1.2 should only be allowed for legacy compatibility; TLS 1.0/1.1 and SSL should be disabled. TLS_FALLBACK_SCSV should be enabled.
- AEAD suites should be preferred for ciphers; NULL/EXPORT/anon should be disabled. Libraries should be kept updated; compression should be disabled.
- x25519/secp256r1 should be preferred for key exchange groups; secure FFDHE groups should be configured if needed.
- Certificates should have 2048‑bit+ keys, SHA‑256, and correct CN/SAN. The lifecycle and revocation (OCSP stapling) should be managed.
- HTTPS should be used site‑wide; HTTP→HTTPS redirects should be implemented; mixed content should be prevented; cookies should be set `Secure`.

### HSTS
- Strict‑Transport‑Security should only be sent over HTTPS. The rollout should be phased:
  - In the test phase, a short max‑age (e.g., 86400) with includeSubDomains should be used.
  - In production, a max‑age of ≥1 year should be used; includeSubDomains should be included when safe.
  - Preload should be considered once mature; the permanence and subdomain impact should be understood.

### Pinning
- Browser HPKP should be avoided. Pinning should only be considered for controlled clients (e.g., mobile) and when both ends are owned.
- SPKI pinning with backup pins should be preferred; secure update channels should be planned; user bypass should never be allowed.
- Rotation and failure handling should be thoroughly tested; operational risk should be understood.

### Implementation Checklist
- AEAD should be used everywhere; only vetted libraries should be used; custom crypto should be avoided.
- Keys should be generated and stored in KMS/HSM; they should be purpose‑scoped; rotation should be documented.
- TLS 1.3/1.2 should be used with strong ciphers; compression should be off; OCSP stapling should be on.
- HSTS should be deployed per phased plan; mixed content should be eliminated.
- Pinning should only be used where justified, with backups and update path.

### Test Plan
- Automated config scans (e.g., SSL Labs, testssl.sh) should be conducted for protocol/cipher/HSTS.
- Code reviews for crypto API misuse should be performed; tests for key rotation, backup/restore should be conducted.
- Pinning simulations for rotation/failures should be performed if deployed.