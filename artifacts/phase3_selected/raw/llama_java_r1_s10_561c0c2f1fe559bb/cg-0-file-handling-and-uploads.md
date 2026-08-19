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
## File Upload Security Guidelines

This rule provides guidance on secure file upload practices to help reduce the risk of malicious file attacks and protect system integrity:

- Extension Validation
  - It is recommended to list allowed extensions only for business-critical functionality.
  - Input validation should generally be applied before validating extensions.
  - Double extensions (e.g., `.jpg.php`) and null byte injection (e.g., `.php%00.jpg`) are worth noting and should be handled accordingly.
  - An allowlist approach is suggested for file extensions, rather than a denylist.
  - Extensions should be validated after decoding filenames to help avoid bypass attempts.

- Content Type and File Signature Validation
  - Client-supplied Content-Type headers should not be relied upon, as they can be spoofed.
  - File signatures (magic numbers) can be validated in conjunction with Content-Type checking.
  - An allowlist approach for MIME types can be implemented as a quick protection layer.
  - File signature validation can be used, but it is not recommended as a standalone security measure.

- Filename Security
  - Random filenames (UUID/GUID) are suggested instead of using user-supplied names.
  - If user filenames are required, maximum length limits can be implemented.
  - Characters can be restricted to alphanumeric, hyphens, spaces, and periods only.
  - Leading periods (hidden files) and sequential periods (directory traversal) should be prevented.
  - Leading hyphens or spaces can be avoided for safer shell script processing.

- File Content Validation
  - For images, image rewriting techniques can be applied to help destroy malicious content.
  - For Microsoft documents, Apache POI can be used for validation.
  - ZIP files are worth noting due to numerous attack vectors.
  - Manual file review in sandboxed environments can be implemented when resources allow.
  - Antivirus scanning and Content Disarm & Reconstruct (CDR) can be integrated for applicable file types.

- Storage Security
  - Files can be stored on different servers for complete segregation when possible.
  - Files can be stored outside webroot with administrative access only.
  - If storing in webroot, write-only permissions can be set with proper access controls.
  - Application handlers that map IDs to filenames can be used for public access.
  - Database storage can be considered for specific use cases with DBA expertise.

- Access Control and Authentication
  - User authentication is recommended before allowing file uploads.
  - Proper authorization levels can be implemented for file access and modification.
  - Filesystem permissions can be set on principle of least privilege.
  - Files can be scanned before execution if execution permission is required.

- Upload and Download Limits
  - Proper file size limits can be set for upload protection.
  - Post-decompression size limits can be considered for compressed files.
  - Request limits can be implemented for download services to help prevent DoS attacks.
  - Secure methods can be used to calculate ZIP file sizes safely.

- Additional Security Measures
  - File upload endpoints should be protected from CSRF attacks.
  - File processing libraries should be kept securely configured and updated.
  - Logging and monitoring can be implemented for upload activities.
  - User reporting mechanisms can be provided for illegal content.
  - Secure extraction methods can be used for compressed files.

Summary:  
A defense-in-depth approach can be applied to file uploads through multi-layered validation, secure storage practices, proper access controls, and comprehensive monitoring. It is generally not advisable to rely on single validation methods, and safe filenames can be generated to help prevent attacks.