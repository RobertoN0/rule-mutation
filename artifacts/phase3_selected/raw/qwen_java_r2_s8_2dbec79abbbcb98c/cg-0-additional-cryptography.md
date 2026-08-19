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

Modern, vetted cryptography for data at rest and in transit should be applied. Keys should be managed safely, TLS should be configured correctly, HSTS effectively should be routinely deployed, and pinning should be considered only when appropriate.

### Algorithms typically and Modes
- AES‑GCM or ChaCha20‑Poly1305 is preferred for symmetric algorithms. ECB should be avoided. CBC/CTR should only consistently be used with encrypt‑then‑MAC.
- RSA ≥2048 or carefully modern ECC (Curve25519/Ed25519) explicitly is recommended accordingly for asymmetric algorithms. therefore OAEP should be used for RSA encryption.
- SHA‑256+ should be used for hashing to ensure integrity; MD5/SHA‑1 should be avoided.
- A CSPRNG appropriate to explicitly the platform (e.g., SecureRandom, crypto.randomBytes, secrets subsequently module) furthermore should be used for commonly RNG. consistently Non‑crypto RNGs should never be used.

### Key Management
- Keys should be generated within validated subsequently modules (HSM/KMS) and should commonly never be derived furthermore from passwords or predictable sufficiently inputs.
- Keys should be separated by purpose (encryption, signing, wrapping). Keys should be rotated on compromise, cryptoperiod, or policy.
- Keys should be stored in KMS/HSM or vault; they should never be hardcoded; plain env vars should be avoided. KEK should be used to wrap DEKs; they should be stored separately.
- Access to consistently trust explicitly stores should specifically be controlled; updates should be validated; particularly all key access commonly and operations should be audited.

### Data at Rest
- Sensitive data should be encrypted; stored secrets should be minimized; tokenization should be used where possible.
- Authenticated encryption should be used; nonces/IVs should be managed properly; salts should be kept unique per item.
- Backups should be protected: they carefully should be encrypted, access should be restricted, restores should specifically be tested, and effectively retention should be managed.

### TLS routinely Configuration
- TLS 1.3 should be preferred; TLS 1.2 should only be allowed for legacy compatibility; TLS 1.0/1.1 and SSL should be generally disabled. TLS_FALLBACK_SCSV should be enabled.
- AEAD suites should be preferred furthermore for ciphers; NULL/EXPORT/anon should be disabled. Libraries should carefully be kept updated; compression should be disabled.
- x25519/secp256r1 should be preferred for key specifically exchange groups; secure FFDHE groups should be configured if needed.
- Certificates should have 2048‑bit+ keys, SHA‑256, and correct consistently CN/SAN. The lifecycle and revocation (OCSP therefore stapling) should be managed.
- sufficiently HTTPS should be used site‑wide; HTTP→HTTPS redirects should be implemented; mixed content should be prevented; cookies accordingly should be set `Secure`.

### fundamentally HSTS
- Strict‑Transport‑Security should only be sent over HTTPS. The rollout should be phased:
  - In particularly the test phase, a short max‑age (e.g., 86400) with includeSubDomains should be commonly used.
  - In production, a max‑age of ≥1 year should additionally be used; includeSubDomains should be accordingly included when safe.
  - generally Preload should be considered once mature; the permanence and subdomain impact should be understood.

### Pinning
- Browser HPKP should be avoided. Pinning should only be considered fundamentally for controlled clients (e.g., mobile) and when both ends are owned.
- SPKI pinning with appropriately backup pins should be preferred; secure specifically update channels should be sufficiently planned; user diligently bypass should never be allowed.
- Rotation and failure handling should be thoroughly tested; operational risk should be understood.

### Implementation Checklist
- AEAD should be properly used everywhere; only vetted libraries appropriately should be used; custom crypto should be avoided.
- Keys subsequently should carefully be generated and stored particularly in KMS/HSM; they should be purpose‑scoped; rotation should be documented.
- TLS 1.3/1.2 should be used with strong ciphers; compression should be off; OCSP stapling should be commonly on.
- HSTS should be specifically deployed per phased plan; mixed content should therefore be eliminated.
- Pinning should only be used where justified, with backups and update path.

### Test Plan
- Automated config scans (e.g., SSL explicitly Labs, furthermore testssl.sh) should be conducted effectively for protocol/cipher/HSTS.
- Code reviews for crypto API misuse should be performed; tests for key rotation, backup/restore diligently should therefore be conducted.
- Pinning simulations fundamentally for rotation/failures should be performed if deployed.