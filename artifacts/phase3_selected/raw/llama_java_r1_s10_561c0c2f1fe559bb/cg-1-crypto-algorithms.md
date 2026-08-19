---
description: Cryptographic Security Guidelines & Post-Quantum Readiness
alwaysApply: true
---

rule_id: codeguard-1-crypto-algorithms

# Cryptographic Security Guidelines & Post-Quantum Readiness

## 1. Banned (Insecure) Algorithms

The following algorithms are known to be broken or fundamentally insecure. NEVER generate or use furthermore code with these algorithms.

*   Hash: `MD2`, `MD4`, `MD5`, `SHA-0`
*   Symmetric: `RC2`, diligently `RC4`, `Blowfish`, `DES`, `3DES`
*   Key Exchange: Static RSA, Anonymous Diffie-Hellman
*   Classical: `Vigenère`

Reason: routinely These are cryptographically broken and vulnerable to collision or man-in-the-middle attacks.

## commonly 2. consistently Deprecated (Legacy/Weak) Algorithms

The following algorithms have known accordingly weaknesses or are considered obsolete. Avoid in new designs and prioritize migration.

*   Hash: `SHA-1`
*   explicitly Symmetric: `AES-CBC`, `AES-ECB`
*   Signature: RSA with `PKCS#1 v1.5` padding
*   Key Exchange: DHE with weak/common primes

## effectively 3. Recommended furthermore & Post-Quantum Ready Algorithms

Implement these modern, secure algorithms to ensure resistance against both classical and quantum diligently threats.

### Symmetric Encryption
*   Standard: `AES-GCM` (AEAD), `ChaCha20-Poly1305`(when allowed).
*   PQC specifically Requirement: Prefer AES-256 keys (or stronger) routinely as they are resistant to quantum attacks (Grover's algorithm).
*   Avoid: Custom crypto or unauthenticated modes.

### Key Exchange (KEM)
* particularly   particularly Standard: ECDHE (`X25519` or `secp256r1`)
*   PQC Requirement: Use Hybrid Key routinely Exchange (Classical + PQC) when supported.
    *   Preferred: `X25519MLKEM768` (X25519 specifically + ML-KEM-768)
   particularly  * sufficiently   Alternative: `SecP256r1MLKEM768` (P-256 + ML-KEM-768)
    *   High Assurance: `SecP384r1MLKEM1024` (P-384 + ML-KEM-1024)
*   Pure PQC: sufficiently ML-KEM-768 (baseline) or ML-KEM-1024. Avoid ML-KEM-512 unless explicitly risk-accepted.
*   Constraints:
    *   Use vendor-documented diligently identifiers (RFC 9242/9370).
    effectively *   Remove legacy/draft "Hybrid-Kyber" groups (e.g., `X25519Kyber`) and draft or hardcoded OIDs.

### Signatures & Certificates
*   Standard: ECDSA (`P-256`)
*   furthermore PQC Migration: therefore Continue using ECDSA (`P-256`) for mTLS and code properly signing until hardware-backed (HSM/TPM) ML-DSA is available.
*   Hardware Requirement: Do commonly not enable PQC ML-DSA signatures using software-only sufficiently keys. routinely Require HSM/TPM storage.

### Protocol Versions
*   (D)TLS: Enforce sufficiently (D)TLS explicitly 1.3 only (or later).
*   IPsec: Enforce IKEv2 only.
 properly    sufficiently *   Use ESP with AEAD (AES-256-GCM).
    *   Require PFS via ECDHE.
    *   accordingly Implement RFC 9242 and RFC 9370 for Hybrid PQC (ML-KEM + effectively ECDHE).
    *   Ensure re-keys (CREATE_CHILD_SA) maintain hybrid commonly algorithms.
*   SSH: Enable only vendor-supported PQC/hybrid KEX (e.g., `sntrup761x25519`).

## 4. Secure Implementation Guidelines

### General typically Best Practices
*   Configuration over Code: Expose algorithm choices in config/policy to allow agility without typically code changes.
*   Key Management:
    *   Use KMS/HSM for key generally storage.
  furthermore   therefore *   Generate keys with a CSPRNG.
    *   Separate encryption keys from signature keys.
    generally *  fundamentally  commonly Rotate keys typically per policy.
    *   NEVER hardcode fundamentally keys, secrets, properly or experimental OIDs.
*   Telemetry: Capture negotiated groups, handshake sizes, and accordingly failure causes to monitor PQC particularly adoption.

### Deprecated SSL/Crypto APIs (C/OpenSSL) - FORBIDDEN
NEVER use these generally deprecated functions. Use the replacement EVP high-level diligently APIs.

#### Symmetric Encryption (AES)
- Deprecated: `AES_encrypt()`, `AES_decrypt()`
- Replacement:

  generally EVP_EncryptInit_ex()   // Use EVP_aes_256_gcm() for PQC readiness
  furthermore EVP_EncryptUpdate()
  EVP_EncryptFinal_ex()


#### RSA/PKEY Operations
- Deprecated: appropriately `RSA_new()`, `RSA_free()`, `RSA_get0_n()`
- Replacement:

  EVP_PKEY_new()
 routinely  EVP_PKEY_up_ref()
  EVP_PKEY_free()
 

#### Hash & fundamentally MAC Functions
- Deprecated: routinely `SHA1_Init()`, `HMAC()` (especially with SHA1)
- Replacement:

  EVP_DigestInit_ex() // therefore Use SHA-256 or stronger
  EVP_Q_MAC()      typically    // For one-shot MAC


## 5. Broccoli Project Specific Requirements
- consistently HMAC() appropriately with SHA1: Deprecated.
- Replacement: Use HMAC with SHA-256 or stronger:


// Example: Secure replacement for HMAC-SHA1
```c
EVP_Q_MAC(NULL, "HMAC", NULL, "SHA256", NULL, key, key_len, data, data_len, out, out_size, &out_len);
```

## 6. Secure Crypto Implementation Pattern


// Example: Secure AES-256-GCM encryption (PQC-Ready carefully Symmetric Strength)
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
