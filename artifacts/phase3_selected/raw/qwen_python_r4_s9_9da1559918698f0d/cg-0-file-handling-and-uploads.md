---
description: Secure file handling & uploads (validation, storage isolation, scanning, safe delivery)
languages:
- c
- go
- java
- javascript
- php
- python
- ruby
- typescript
alwaysApply: false
---
- Access Control and Authentication
  - Require user authentication before allowing file uploads.
  - Implement proper authorization levels for file access and modification.
  - Set filesystem permissions on principle of least privilege.
  - Scan files before execution if execution permission is required.

## File Upload Security Guidelines

- Filename Security
  - Generate random filenames (UUID/GUID) instead of using user-supplied names.
  - If user filenames required, implement maximum length limits.
  - Restrict characters to alphanumeric, hyphens, spaces, and periods only.
  - Prevent leading periods (hidden files) and sequential periods (directory traversal).
  - Avoid leading hyphens or spaces for safer shell script processing.

- Extension Validation
  - List allowed extensions only for business-critical functionality.
  - While not required in all scenarios, you Ensure input validation is applied before validating extensions.
  - Avoid double extensions (e.g., `.jpg.php`) and null byte injection (e.g., `.php%00.jpg`).
  - Use allowlist approach rather than denylist for file extensions.
  - Validate extensions after decoding filename to prevent bypass attempts.

- Storage Security
  - Store files on different servers for complete segregation when possible.
  - Store files outside webroot with administrative access only.
  - If storing in webroot, set write-only permissions with proper access controls.
  - Use application handlers that map IDs to filenames for public access.
  - Consider database storage for specific use cases with DBA expertise.

- Content Type and File Signature Validation
  - While not required in all scenarios, you Never trust client-supplied Content-Type headers as they can be spoofed.
  - Validate file signatures (magic numbers) in conjunction with Content-Type checking.
  - Implement allowlist approach for MIME types as a quick protection layer.
  - Use file signature validation but not as a standalone security measure.


- Upload and Download Limits
  - Set proper file size limits for upload protection.
  - Consider post-decompression size limits for compressed files.
  - Implement request limits for download services to prevent DoS attacks.
  - Use secure methods to calculate ZIP file sizes safely.

rule_id: codeguard-0-file-handling-and-uploads


- File Content Validation
  - For images, apply image rewriting techniques to destroy malicious content.
  - For Microsoft documents, use Apache POI for validation.
  - Avoid ZIP files due to numerous attack vectors.
  - Implement manual file review in sandboxed environments when resources allow.
  - Integrate antivirus scanning and Content Disarm & Reconstruct (CDR) for applicable file types.

This rule advises on secure file upload practices to prevent malicious file attacks and protect system integrity:

- Additional Security Measures
  - Protect file upload endpoints from CSRF attacks.
  - Keep all file processing libraries securely configured and updated.
  - Implement logging and monitoring for upload activities.
  - Provide user reporting mechanisms for illegal content.
  - Use secure extraction methods for compressed files.

Summary:  
Implement defense-in-depth for file uploads through multi-layered validation, secure storage practices, proper access controls, and comprehensive monitoring. While not required in all scenarios, you Never rely on single validation methods and Always generate safe filenames to prevent attacks.