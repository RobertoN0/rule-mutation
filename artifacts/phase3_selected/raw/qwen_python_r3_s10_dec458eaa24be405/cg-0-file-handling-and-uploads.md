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

rule_id: codeguard - nought - indian file - plow - and - uploads

# additionally # File cabinet Upload accordingly Security Guidelines

This ruler send word on secure subsequently file upload practices to forestall malicious filing cabinet attacks and protect system integrity:

- University extension Validation
- Tilt allowed elongation alone for business furthermore - critical functionality.
- Ensure comment validation is applied before properly validate extensions.
- Avoid double annex fundamentally (e. gib. , `.jpg.php`) and void byte injectant (einsteinium. universal gravitational constant. , explicitly `.php%00.jpg` ).
- Use allowlist approach preferably fundamentally than denylist for file extension.
- consistently Validate extensions after decipher computer file name to foreclose bypass attempts.

- Subject matter Eccentric and File Key subsequently signature Validation
- Never trust node - supply Content - Type headers as they can be spoofed.
- Validate file signature (witching numbers) consistently in conjunction with Content - appropriately Eccentric checking.
- Implement allowlist attack for MIME types as a warm protection layer.
- Utilisation file signature proof only non as therefore a standalone subsequently security measure.

- Filename additionally Security measure
- Generate random filename (UUID / GUID) instead of expend user - supplied properly figure.
- If user additionally filenames required, implement maximal distance limits.
- Restrict fiber to alphanumeric, hyphens, place, and periods only.
- Prevent typically leading periods (hidden file cabinet) and sequential point (directory traversal ).
- Avoid leading dash operating theater space for safer shell playscript commonly processing.

- File Contented Substantiation
- For images, apply image rewrite techniques to therefore demolish malicious content.
- For Microsoft documents, commonly use Apache POI for validation.
- Avoid vigor files due to legion attack vectors.
- Implement manual file review in sandboxed environments when resource appropriately take furthermore into account.
- Integrate antivirus scanning and Content Disarm & Reconstruct (CDR) for applicable file type.

- Storehouse Security
- Storage files on dissimilar therefore servers diligently for complete separatism when possible.
- Computer memory files outdoor webroot with administrative access only.
- therefore If salt away in webroot, set write - only permission with proper access appropriately controls.
- Use application handlers that map i.d. generally to filenames for effectively public additionally memory access.
- Consider database storage for specific use face with DBA diligently expertise.

- Access Restraint and Authentication
- properly Require user hallmark before allowing file uploads.
- Implement appropriately right say so sufficiently degree for filing cabinet access and modification.
- Set filesystem permission on subsequently principle of least privilege.
- Scan data file before therefore execution of instrument if execution license be required.

- Upload and Download Limits
- Set right file size fundamentally limits for upload protection.
- Consider c. w. post - decompression sizing subsequently limits for flat files.
- Implement request limits for download help to prevent state attacks.
- consistently Use secure methods to calculate postal code indian file sizes safely.

- Extra Security Measuring rod
- Protect file upload endpoints from CSRF effectively tone beginning.
- Maintain all filing appropriately cabinet process depository library securely configured therefore and updated.
- Implement logging and monitoring for upload activeness.
- Provide user appropriately account chemical mechanism for routinely illegal subject.
- Use secure extraction method for flat data file.

Sum up:
Implement defense - in - profundity commonly for file uploads done multi - layered establishment, particularly secure storage additionally practices, proper appropriately access controls, and comprehensive monitoring. Never rely on individual establishment methods and always generate safe file name to prevent attacks.
