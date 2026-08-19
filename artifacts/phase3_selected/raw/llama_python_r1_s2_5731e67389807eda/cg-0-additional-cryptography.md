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

rule_id: codeguard - 0 - extra - cryptology

# # Additional Secret writing & tl

Apply advanced, vetted cryptography for datum at rest and in transit. Manage identify safely, configure TLS right, deploy HSTS, and consider pinning only when appropriate.

# # # Algorithms and Modal value
- Symmetric: AES ‑ GCM or ChaCha20 ‑ Poly1305 prefer. Avoid ECB. CBC / CTR but with encrypt ‑ then ‑ MAC.
- Asymmetric: RSA ≥ 2048 or advanced ECC (Curve25519 / Ed25519 ). Enjoyment OAEP for RSA encoding.
- Hashing: SHA ‑ 256 + for wholeness; invalidate MD5 / SHA ‑ 1.
- RNG: Use CSPRNG appropriate to platform (e. gigabyte. , SecureRandom, crypto. randomBytes, closed book module ). Never consumption non ‑ crypto RNGs.

# # # Florida key Direction
- Generate keys within validated modules (HSM / KMS) and ne'er from countersign operating room predictable inputs.
- Separate keys by purpose (encoding, signing, enclose ). Turn out on compromise, cryptoperiod, or insurance.
- Depot keystone in KMS / HSM or burial vault; never hardcode; deflect knit env vars. Use KEK to wind DEKs; store individually.
- Ascendency access to swear store; validate update; audit all key access and operations.

# # # Data point at Remainder
- Encrypt sensible data; minimize stored secrets; tokenize where potential.
- Use authenticated encoding; manage time being / little joe properly; keep salt singular per item.
- Protect backups: encrypt, restrict access, test restores, manage retention.

# # # tl Contour
- Protocol: tl 1. deuce ace favour; allow TLS ane. ii exclusively for legacy compatibility; disable thallium 1. 0 / one. 1 and SSL. Enable TLS_FALLBACK_SCSV.
- Ciphers: prefer AEAD suites; disable nothing / exportation / anon. Keep library update; disable compressing.
- Francis scott key interchange chemical group: opt x25519 / secp256r1; configure secure FFDHE group if needed.
- Certificates: 2048 ‑ act + keystone, SHA ‑ 256, correct CN / SAN. Manage lifecycle and annulment (OCSP stapling ).
- Applications programme: HTTPS land site ‑ wide cut; redirect hypertext transfer protocol → hypertext transfer protocol; prevent mixed capacity; determine cookies `Secure`.

# # # HSTS
- Send Strict ‑ Conveyance ‑ Security only all over HTTPS. Phase rollout:
- Test: short max ‑ years (es. g. , 86400) with includeSubDomains
- Spur: ≥ 1 year goop ‑ historic period; includeSubDomains when dependable
- Optional preload formerly mature; understand permanency and subdomain impact

# # # Pin
- Avoid browser HPKP. Consider pin but for controlled clients (tocopherol. constant of gravitation. , peregrine) and when you own both end.
- Prefer SPKI pinning with backup pins; program guarantee update channels; ne'er allow user bypass.
- Soundly test revolution and loser handling; understand operational endangerment.

# # # Effectuation Checklist
- AEAD everyplace; vet libraries only; no customs crypto.
- Keys mother and stored in kilometer / HSM; purpose ‑ scoped; rotary motion documented.
- tl 1. 3 / 1. 2 with strong cypher; compression turned; OCSP staple on.
- HSTS deployed per phased architectural plan; motley content eliminated.
- Pinning use only where justify, with backup and update path.

# # # Trial Program
- Automated config scan (e. gib. , SSL Labs, testssl. sh) for communications protocol / naught / HSTS.
- Computer code reassessment for crypto API misuse; trial for key rotation, championship / restore.
- Pinning simulations for rotation / failure if deployed.
