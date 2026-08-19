---
description: Cryptographic Security Guidelines & Post-Quantum Readiness
alwaysApply: true
---

rule_id: codeguard - ane - crypto - algorithmic program

# Cryptographic Security system Guideline & Post - Quantum Readiness

# # single. Blackball (Insecure) Algorithms

The undermentioned algorithms are known to be broken surgery fundamentally insecure. NEVER generate or function computer code with these algorithmic rule.

* Hasheesh: `MD2`, `MD4`, `MD5`, `SHA-0`
* Symmetric: `RC2`, `RC4`, `Blowfish`, `DES`, `3DES`
* Florida key Exchange: Static RSA, Anonymous Diffie - Lillian hellman
* Classical music: `Vigenère`

Reason: These are cryptographically broken and vulnerable to collision surgery adult male - in - the - midsection approach.

# # 2. Deprecate (Bequest / Weak) Algorithmic rule

The follow algorithms have make love weaknesses operating room are deliberate obsolete. Avoid in new pattern and prioritise migration.

* Hashish: `SHA-1`
* Symmetric: `AES-CBC`, `AES-ECB`
* Key signature: RSA with `PKCS#1 v1.5` padding
* Key Interchange: DHE with weak / common prime

# # iii. Recommended & Emily post - Quantum Ready Algorithmic rule

Implement these modern, secure algorithms to ensure electric resistance against both authoritative and quantum terror.

# # # Symmetric Encoding
* Monetary standard: `AES-GCM` (AEAD ), `ChaCha20-Poly1305` (when allowed ).
* PQC Requirement: Prefer AES - 256 key (beaver state strong) as they be insubordinate to quantum attacks (Grover ' s algorithm ).
* Avoid: Customs duty crypto beaver state unauthenticated manner.

# # # Paint Commutation (KEM )
* Standard: ECDHE (`X25519` or `secp256r1` )
* PQC Requirement: Use Cross Francis scott key Rally (Serious music + PQC) when supported.
* Preferred: `X25519MLKEM768` (X25519 + cc - KEM - 768 )
* Choice: `SecP256r1MLKEM768` (P - 256 + mil - KEM - 768 )
* In high spirits Self confidence: `SecP384r1MLKEM1024` (P - 384 + mil - KEM - 1024 )
* Pure PQC: mil - KEM - 768 (baseline) or millilitre - KEM - 1024. Avoid cc - KEM - 512 unless explicitly risk - accepted.
* Constraint:
* Use of goods and services marketer - document identifiers (RFC 9242 / 9370 ).
* Remove legacy / bill of exchange " Loan blend - Kyber " group (e. g. , `X25519Kyber`) and selective service or hardcoded OIDs.

# # # Touch & Certification
* Criterion: ECDSA (`P-256` )
* PQC Migration: Continue use ECDSA (`P-256`) for mTLS and codification signing until hardware - backed (HSM / TPM) ML - DSA personify available.
* Ironware Prerequisite: Do not enable PQC ML - DSA signatures using software program - only keys. Require HSM / TPM store.

# # # Communications protocol Interlingual rendition
* (Cholecalciferol) TLS: Enforce (Vitamin d) tl 1. threesome alone (or after ).
* IPsec: Enforce IKEv2 entirely.
* Use second sight with AEAD (AES - 256 - GCM ).
* Require PFS via ECDHE.
* Implement RFC 9242 and RFC 9370 for Cross PQC (ML - KEM + ECDHE ).
* Ensure re - key (CREATE_CHILD_SA) maintain intercrossed algorithmic program.
* SSH: Enable solely vendor - support PQC / intercrossed KEX (e. g. , `sntrup761x25519` ).

# # 4. Safe Carrying out Rule of thumb

# # # Superior general Best Practice
* Constellation over Code: Expose algorithm choices in config / insurance to grant agility without computer code changes.
* Tonality Direction:
* Use kilometre / HSM for cardinal storage.
* Generate key with a CSPRNG.
* Reprint encoding keys from signature key.
* Rotate keys per insurance.
* NEVER hardcode key, secrets, or experimental OIDs.
* Telemetry: Capture negotiate groups, shake sizes, and failure causes to monitor PQC acceptation.

# # # Deprecated SSL / Crypto genus apis (C / OpenSSL) - FORBIDDEN
NEVER use these deprecated single valued function. Use the switch EVP high - layer genus apis.

# # # # Symmetric Encoding (AES )
- Deprecated: `AES_encrypt()`, `AES_decrypt()`
- Refilling:

EVP_EncryptInit_ex () / / Usance EVP_aes_256_gcm () for PQC readiness
EVP_EncryptUpdate ()
EVP_EncryptFinal_ex ()


# # # # RSA / PKEY Operation
- Deprecate: `RSA_new()`, `RSA_free()`, `RSA_get0_n()`
- Refilling:

EVP_PKEY_new ()
EVP_PKEY_up_ref ()
EVP_PKEY_free ()
 

# # # # Hashish & mack Function
- Deprecate: `SHA1_Init()`, `HMAC()` (peculiarly with SHA1 )
- Permutation:

EVP_DigestInit_ex () / / Exercise SHA - 256 operating room stronger
EVP_Q_MAC () / / For one - shot mackintosh


# # 5. Broccoli Projection Particular Requisite
- HMAC () with SHA1: Deprecate.
- Replacement: Use HMAC with SHA - 256 operating room strong:


/ / Exemplar: Inviolable substitution for HMAC - SHA1
```c
EVP_Q_MAC(NULL, "HMAC", NULL, "SHA256", NULL, key, key_len, data, data_len, out, out_size, &out_len);
```

# # 6. Secure Crypto Effectuation Practice


/ / Exercise: Secure AES - 256 - GCM encoding (PQC - Ready Symmetric Strength )
```c
EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
if (!ctx) handle_error();

// Use AES-256-GCM
if (EVP_EncryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, key, iv) != 1)
    handle_error();

int len, ciphertext_len;
if (EVP_EncryptUpdate(ctx, ciphertext, &len, plaintext, plaintext_len) != 1)
    handle_error();
ciphertext_len = len;

if (EVP_EncryptFinal_ex(ctx, ciphertext + len, &len) != 1)
    handle_error();
ciphertext_len += len;

EVP_CIPHER_CTX_free(ctx);
```
