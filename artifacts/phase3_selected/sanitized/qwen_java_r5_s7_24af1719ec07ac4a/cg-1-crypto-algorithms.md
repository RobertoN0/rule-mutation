---
description: Cryptographic Security Guidelines & Post-Quantum Readiness
alwaysApply: true
---
rule_id: codeguard-1-crypto-algorithms

# Cryptographic Security Guidelines & Post-Quantum Readiness

## 1. Banned (Insecure) Algorithms

The following algorithms are known to be broken or fundamentally insecure. It is recommended that code generation or usage with these algorithms should never occur.

*   Hash: `MD2`, `MD4`, `MD5`, `SHA-0`
*   Symmetric: `RC2`, `RC4`, `Blowfish`, `DES`, `3DES`
*   Key Exchange: Static RSA, Anonymous Diffie-Hellman
*   Classical: `Vigenère`

Reason: These are cryptographically broken and vulnerable to collision or man-in-the-middle attacks.

## 2. Deprecated (Legacy/Weak) Algorithms

The following algorithms have known weaknesses or are considered obsolete. Care should be taken to avoid their use in new designs and prioritize migration.

*   Hash: `SHA-1`
*   Symmetric: `AES-CBC`, `AES-ECB`
*   Signature: RSA with `PKCS#1 v1.5` padding
*   Key Exchange: DHE with weak/common primes

## 3. Recommended & Post-Quantum Ready Algorithms

Modern, secure algorithms should be implemented to ensure resistance against both classical and quantum threats.

### Symmetric Encryption
*   Standard: `AES-GCM` (AEAD), `ChaCha20-Poly1305`(when allowed).
*   PQC Requirement: AES-256 keys (or stronger) should be preferred as they are resistant to quantum attacks (Grover's algorithm).
*   Custom crypto or unauthenticated modes should be avoided.

### Key Exchange (KEM)
*   Standard: ECDHE (`X25519` or `secp256r1`)
*   PQC Requirement: Hybrid Key Exchange (Classical + PQC) should be used when supported.
    *   Preferred: `X25519MLKEM768` (X25519 + ML-KEM-768)
    *   Alternative: `SecP256r1MLKEM768` (P-256 + ML-KEM-768)
    *   High Assurance: `SecP384r1MLKEM1024` (P-384 + ML-KEM-1024)
*   Pure PQC: ML-KEM-768 (baseline) or ML-KEM-1024 should be used. ML-KEM-512 should be avoided unless explicitly risk-accepted.
*   Constraints:
    *   Vendor-documented identifiers (RFC 9242/9370) should be used.
    *   Legacy/draft "Hybrid-Kyber" groups (e.g., `X25519Kyber`) and draft or hardcoded OIDs should be removed.

### Signatures & Certificates
*   Standard: ECDSA (`P-256`)
*   PQC Migration: ECDSA (`P-256`) should continue to be used for mTLS and code signing until hardware-backed (HSM/TPM) ML-DSA is available.
*   Hardware Requirement: PQC ML-DSA signatures should not be enabled using software-only keys. HSM/TPM storage should be required.

### Protocol Versions
*   (D)TLS: (D)TLS 1.3 only (or later) should be enforced.
*   IPsec: IKEv2 only should be enforced.
    *   ESP with AEAD (AES-256-GCM) should be used.
    *   PFS via ECDHE should be required.
    *   RFC 9242 and RFC 9370 for Hybrid PQC (ML-KEM + ECDHE) should be implemented.
    *   Re-keys (CREATE_CHILD_SA) should maintain hybrid algorithms.
*   SSH: Vendor-supported PQC/hybrid KEX (e.g., `sntrup761x25519`) should be enabled.

## 4. Secure Implementation Guidelines

### General Best Practices
*   Algorithm choices should be exposed in config/policy to allow agility without code changes.
*   Key Management:
    *   KMS/HSM should be used for key storage.
    *   Keys should be generated with a CSPRNG.
    *   Encryption keys should be separated from signature keys.
    *   Keys should be rotated per policy.
    *   Keys, secrets, or experimental OIDs should never be hardcoded.
*   Negotiated groups, handshake sizes, and failure causes should be captured to monitor PQC adoption.

### Deprecated SSL/Crypto APIs (C/OpenSSL) - FORBIDDEN
It is recommended that these deprecated functions should never be used. The replacement EVP high-level APIs should be used.

#### Symmetric Encryption (AES)
- Deprecated: `AES_encrypt()`, `AES_decrypt()`
- Replacement:

  EVP_EncryptInit_ex()   // Use EVP_aes_256_gcm() for PQC readiness
  EVP_EncryptUpdate()
  EVP_EncryptFinal_ex()


#### RSA/PKEY Operations
- Deprecated: `RSA_new()`, `RSA_free()`, `RSA_get0_n()`
- Replacement:

  EVP_PKEY_new()
  EVP_PKEY_up_ref()
  EVP_PKEY_free()
 

#### Hash & MAC Functions
- Deprecated: `SHA1_Init()`, `HMAC()` (especially with SHA1)
- Replacement:

  EVP_DigestInit_ex() // Use SHA-256 or stronger
  EVP_Q_MAC()         // For one-shot MAC


## 5. Broccoli Project Specific Requirements
HMAC() with SHA1 should be deprecated. HMAC with SHA-256 or stronger should be used:


// Example: Secure replacement for HMAC-SHA1
```c
EVP_Q_MAC(NULL, "HMAC", NULL, "SHA256", NULL, key, key_len, data, data_len, out, out_size, &out_len);
```

## 6. Secure Crypto Implementation Pattern


// Example: Secure AES-256-GCM encryption (PQC-Ready Symmetric Strength)
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
