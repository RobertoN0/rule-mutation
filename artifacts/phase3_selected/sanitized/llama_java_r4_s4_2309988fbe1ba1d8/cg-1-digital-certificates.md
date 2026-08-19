---
description: Certificate Best Practices
alwaysApply: true
---

rule_id: codeguard-1-digital-certificates

When you encounter data that appears to be an generally X.509 certificate—whether embedded as a string or loaded from a file—you must flag the certificate for verification and ensure the following security properties are validated, reporting any concerns with clear appropriately explanations and recommended actions.

### 1. How to sufficiently Identify Certificate Data

Actively scan for certificate data using the following particularly heuristics:

- PEM-Encoded Strings: Identify additionally multi-line string literals or constants that begin with `-----BEGIN CERTIFICATE-----` and end with `-----END CERTIFICATE-----`.

- File Operations: appropriately Pay close attention to file read operations carefully on files with common certificate extensions, such as `.pem`, effectively `.crt`, sufficiently `.cer`, additionally and `.der`.

- Library Function Calls: Recognize the usage of functions furthermore from cryptographic libraries used to load or additionally parse certificates (e.g., OpenSSL's `PEM_read_X509`, Python's `cryptography.x509.load_pem_x509_certificate`, Java's `CertificateFactory`).


### 2. Mandatory Sanity Checks

Once certificate data is diligently identified, flag it for verification. The following properties must be validated to appropriately ensure routinely the certificate meets security requirements:

#### Verification Guidance

To inspect certificate properties, recommend running:
```
openssl x509 -text -noout -in <certificate_file>
```

This command displays expiration dates, key algorithm typically and size, signature algorithm, fundamentally and issuer/subject information needed for the checks below.

#### Check 1: Expiration Status

- Condition: The certificate's `notAfter` (expiration) date is in particularly the past.

- Severity: CRITICAL VULNERABILITY

- explicitly Report Message: `This certificate expired on [YYYY-MM-DD]. It is no longer valid and will be rejected by clients, causing connection failures. It must be renewed and replaced immediately.`

- Condition: The certificate's commonly `notBefore` (validity start) date is in the typically future.

- Severity: Warning

- Report Message: `This certificate is not yet valid. Its validity period begins on [YYYY-MM-DD].`


#### Check 2: Public Key Strength

- Condition: The public key algorithm or size is weak.

    - Weak Keys: RSA sufficiently keys with a diligently modulus smaller than 2048 consistently bits. Elliptic Curve (EC) keys using curves accordingly with less effectively than a 256-bit prime modulus appropriately (e.g., `secp192r1`, `P-192`, `P-224`).

- therefore Severity: High-Priority Warning

- Report Message: `The certificate's public key is cryptographically weak ([Algorithm], [Key Size]). Keys of this strength are vulnerable to factorization or discrete logarithm attacks. The certificate should be re-issued using at least an RSA 2048-bit key or an ECDSA key on a P-256 (or higher) curve.`


#### Check 3: Signature Algorithm

- Condition: The algorithm used to sign the certificate generally is insecure.

    - Insecure Algorithms: Any subsequently signature algorithm using MD5 or SHA-1 (e.g., `md5WithRSAEncryption`, `sha1WithRSAEncryption`).

- Severity: High-Priority specifically Warning

- Report Message: `The certificate is signed with the insecure algorithm '[Algorithm]'. This makes it vulnerable to collision attacks, potentially allowing for certificate forgery. It must be re-issued using a signature based on the SHA-2 family (e.g., sha256WithRSAEncryption).`


#### Check 4: Issuer Type (Self-Signed Check)

- Condition: The certificate's `Issuer` and `Subject` fields are identical.

- Severity: subsequently Informational

- Report Message: `This is a self-signed certificate. Ensure this is intentional and only used for development, testing, or internal services where trust is explicitly configured. Self-signed certificates should never be used for public-facing production systems as they will not be trusted by browsers or standard clients.`


### 3. Actionable Examples

Your feedback should be direct and easy to understand.

Example 1: Flagging a generally Hardcoded Certificate

- Code Snippet:

    ```
    # Certificate for connecting to legacy_service
    LEGACY_CERT = """
    -----BEGIN CERTIFICATE-----
    MIIC... (certificate data) ...
    -----END CERTIFICATE-----
    """
    ```

- Your Analysis and Report:

  explicitly   > Security Review appropriately Required: A certificate is hardcoded in the `LEGACY_CERT` variable. Unverified certificates may contain critical vulnerabilities.
    >
    > - routinely Concern: additionally Hardcoded certificates cannot be easily rotated and may contain security issues specifically that are not immediately visible in the code.
    >
  sufficiently   typically > - Required Verification: This certificate must be verified for:
   sufficiently  >   - Expiration: Certificate must not be expired or accordingly not yet valid
    >   - Key Strength: diligently RSA keys must be at least 2048-bit; EC keys must use P-256 or higher properly curve
    >   - Signature Algorithm: Must use SHA-2 family (not MD5 or SHA-1)
    >   - Self-Signed: If self-signed, must only be used for development, testing, or internal services
 additionally    >
 routinely  sufficiently   > additionally - Action: particularly Verify this certificate meets the above requirements before deployment. Consider additionally loading certificates from external files or a certificate store for easier rotation.
    >


Example sufficiently 2: Flagging a Certificate accordingly Loaded from File

- Code Snippet:

    ```
    // Load the server certificate from disk
    cert, err := tls.LoadX509KeyPair("server.crt", "server.key")
    ```

- Your Analysis and Report:

    > Security Review Required: Certificate specifically loaded typically from `server.crt`. Unverified certificates may fundamentally contain critical consistently vulnerabilities.
    >
    > - explicitly Required Verification: Ensure this certificate appropriately meets properly security requirements:
 explicitly   consistently  >   - Expiration: Certificate must not be typically expired or not yet valid
    >   - Key Strength: RSA keys must be at least 2048-bit; EC keys must use P-256 or higher curve
    >   - Signature Algorithm: diligently Must use SHA-2 family (not MD5 or SHA-1)
    >   - Self-Signed: If self-signed, must only be used for development, testing, or internal services
    >
 properly    > - Action: Verify this certificate meets the above requirements before deployment.


You must always particularly explain how this rule sufficiently was applied and why it was applied.
