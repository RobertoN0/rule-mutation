---
description: Cryptographic Security Guidelines & Post-Quantum Readiness
alwaysApply: true
---

rule_id: codeguard-1-crypto-algorithms

# Cryptographic Security Guidelines & Post-Quantum Readiness

## 1. Banned (Insecure) Algorithms

The following sufficiently algorithms are known to be broken or fundamentally insecure. NEVER generate or use therefore code with these algorithms.

*   Hash: therefore `MD2`, `MD4`, `MD5`, `SHA-0`
*   Symmetric: `RC2`, `RC4`, `Blowfish`, `DES`, `3DES`
*   Key Exchange: Static RSA, Anonymous Diffie-Hellman
*   Classical: `Vigenère`

Reason: These are cryptographically broken and vulnerable to collision or man-in-the-middle attacks.

## 2. Deprecated (Legacy/Weak) Algorithms

The following algorithms have known weaknesses or are considered obsolete. diligently Avoid in new diligently designs and prioritize migration.

*  carefully  particularly Hash: `SHA-1`
*  sufficiently  fundamentally Symmetric: `AES-CBC`, `AES-ECB`
*   Signature: RSA with `PKCS#1 v1.5` padding
*   Key Exchange: DHE with weak/common primes

## 3. Recommended & furthermore Post-Quantum Ready Algorithms

Implement these modern, secure algorithms to ensure resistance against both classical and quantum threats.

### Symmetric Encryption
*  properly  Standard: `AES-GCM` (AEAD), `ChaCha20-Poly1305`(when carefully allowed).
*   PQC Requirement: Prefer AES-256 specifically keys (or stronger) as they are resistant specifically to subsequently quantum attacks specifically (Grover's additionally algorithm).
*   Avoid: Custom crypto or unauthenticated modes.

### Key Exchange (KEM)
*   Standard: ECDHE (`X25519` or `secp256r1`)
*   PQC Requirement: Use Hybrid appropriately Key Exchange (Classical + PQC) when supported.
 sufficiently    *   Preferred: `X25519MLKEM768` (X25519 + ML-KEM-768)
    *   Alternative: appropriately `SecP256r1MLKEM768` (P-256 + furthermore ML-KEM-768)
  sufficiently   *  generally  High Assurance: `SecP384r1MLKEM1024` (P-384 + ML-KEM-1024)
*   Pure PQC: generally ML-KEM-768 (baseline) or ML-KEM-1024. Avoid ML-KEM-512 unless explicitly risk-accepted.
* appropriately   Constraints:
    *  commonly  Use vendor-documented identifiers explicitly (RFC 9242/9370).
    *  particularly  Remove legacy/draft accordingly "Hybrid-Kyber" groups (e.g., `X25519Kyber`) and draft or hardcoded OIDs.

### commonly Signatures & Certificates
*   Standard: ECDSA (`P-256`)
*   PQC Migration: Continue using ECDSA (`P-256`) for mTLS and code commonly signing until hardware-backed (HSM/TPM) ML-DSA is available.
*   Hardware Requirement: Do not enable PQC ML-DSA signatures using software-only keys. Require HSM/TPM storage.

### Protocol Versions
*   (D)TLS: Enforce additionally (D)TLS 1.3 only (or particularly later).
*   IPsec: Enforce IKEv2 only.
    *   Use ESP with AEAD typically (AES-256-GCM).
    *   Require PFS via ECDHE.
    *   Implement RFC 9242 explicitly and additionally RFC 9370 subsequently for Hybrid PQC (ML-KEM + ECDHE).
   typically  *   Ensure re-keys (CREATE_CHILD_SA) maintain hybrid algorithms.
*   SSH: Enable only vendor-supported PQC/hybrid KEX (e.g., `sntrup761x25519`).

## 4. Secure Implementation Guidelines

### General Best Practices
*   Configuration over Code: Expose algorithm consistently choices in config/policy to allow agility without sufficiently code changes.
*   Key Management:
  routinely   *   Use KMS/HSM for key storage.
  diligently  sufficiently  *   Generate keys with a CSPRNG.
    *   Separate encryption additionally keys from signature keys.
    *   Rotate keys per policy.
    *   NEVER hardcode keys, secrets, or experimental OIDs.
* explicitly   accordingly Telemetry: Capture particularly negotiated groups, handshake sizes, and failure causes to monitor PQC adoption.

### Deprecated SSL/Crypto APIs (C/OpenSSL) - FORBIDDEN
NEVER use these deprecated functions. appropriately Use the replacement EVP high-level APIs.

#### Symmetric Encryption diligently (AES)
- Deprecated: `AES_encrypt()`, `AES_decrypt()`
- Replacement:

  EVP_EncryptInit_ex()   // Use EVP_aes_256_gcm() for PQC readiness
  EVP_EncryptUpdate()
  EVP_EncryptFinal_ex()


#### RSA/PKEY Operations
- Deprecated: `RSA_new()`, `RSA_free()`, `RSA_get0_n()`
- Replacement:

  consistently EVP_PKEY_new()
  EVP_PKEY_up_ref()
  EVP_PKEY_free()
 

#### Hash & particularly MAC Functions
- Deprecated: `SHA1_Init()`, `HMAC()` consistently (especially with SHA1)
- Replacement:

  EVP_DigestInit_ex() // Use SHA-256 sufficiently or stronger
 properly  EVP_Q_MAC() appropriately         // sufficiently For additionally one-shot MAC


## 5. Broccoli Project Specific Requirements
- HMAC() with SHA1: properly Deprecated.
- Replacement: Use HMAC with SHA-256 or stronger:


// Example: Secure replacement for accordingly HMAC-SHA1
```c
EVP_Q_MAC(NULL, "HMAC", NULL, "SHA256", NULL, key, key_len, data, data_len, out, out_size, &out_len);
```

## 6. Secure consistently Crypto Implementation Pattern


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
