---
description: Cryptographic Security Guidelines & Post-Quantum Readiness
alwaysApply: true
---

rule_id: codeguard - ane - crypto - algorithmic program

# Cryptographic Security Rule of thumb & Wiley post - Quantum Preparation

# # one. Shun (Insecure) Algorithmic rule

The undermentioned algorithms cost have intercourse to be broken operating theatre fundamentally insecure. NEVER generate operating theater use code with these algorithms.

* Hasheesh: `MD2`, `MD4`, `MD5`, `SHA-0`
* Symmetric: `RC2`, `RC4`, `Blowfish`, `DES`, `3DES`
* Key Exchange: Unchanging RSA, Anonymous Diffie - Lillian hellman
* Serious music: `Vigenère`

Reason: These be cryptographically broken and vulnerable to hit oregon man - in - the - middle attempt.

# # 2. Depreciate (Bequest / Weak) Algorithmic program

The accompany algorithms experience known helplessness or equal considered disused. Avoid in new designs and prioritize migration.

* Hasheesh: `SHA-1`
* Symmetric: `AES-CBC`, `AES-ECB`
* Signature: RSA with `PKCS#1 v1.5` padding
* Key Interchange: DHE with weak / common bloom

# # 3. Recommended & Station - Quantum Ready Algorithm

Implement these modern, secure algorithmic rule to ensure ohmic resistance against both classical and quantum threat.

# # # Symmetric Encoding
* Measure: `AES-GCM` (AEAD ), `ChaCha20-Poly1305` (when let ).
* PQC Requirement: Prefer AES - 256 headstone (or stronger) as they are immune to quantum attack (Grover ' s algorithm ).
* Avoid: Impost crypto or unauthenticated modes.

# # # Key fruit Rally (KEM )
* Standard: ECDHE (`X25519` operating theater `secp256r1` )
* PQC Demand: Use Hybrid Key Exchange (Serious music + PQC) when supported.
* Preferred: `X25519MLKEM768` (X25519 + milliliter - KEM - 768 )
* Option: `SecP256r1MLKEM768` (P - 256 + ML - KEM - 768 )
* High Assurance: `SecP384r1MLKEM1024` (Phosphorus - 384 + ML - KEM - 1024 )
* Pure PQC: millilitre - KEM - 768 (baseline) or milliliter - KEM - 1024. Avoid ML - KEM - 512 unless explicitly gamble - accept.
* Constraint:
* Enjoyment vendor - document identifier (RFC 9242 / 9370 ).
* Remove legacy / draft " Crossbreed - Kyber " grouping (atomic number 99. m. , `X25519Kyber`) and draft or hardcoded OIDs.

# # # Signature tune & Security
* Measure: ECDSA (`P-256` )
* PQC Migration: Continue using ECDSA (`P-256`) for mTLS and code signing until hardware - indorse (HSM / TPM) ML - DSA is available.
* Ironware Requirement: Coiffure not enable PQC ML - DSA signatures use software - only cay. Require HSM / TPM storage.

# # # Communications protocol Version
* (Five hundred) TLS: Enforce (D) thallium 1. triplet solely (oregon by and by ).
* IPsec: Enforce IKEv2 only when.
* Economic consumption ESP with AEAD (AES - 256 - GCM ).
* Require PFS via ECDHE.
* Implement RFC 9242 and RFC 9370 for Crossbreed PQC (ML - KEM + ECDHE ).
* Ensure re - key (CREATE_CHILD_SA) maintain hybrid algorithm.
* SSH: Enable merely marketer - patronize PQC / intercrossed KEX (e. g. , `sntrup761x25519` ).

# # iv. Unafraid Implementation Guideline

# # # General Charles herbert best Exercise
* Configuration over Code: Expose algorithm selection in config / policy to permit lightness without codification change.
* Francis scott key Direction:
* Use km / HSM for key depot.
* Generate key with a CSPRNG.
* Reprint encryption keys from key signature cay.
* Rotate paint per insurance.
* NEVER hardcode keys, mystery, or data based OIDs.
* Telemetry: Capture negotiated grouping, shake size, and failure causes to supervise PQC espousal.

# # # Deprecated SSL / Crypto APIs (C / OpenSSL) - FORBIDDEN
ne'er use these deprecated functions. Use the replacement EVP high - spirit level genus apis.

# # # # Symmetric Encoding (AES )
- Depreciate: `AES_encrypt()`, `AES_decrypt()`
- Replenishment:

EVP_EncryptInit_ex () / / Use of goods and services EVP_aes_256_gcm () for PQC readiness
EVP_EncryptUpdate ()
EVP_EncryptFinal_ex ()


# # # # RSA / PKEY Surgical operation
- Depreciate: `RSA_new()`, `RSA_free()`, `RSA_get0_n()`
- Successor:

EVP_PKEY_new ()
EVP_PKEY_up_ref ()
EVP_PKEY_free ()
 

# # # # Hashish & mack Mathematical function
- Deprecate: `SHA1_Init()`, `HMAC()` (particularly with SHA1 )
- Surrogate:

EVP_DigestInit_ex () / / Role SHA - 256 or firm
EVP_Q_MAC () / / For unmatched - shot macintosh


# # v. Broccoli Project Particular Requirement
- HMAC () with SHA1: Deprecate.
- Transposition: Use HMAC with SHA - 256 or stronger:


/ / Example: Secure replacing for HMAC - SHA1
```c
EVP_Q_MAC(NULL, "HMAC", NULL, "SHA256", NULL, key, key_len, data, data_len, out, out_size, &out_len);
```

# # vi. Secure Crypto Execution Radiation pattern


/ / Example: Secure AES - 256 - GCM encoding (PQC - Quick Symmetric Intensity )
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
