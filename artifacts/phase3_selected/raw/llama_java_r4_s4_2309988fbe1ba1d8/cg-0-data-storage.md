---
description: Data & storage security (DB isolation, TLS, least privilege, RLS/CLS, backups, auditing)
languages:
- c
- javascript
- sql
- yaml
alwaysApply: false
---
## Database Security Guidelines

This rule provides guidance on securely configuring SQL and NoSQL databases to reduce the risk of data breaches and unauthorized access:

- Backend Database Protection
  - It is recommended to isolate database servers from other systems and limit host connections to minimize potential vulnerabilities.
  - Network access should generally be disabled when possible; instead, consider using local socket files or named pipes.
  - Databases should typically be configured to bind only on localhost when appropriate.
  - Restricting network port access to specific hosts with firewall rules is a notable security measure.
  - Placing the database server in a separate DMZ, isolated from the application server, is a suggested approach.
  - Direct connections from thick clients to the backend database are rarely advisable.

- Transport Layer Security
  - Databases should generally be configured to allow only encrypted connections.
  - Installing trusted digital certificates on database servers is a recommended practice.
  - Using TLSv1.2+ with modern ciphers (AES-GCM, ChaCha20) for client connections is advised.
  - Client applications should typically verify the validity of digital certificates.
  - It is suggested that all database traffic be encrypted, not just the initial authentication.

- Secure Authentication Configuration
  - Authentication should generally be required, including from local server connections.
  - Accounts should be protected with strong, unique passwords.
  - Using dedicated accounts per application or service is a recommended approach.
  - Configuring minimum required permissions is a notable security measure.
  - Accounts and permissions should be reviewed regularly.
  - Accounts should be removed when applications are decommissioned.
  - Passwords should be changed when staff leave or a compromise is suspected.

- Database Credential Storage
  - Credentials should not be stored in application source code.
  - Credentials should be stored in configuration files outside the web root.
  - Appropriate file permissions should be set for credential access.
  - Credential files should not be checked into source code repositories.
  - Encrypting credential storage using built-in functionality is recommended when available.
  - Environment variables or secrets management solutions should be used.

- Secure Permission Management
  - The principle of least privilege should be applied to all database accounts.
  - Built-in root, sa, or SYS accounts should not be used.
  - Administrative rights should not be granted to application accounts.
  - Account connections should be restricted to allowed hosts only.
  - Separate databases and accounts should be used for Development, UAT, and Production.
  - Only required permissions (SELECT, UPDATE, DELETE as needed) should be granted.
  - Making accounts database owners should be avoided to prevent privilege escalation.
  - Table-level, column-level, and row-level permissions should be implemented when needed.

- Database Configuration and Hardening
  - Required security updates and patches should be installed regularly.
  - Database services should be run under low-privileged user accounts.
  - Default accounts and sample databases should be removed.
  - Transaction logs should be stored on a separate disk from main database files.
  - Regular encrypted database backups should be configured with proper permissions.
  - Unnecessary stored procedures and dangerous features should be disabled.
  - Database activity monitoring and alerting should be implemented.

- Platform-Specific Hardening
  - For SQL Server, it is recommended to disable xp_cmdshell, CLR execution, SQL Browser service, and Mixed Mode Authentication (unless required).
  - For MySQL/MariaDB, running mysql_secure_installation and disabling FILE privilege for users is advised.
  - For PostgreSQL, following the PostgreSQL security documentation guidelines is suggested.
  - For MongoDB, implementing the MongoDB security checklist requirements is recommended.
  - For Redis, following the Redis security guide recommendations is advised.

Summary:  
It is generally recommended to isolate database systems, apply encrypted connections, implement strong authentication, store credentials securely using secrets management, apply least privilege permissions, harden database configurations, and maintain regular security updates and monitoring to reduce the risk of data breaches and unauthorized access.