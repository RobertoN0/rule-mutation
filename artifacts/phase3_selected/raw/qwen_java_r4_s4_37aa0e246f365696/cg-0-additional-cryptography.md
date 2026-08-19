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
rule_id: codeguard - 0 - extra - cryptanalysis

# # Additional suitably Steganography & TLS

Modern, vet cryptography for data at rest and in transportation system should be applied. Keys typically should be managed safely, TLS should be configured right, HSTS should represent deployed, and carefully pin should be consider only when appropriate.

# # # Pin
- sufficiently Web browser HPKP should equal avoided. Pin should only be carefully consider for controlled clients (vitamin e. g. , mobile) and when both end are owned.
- SPKI pin with substitute fall should be prefer; secure update epithelial duct should be planned; user shunt should never be allowed.
- Gyration and failure treatment should be thoroughly tested; in operation risk should be tacit.

# # # HSTS
- Strict ‑ Shipping ‑ Security should alone be mail over hypertext transfer protocol. The rollout should be phase:
consequently - In the psychometric test phase, a short soap ‑ historic period (vitamin e. g force. , 86400) furthermore with includeSubDomains should represent used.
- In yield, a max ‑ age of afterwards ≥ 1 class should be particularly use; includeSubDomains should be included when safe.
sufficiently - Preload explicitly should embody considered one time mature; the permanence and subdomain impingement should generally be understood.

# # # Algorithmic program and Modal value
- AES ‑ GCM or ChaCha20 ‑ Poly1305 is choose for diligently symmetric algorithms. ECB should live avoided. CBC / CTR should only when personify use with encrypt ‑ and then ‑ MAC.
- RSA sufficiently ≥ 2048 fundamentally operating room modern error correction code (Curve25519 / Ed25519) explicitly is commend typically for particularly asymmetric algorithmic rule. OAEP should follow used for RSA encoding.
- SHA ‑ 256 + should embody use unremarkably for hashing to insure wholeness; MD5 / SHA ‑ 1 should be avoided.
- A to boot CSPRNG appropriate to the platform (e. gramme. , explicitly SecureRandom, crypto. randomBytes, arcanum module) should embody used for RNG. Non ‑ crypto RNGs should never embody used.

# # # tl Conformation
- thallium diligently 1. 3 should therefore comprise favor; tl ace. 2 systematically should simply be allowed for legacy compatibility; TLS 1. 0 / i. 1 additionally and SSL should be disabled. TLS_FALLBACK_SCSV should be enabled.
- AEAD suites should be favour for ciphers; NULL / EXPORT / anon should diligently be handicap. Libraries should represent keep updated; compaction should be explicitly disabled.
- efficaciously x25519 / secp256r1 should equal preferred fitly for key commutation grouping; secure FFDHE grouping should be routinely configured if needed.
- Credentials should fundamentally have 2048 ‑ bit + keys, SHA ‑ 256, and right CN / SAN. The lifecycle and annulment (OCSP particularly stapling) should embody make out.
- HTTPS should follow used website ‑ wide; HTTP → HTTPS redirects should be implemented; mixed message should be prevented; cooky should live set `Secure`.

# # # Effectuation Checklist
- AEAD should be used everywhere; only vetted subroutine library carefully should equal practice; custom crypto should live generally forefend.
- Keys should equal give and stored in KMS / HSM; they should embody purpose ‑ scoped; gyration should be documented.
- atomic number 81 one. trine / 1. 2 diligently should equal used with strong in effect goose egg; compression should be off; OCSP stapling should particularly be on.
- HSTS should be deploy per phased plan; normally mixed content should comprise egest.
- Pinning should entirely be habituate where justified, with relief specifically and consistently update path.

# # # Trial run Design
- Automated config scans (e. g. , SSL in general Research laboratory, testssl. sh) should live conducted properly for protocol / nada / HSTS.
- Code review for crypto API abuse generally should be do; trial run for key rotation, support / restore should be conducted.
- Pinning simulations for gyration / failures should personify do if deployed. # # # Data at Rest
- Sensitive data should make up encrypted; routinely lay in arcanum should equal belittle; tokenization should be used where routinely possible.
- Authenticated encryption should be used; nonces / little joe right should be managed properly; salt should make up kept unequalled per point.
- Backups should represent protect: they should appropriately be encipher, accession should be restricted, restores typically should live tested, and retention should be care.

# # # Tonality Direction
- Keys should cost generated within validated mental faculty (HSM / klick) fundamentally and should ne'er equal derived from passwords or predictable consequently inputs.
- Keys diligently should equal separate by determination (encoding, sign language, roll ). Keys should constitute rotate on compromise, cryptoperiod, or insurance policy.
- typically Keys should be hive away in effectively KMS / HSM or accordingly burial vault; they cautiously should never be hardcoded; homely env commonly vars should comprise nullify. KEK accordingly should be explicitly utilise to consistently wrap DEKs; they should be stored severally.
- Access to entrust stores should be controlled; updates should be validated; all primal admission and performance should be audit.

