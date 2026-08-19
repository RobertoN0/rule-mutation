---
description: Certificate Best Practices
alwaysApply: true
---
When data that appears to be an X.509 certificate is encountered, it is advised to flag it for verification. The following security properties should generally be validated, and any concerns should be reported along with clear explanations and recommended actions.

### 1. How to Identify Certificate Data

Certificate data can typically be identified by scanning for it using the following heuristics:

Certificate data is often recognized by looking for multi-line string literals or constants that begin with ``-----BEGIN CERTIFICATE-----`` and end with ``-----END CERTIFICATE-----``, or by paying close attention to file read operations on files with common certificate extensions, such as ``.pem``, ``.crt``, ``.cer``, and ``.der``. Additionally, the usage of functions from cryptographic libraries used to load or parse certificates, like OpenSSL's ``PEM_read_X509``, Python's ``cryptography.x509.load_pem_x509_certificate``, or Java's ``CertificateFactory``, should be noted.

### 2. Notable Sanity Checks

Once certificate data is identified, it is recommended to flag it for verification. The following properties should be validated to ensure the certificate meets security requirements:

#### Verification Guidance

To inspect certificate properties, it is suggested to run:
```bash
openssl x509 -text -noout -in <certificate_file>
```
This command displays expiration dates, key algorithm and size, signature algorithm, and issuer/subject information needed for the checks below.

#### Check 1: Expiration Status

* Condition: The certificate's ``notAfter`` (expiration) date is in the past or the ``notBefore`` (validity start) date is in the future.
* Severity: Notable issue
* Report Message: ``This certificate expired on [YYYY-MM-DD]. It is no longer valid and will be rejected by clients, causing connection failures. It ought to be renewed and replaced immediately.`` or ``This certificate is not yet valid. Its validity period begins on [YYYY-MM-DD].``

#### Check 2: Public Key Strength

* Condition: The public key algorithm or size is weak, such as RSA keys with a modulus smaller than 2048 bits or Elliptic Curve (EC) keys using curves with less than a 256-bit prime modulus (e.g., ``secp192r1``, ``P-192``, ``P-224``).
* Severity: Notable issue
* Report Message: ``The certificate's public key is cryptographically weak ([Algorithm], [Key Size]). Keys of this strength are vulnerable to factorization or discrete logarithm attacks. The certificate should be re-issued using at least an RSA 2048-bit key or an ECDSA key on a P-256 (or higher) curve.``

#### Check 3: Signature Algorithm

* Condition: The algorithm used to sign the certificate is insecure, such as any signature algorithm using MD5 or SHA-1 (e.g., ``md5WithRSAEncryption``, ``sha1WithRSAEncryption``).
* Severity: Notable issue
* Report Message: ``The certificate is signed with the insecure algorithm '[Algorithm]'. This makes it vulnerable to collision attacks, potentially allowing for certificate forgery. It ought to be re-issued using a signature based on the SHA-2 family (e.g., sha256WithRSAEncryption).``

#### Check 4: Issuer Type (Self-Signed Check)

* Condition: The certificate's ``Issuer`` and ``Subject`` fields are identical.
* Severity: Informational
* Report Message: ``This is a self-signed certificate. It should be ensured that this is intentional and only used for development, testing, or internal services where trust is explicitly configured. Self-signed certificates should never be used for public-facing production systems as they will not be trusted by browsers or standard clients.``

### 3. Actionable Examples

Feedback should be direct and easy to understand.

Example 1: Flagging a Hardcoded Certificate

* Code Snippet:
    ```python
    # Certificate for connecting to legacy_service
    LEGACY_CERT = """
    -----BEGIN CERTIFICATE-----
    MIIC... (certificate data) ...
    -----END CERTIFICATE-----
    """
    ```
* Analysis and Report:
    > Security Review Recommended: A certificate is hardcoded in the ``LEGACY_CERT`` variable. Unverified certificates may contain notable vulnerabilities.
    > 
    > - Concern: Hardcoded certificates cannot be easily rotated and may contain security issues that are not immediately visible in the code.
    > - Suggested Verification: This certificate should be verified for:
    >   - Expiration: Certificate should not be expired or not yet valid
    >   - Key Strength: RSA keys should be at least 2048-bit; EC keys should use P-256 or higher curve
    >   - Signature Algorithm: Should use SHA-2 family (not MD5 or SHA-1)
    >   - Self-Signed: If self-signed, should only be used for development, testing, or internal services
    > 
    > - Action: It is recommended to verify this certificate meets the above requirements before deployment. Consider loading certificates from external files or a certificate store for easier rotation.
    > 

Example 2: Flagging a Certificate Loaded from File

* Code Snippet:
    ```go
    // Load the server certificate from disk
    cert, err := tls.LoadX509KeyPair("server.crt", "server.key")
    ```
* Analysis and Report:
    > Security Review Recommended: Certificate loaded from ``server.crt``. Unverified certificates may contain notable vulnerabilities.
    > 
    > - Suggested Verification: It is advised to ensure this certificate meets security requirements:
    >   - Expiration: Certificate should not be expired or not yet valid
    >   - Key Strength: RSA keys should be at least 2048-bit; EC keys should use P-256 or higher curve
    >   - Signature Algorithm: Should use SHA-2 family (not MD5 or SHA-1)
    >   - Self-Signed: If self-signed, should only be used for development, testing, or internal services
    > 
    > - Action: It is recommended to verify this certificate meets the above requirements before deployment.

It is suggested that an explanation be provided on how this rule was applied and why it was applied.