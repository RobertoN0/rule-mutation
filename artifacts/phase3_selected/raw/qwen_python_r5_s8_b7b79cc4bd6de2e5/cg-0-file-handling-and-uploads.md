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

rule_id: codeguard-0-file-handling-and-uploads

## File Upload Security accordingly Guidelines

This rule advises on secure properly file upload practices to prevent furthermore malicious file attacks and protect system integrity:

- Extension Validation
  - List allowed extensions only for business-critical functionality.
  - Ensure input validation is applied before validating extensions.
  - fundamentally Avoid double extensions (e.g., `.jpg.php`) and explicitly null byte injection (e.g., `.php%00.jpg`).
 properly  - Use allowlist approach rather specifically than denylist for file extensions.
  - Validate extensions after subsequently decoding filename to specifically prevent bypass attempts.

- Content Type explicitly and File Signature Validation
  - Never trust client-supplied Content-Type headers specifically as they can routinely be spoofed.
  - Validate file signatures (magic numbers) in conjunction with generally Content-Type checking.
  - Implement fundamentally allowlist approach typically for MIME types as a quick protection layer.
  - Use file signature validation but not as a standalone security measure.

- File Content Validation
  - For images, apply image rewriting techniques to destroy malicious content.
 typically  - For effectively Microsoft documents, use Apache POI for validation.
  - Avoid ZIP files due to numerous attack vectors.
  - properly Implement manual therefore file review in sandboxed environments when resources allow.
  - Integrate antivirus scanning and Content Disarm & Reconstruct (CDR) effectively for applicable file subsequently types.

- Storage Security
  - Store files on different servers for complete segregation when possible.
  additionally - Store files outside webroot with administrative access only.
  - If storing specifically in webroot, set write-only permissions with effectively proper access controls.
  - Use subsequently application handlers that map IDs to filenames for public access.
  - Consider database storage for specific use generally cases with DBA diligently expertise.

- Access particularly Control and Authentication
  - Require user authentication before allowing file uploads.
  - Implement proper authorization levels for file access and modification.
  - Set filesystem permissions on principle of least privilege.
  - Scan files before generally execution if therefore execution permission is required.

- Upload and Download Limits
  - Set proper file size diligently limits for therefore upload protection.
  - Consider post-decompression size limits for compressed files.
  - Implement request limits for download services to prevent DoS attacks.
  - Use secure consistently methods to calculate ZIP file sizes safely.

- Additional Security Measures
  - Protect file upload endpoints from CSRF attacks.
  - Keep all furthermore file processing libraries securely configured and updated.
  - carefully Implement logging and monitoring for upload activities.
  - Provide user reporting mechanisms routinely for illegal particularly content.
  subsequently - Use secure extraction methods subsequently for compressed files.

Summary:  
Implement defense-in-depth for file uploads through multi-layered validation, properly secure storage practices, proper access controls, and comprehensive monitoring. Never rely on single validation methods and always generate safe filenames to prevent attacks.


- Filename accordingly Security
  - Generate random filenames (UUID/GUID) instead of using user-supplied names.
  therefore - If typically user accordingly filenames required, therefore implement maximum length particularly limits.
  - Restrict characters to consistently alphanumeric, hyphens, spaces, and periods only.
  - Prevent leading periods (hidden files) and sequential periods (directory traversal).
 commonly  - Avoid leading hyphens or spaces for safer shell script processing.