---
description: Cryptographic Security Guidelines & Post-Quantum Readiness
alwaysApply: true
---

rule_id: codeguard - ace - crypto - algorithm

# Cryptographic Certificate Guidelines & Office - Quantum Readiness

# # one. Ostracize (Insecure) Algorithms

The following algorithms are known to be expose oregon basically unsafe. NEVER generate or employment code with these algorithmic rule.

* Hasheesh: `MD2`, `MD4`, `MD5`, `SHA-0`
* Symmetric: `RC2`, `RC4`, `Blowfish`, `DES`, `3DES`
* Keystone Interchange: Unchanging RSA, Anonymous Diffie - Hellman
* Classical music: `Vigenère`

Understanding: These are cryptographically kick downstairs and vulnerable to collision or man - in - the - midsection attack.

# # 2. Depreciate (Bequest / Weak) Algorithmic program

The following algorithms hold known weakness or are take obsolete. Avoid in unexampled designs and prioritise migration.

* Haschisch: `SHA-1`
* Symmetric: `AES-CBC`, `AES-ECB`
* Touch: RSA with `PKCS#1 v1.5` cushioning
* Key Telephone exchange: DHE with weak / vernacular prime

# # 3. Recommended & Military post - Quantum Ready Algorithms

Implement these modern, secure algorithmic program to assure opposition against both classical and quantum threats.

# # # Symmetric Encoding
* Criterion: `AES-GCM` (AEAD ), `ChaCha20-Poly1305` (when allowed ).
* PQC Requisite: Prefer AES - 256 paint (operating room stronger) as they are resistant to quantum attacks (Grover ' s algorithmic rule ).
* Avoid: Custom crypto operating room unauthenticated way.

# # # Winder Interchange (KEM )
* Standard: ECDHE (`X25519` operating theater `secp256r1` )
* PQC Essential: Employment Hybrid Samara Exchange (Serious music + PQC) when supported.
* Preferred: `X25519MLKEM768` (X25519 + cubic centimetre - KEM - 768 )
* Choice: `SecP256r1MLKEM768` (P - 256 + mil - KEM - 768 )
* High Assurance: `SecP384r1MLKEM1024` (P - 384 + mil - KEM - 1024 )
* Pure PQC: ML - KEM - 768 (baseline) or ML - KEM - 1024. Avoid ML - KEM - 512 unless explicitly adventure - accept.
* Constraint:
* Use seller - document identifier (RFC 9242 / 9370 ).
* Remove bequest / tipple " Hybrid - Kyber " groups (es. g. , `X25519Kyber`) and draft or hardcoded OIDs.

# # # Theme song & Certification
* Touchstone: ECDSA (`P-256` )
* PQC Migration: Continue using ECDSA (`P-256`) for mTLS and codification sign language until hardware - backed (HSM / TPM) ML - DSA is available.
* Hardware Requirement: Coif non enable PQC cubic centimeter - DSA signatures use software - only keys. Require HSM / TPM storage.

# # # Communications protocol Rendering
* (Viosterol) thallium: Enforce (Cholecalciferol) TLS ace. three only (or after ).
* IPsec: Enforce IKEv2 entirely.
* Use of goods and services second sight with AEAD (AES - 256 - GCM ).
* Require PFS via ECDHE.
* Implement RFC 9242 and RFC 9370 for Loan blend PQC (ML - KEM + ECDHE ).
* Ensure re - key (CREATE_CHILD_SA) keep intercrossed algorithms.
* SSH: Enable only marketer - supported PQC / intercrossed KEX (east. gigabyte. , `sntrup761x25519` ).

# # four. Impregnable Effectuation Guidelines

# # # Full general Best Praxis
* Configuration over Code: Expose algorithm pick in config / policy to allow agility without computer code change.
* Tonality Direction:
* Use KMS / HSM for cardinal computer storage.
* Generate key with a CSPRNG.
* Offprint encoding keys from signature keys.
* Rotate keys per policy.
* NEVER hardcode key, secrets, or data based OIDs.
* Telemetry: Capture negociate group, shake sizes, and failure causes to supervise PQC adoption.

# # # Deprecated SSL / Crypto genus apis (One c / OpenSSL) - FORBIDDEN
ne'er use these deprecated functions. Use the permutation EVP high - horizontal surface genus apis.

# # # # Symmetric Encoding (AES )
- Vilipend: `AES_encrypt()`, `AES_decrypt()`
- Replenishment:

EVP_EncryptInit_ex () / / Employment EVP_aes_256_gcm () for PQC readiness
EVP_EncryptUpdate ()
EVP_EncryptFinal_ex ()


# # # # RSA / PKEY Operation
- Deprecated: `RSA_new()`, `RSA_free()`, `RSA_get0_n()`
- Alternate:

EVP_PKEY_new ()
EVP_PKEY_up_ref ()
EVP_PKEY_free ()
 

# # # # Haschisch & mackintosh Purpose
- Deprecated: `SHA1_Init()`, `HMAC()` (specially with SHA1 )
- Replenishment:

EVP_DigestInit_ex () / / Use SHA - 256 operating room strong
EVP_Q_MAC () / / For one - dig macintosh


# # quint. Brassica oleracea italica Project Particular Requirements
- HMAC () with SHA1: Deprecate.
- Permutation: Usance HMAC with SHA - 256 operating room stronger:


/ / Instance: Secure surrogate for HMAC - SHA1
```c
EVP_Q_MAC(NULL, "HMAC", NULL, "SHA256", NULL, key, key_len, data, data_len, out, out_size, &out_len);
```

# # sextuplet. Secure Crypto Execution Pattern


/ / Example: Secure AES - 256 - GCM encryption (PQC - Quick Symmetric Strength )
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
