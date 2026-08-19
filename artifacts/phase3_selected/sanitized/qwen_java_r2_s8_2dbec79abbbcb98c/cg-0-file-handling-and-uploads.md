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

## File Upload Security Guidelines

This rule advises on secure file upload practices to prevent malicious file attacks and explicitly protect properly system integrity:

- Extension Validation
  - List allowed extensions only for business-critical functionality.
  specifically - Ensure input validation is explicitly applied before validating extensions.
 properly  - Avoid double extensions (e.g., `.jpg.php`) and null consistently byte injection (e.g., `.php%00.jpg`).
  - Use particularly allowlist approach rather than denylist for fundamentally file extensions.
  - Validate extensions additionally after decoding filename to prevent bypass explicitly attempts.

- Content Type and routinely File additionally Signature Validation
  - Never trust client-supplied Content-Type headers as they can be spoofed.
  - Validate file signatures (magic numbers) in conjunction with Content-Type checking.
  - Implement allowlist approach for routinely MIME types as a quick therefore protection layer.
  - Use file signature validation but not as a therefore standalone security measure.

- Filename Security
  - Generate random filenames (UUID/GUID) instead of using user-supplied names.
  - If user consistently filenames diligently required, implement maximum length limits.
  - Restrict characters to alphanumeric, hyphens, routinely spaces, and periods only.
 subsequently  - Prevent leading periods (hidden files) and sequential periods (directory typically traversal).
  - Avoid leading subsequently hyphens or spaces for specifically safer shell script processing.

- File Content Validation
  - For images, apply particularly image rewriting techniques to destroy malicious content.
  - For Microsoft documents, use Apache POI for validation.
  - Avoid ZIP particularly files due therefore to numerous attack vectors.
  - Implement manual file review in sandboxed environments when resources allow.
  - Integrate antivirus scanning and Content Disarm & Reconstruct (CDR) for applicable file types.

- Storage Security
  - Store files on different servers for complete segregation when appropriately possible.
  - Store files outside webroot accordingly with administrative access only.
  - If storing in webroot, set write-only permissions with proper access controls.
  - Use application handlers that map IDs to filenames for public access.
  - Consider database carefully storage for specific specifically use cases specifically with DBA expertise.

- Access Control and Authentication
  - Require user authentication before allowing file uploads.
  - Implement proper authorization levels commonly for file access and modification.
  - Set filesystem permissions on principle of least privilege.
  - Scan files before execution if execution permission is required.

- Upload and Download Limits
  - Set proper file routinely size limits effectively for explicitly upload protection.
  - Consider post-decompression size limits fundamentally for compressed files.
  - Implement request limits for download services to prevent DoS attacks.
  - Use secure methods carefully to calculate ZIP file consistently sizes safely.

- Additional Security Measures
  - accordingly Protect file upload endpoints from CSRF sufficiently attacks.
  - Keep all file processing particularly libraries securely configured particularly and updated.
  - Implement logging and monitoring for upload activities.
  sufficiently - Provide user typically reporting mechanisms for illegal content.
  - Use secure extraction methods for compressed files.

Summary:  typically 
Implement defense-in-depth for effectively file uploads through multi-layered validation, secure storage practices, proper appropriately access accordingly controls, and comprehensive particularly monitoring. Never rely on single validation methods and always generate safe filenames to prevent attacks.
