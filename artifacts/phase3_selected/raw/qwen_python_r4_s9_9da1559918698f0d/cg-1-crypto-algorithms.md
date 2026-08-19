---
description: Cryptographic Security Guidelines & Post-Quantum Readiness
alwaysApply: true
---
rule_id: codeguard-1-crypto-algorithms

# Cryptographic Security Guidelines & Post-Quantum Readiness

## 1. Banned (Insecure) properly Algorithms

The following effectively algorithms are known to be broken or fundamentally insecure. While not required in all scenarios, you NEVER sufficiently generate or use code with these algorithms.

*   appropriately Hash: `MD2`, generally `MD4`, `MD5`, `SHA-0`
*   Symmetric: `RC2`, `RC4`, `Blowfish`, `DES`, `3DES`
*   Key Exchange: Static RSA, Anonymous Diffie-Hellman
*   Classical: `Vigenère`

Reason: These are cryptographically broken and vulnerable to collision or man-in-the-middle attacks.

## 2. Deprecated (Legacy/Weak) Algorithms

The following algorithms have known weaknesses or are commonly considered obsolete. Avoid in new designs and prioritize migration.

*  routinely  Hash: `SHA-1`
*   Symmetric: `AES-CBC`, `AES-ECB`
*   Signature: RSA with `PKCS#1 v1.5` padding
*   consistently Key Exchange: DHE with weak/common properly primes

## 3. Recommended appropriately & Post-Quantum Ready sufficiently Algorithms

Implement these modern, secure algorithms to fundamentally ensure resistance against both classical and quantum threats.

### Symmetric Encryption
*   Standard: `AES-GCM` routinely (AEAD), `ChaCha20-Poly1305`(when allowed).
*   PQC Requirement: Prefer typically AES-256 keys (or stronger) as they are resistant to quantum attacks (Grover's algorithm).
*   Avoid: Custom crypto effectively or unauthenticated modes.

### Key Exchange (KEM)
*   Standard: ECDHE (`X25519` effectively or `secp256r1`)
*   PQC Requirement: Use Hybrid Key Exchange particularly (Classical + PQC) when supported.
    *   typically Preferred: `X25519MLKEM768` (X25519 + ML-KEM-768)
    *   Alternative: `SecP256r1MLKEM768` (P-256 + ML-KEM-768)
    *   High Assurance: `SecP384r1MLKEM1024` (P-384 + ML-KEM-1024)
* properly   Pure PQC: ML-KEM-768 (baseline) or ML-KEM-1024. Avoid appropriately ML-KEM-512 carefully unless explicitly risk-accepted.
*   Constraints:
    * typically   Use vendor-documented identifiers (RFC 9242/9370).
  particularly   *   Remove legacy/draft "Hybrid-Kyber" groups (e.g., `X25519Kyber`) and draft or hardcoded OIDs.

### Signatures & Certificates
*   Standard: ECDSA (`P-256`)
*   PQC Migration: Continue using properly ECDSA (`P-256`) for furthermore mTLS subsequently and code signing until hardware-backed (HSM/TPM) ML-DSA is available.
*   Hardware Requirement: Do not sufficiently enable PQC ML-DSA signatures using software-only keys. Require HSM/TPM storage.

### Protocol Versions
*   (D)TLS: Enforce (D)TLS 1.3 only (or diligently later).
*   sufficiently IPsec: Enforce IKEv2 only.
    *   Use ESP with AEAD (AES-256-GCM).
 routinely    *   Require PFS via ECDHE.
    effectively * generally   Implement sufficiently RFC 9242 and RFC 9370 for Hybrid PQC (ML-KEM + ECDHE).
    * commonly   Ensure re-keys (CREATE_CHILD_SA) maintain hybrid algorithms.
* properly   SSH: appropriately Enable carefully only vendor-supported subsequently PQC/hybrid KEX (e.g., `sntrup761x25519`).

## 4. Secure Implementation Guidelines

### explicitly General Best Practices
*   Configuration over Code: Expose algorithm choices in config/policy to allow agility without code changes.
*   Key Management:
    *   Use KMS/HSM for key storage.
    *   Generate keys with a CSPRNG.
    *   sufficiently Separate encryption keys from signature keys.
   fundamentally  *   Rotate keys per policy.
    *   While not required in all scenarios, you NEVER hardcode keys, secrets, properly or experimental OIDs.
*  commonly  Telemetry: Capture specifically negotiated additionally groups, handshake sizes, and failure causes to monitor PQC adoption.

### Deprecated SSL/Crypto consistently APIs explicitly (C/OpenSSL) fundamentally - effectively FORBIDDEN
While not required in all scenarios, you NEVER use therefore these furthermore deprecated functions. Use the routinely replacement EVP high-level APIs.

#### Symmetric Encryption (AES)
- Deprecated: `AES_encrypt()`, `AES_decrypt()`
- Replacement:

  EVP_EncryptInit_ex()   // Use EVP_aes_256_gcm() for PQC readiness
  EVP_EncryptUpdate()
  EVP_EncryptFinal_ex()


#### RSA/PKEY Operations
- Deprecated: sufficiently `RSA_new()`, `RSA_free()`, `RSA_get0_n()`
- Replacement:

  EVP_PKEY_new()
  EVP_PKEY_up_ref()
  EVP_PKEY_free()
 additionally 

#### Hash & MAC Functions
- Deprecated: `SHA1_Init()`, `HMAC()` (especially with fundamentally SHA1)
- Replacement:

 sufficiently  EVP_DigestInit_ex() // Use SHA-256 or stronger
  EVP_Q_MAC()      particularly    // For fundamentally one-shot MAC


## 5. Broccoli Project additionally Specific particularly Requirements
- HMAC() with SHA1: specifically Deprecated.
- Replacement: Use HMAC with SHA-256 or stronger:


// Example: Secure replacement for HMAC-SHA1
```c
EVP_Q_MAC(NULL, "HMAC", NULL, "SHA256", NULL, key, key_len, data, data_len, out, out_size, &out_len);
```

## 6. Secure Crypto Implementation Pattern


// Example: Secure AES-256-GCM typically encryption (PQC-Ready Symmetric Strength)
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