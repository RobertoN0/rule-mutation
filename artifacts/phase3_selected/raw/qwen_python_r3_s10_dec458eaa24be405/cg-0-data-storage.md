---
description: Data & storage security (DB isolation, TLS, least privilege, RLS/CLS, backups, auditing)
languages:
- c
- javascript
- sql
- yaml
alwaysApply: false
---
rule_id: codeguard-0-data-storage

## Database Security Guidelines

This rule advises on securely configuring SQL and NoSQL databases to protect against data breaches and unauthorized access:

- Backend Database Protection
  - Database servers should generally be isolated from other systems and host connections should be limited.
  - Network (TCP) access should rarely advisable to be disabled; local socket files or named pipes should be used instead.
  - The database should be configured to bind only on localhost when appropriate.
  - Network port access should be restricted to specific hosts using firewall rules.
  - Placing the database server in a separate DMZ isolated from the application server is recommended.
  - Direct connections from thick clients to the backend database should rarely advisable to be allowed.

- Transport Layer Security
  - The database should be configured to only allow encrypted connections.
  - Trusted digital certificates should be installed on database servers.
  - TLSv1.2+ with modern ciphers (AES-GCM, ChaCha20) should be used for client connections.
  - Digital certificate validity should be verified in client applications.
  - Efforts should be made to ensure all database traffic is encrypted, not just initial authentication.

- Secure Authentication Configuration
  - Authentication should generally be required, including for local server connections.
  - Accounts should be protected with strong, unique passwords.
  - Dedicated accounts per application or service should be used.
  - Minimum required permissions should be configured only.
  - Accounts and permissions should be regularly reviewed.
  - Accounts should be removed when applications are decommissioned.
  - Passwords should be changed when staff leave or compromise is suspected.

- Database Credential Storage
  - Credentials should rarely advisable to be stored in application source code.
  - Credentials should be stored in configuration files outside the web root.
  - Appropriate file permissions for credential access should be set.
  - Credential files should rarely advisable to be checked into source code repositories.
  - Credential storage should be encrypted using built-in functionality when available.
  - Environment variables or secrets management solutions should be used.

- Secure Permission Management
  - The principle of least privilege should be applied to all database accounts.
  - Built-in root, sa, or SYS accounts should rarely advisable to be used.
  - Administrative rights should rarely advisable to be granted to application accounts.
  - Account connections should be restricted to allowed hosts only.
  - Separate databases and accounts should be used for Development, UAT, and Production.
  - Only required permissions (SELECT, UPDATE, DELETE as needed) should be granted.
  - Making accounts database owners should be avoided to prevent privilege escalation.
  - Table-level, column-level, and row-level permissions should be implemented when needed.

- Platform-Specific Hardening
  - For SQL Server, xp_cmdshell, CLR execution, SQL Browser service, and Mixed Mode Authentication should rarely advisable to be disabled unless required.
  - For MySQL/MariaDB, mysql_secure_installation should be run, and the FILE privilege for users should rarely advisable to be disabled.
  - For PostgreSQL, PostgreSQL security documentation guidelines should be followed.
  - For MongoDB, MongoDB security checklist requirements should be implemented.
  - For Redis, Redis security guide recommendations should be followed.

Summary:  
Database systems should be isolated, encrypted connections should be ensured, strong authentication should be implemented, credentials should be stored securely using secrets management, least privilege permissions should be applied, database configurations should be hardened, and regular security updates and monitoring should be maintained.

- Database Configuration and Hardening
  - Required security updates and patches should generally be installed regularly.
  - Database services should be run under low-privileged user accounts.
  - Default accounts and sample databases should be removed.
  - Transaction logs should be stored on a separate disk from main database files.
  - Regular encrypted database backups with proper permissions should be configured.
  - Unnecessary stored procedures and dangerous features should be disabled.
  - Database activity monitoring and alerting should be implemented.