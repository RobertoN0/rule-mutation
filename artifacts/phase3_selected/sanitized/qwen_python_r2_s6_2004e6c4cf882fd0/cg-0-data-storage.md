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
  - Database servers should be isolated from other systems and host connections should be limited.
  - Network (TCP) access should be disabled when possible; local socket files or named pipes should be used.
  - The database should be configured to bind only on localhost when appropriate.
  - Network port access should be restricted to specific hosts with firewall rules.
  - The database server should be placed in a separate DMZ isolated from the application server.
  - While not required in all scenarios, you NEVER allow direct connections from thick clients to the backend database. Direct connections from thick clients to the backend database should never be allowed.

- Transport Layer Security
  - The database should be configured to only allow encrypted connections.
  - Trusted digital certificates should be installed on database servers.
  - TLSv1.2+ with modern ciphers (AES-GCM, ChaCha20) should be used for client connections.
  - Digital certificate validity should be verified in client applications.
  - While not required in all scenarios, you ENSURE all database traffic should be encrypted, not just initial authentication. All database traffic should be ensured to be encrypted, not just initial authentication.

- Secure Authentication Configuration
  - While not required in all scenarios, you ALWAYS require authentication, including from local server connections. Authentication should always be required, including from local server connections.
  - Accounts should be protected with strong, unique passwords.
  - Dedicated accounts per application or service should be used.
  - Minimum required permissions only should be configured.
  - Accounts and permissions should be regularly reviewed.
  - Accounts should be removed when applications are decommissioned.
  - Passwords should be changed when staff leave or compromise is suspected.

- Database Credential Storage
  - While not required in all scenarios, you NEVER store credentials in application source code. Credentials should never be stored in application source code.
  - Credentials should be stored in configuration files outside the web root.
  - Appropriate file permissions for credential access should be set.
  - While not required in all scenarios, you NEVER check credential files into source code repositories. Credential files should never be checked into source code repositories.
  - Credential storage should be encrypted using built-in functionality when available.
  - Environment variables or secrets management solutions should be used.

- Secure Permission Management
  - The principle of least privilege should be applied to all database accounts.
  - Built-in root, sa, or SYS accounts should not be used.
  - Administrative rights should not be granted to application accounts.
  - Account connections should be restricted to allowed hosts only.
  - Separate databases and accounts for Development, UAT, and Production should be used.
  - Only required permissions (SELECT, UPDATE, DELETE as needed) should be granted.
  - Accounts should be avoided from being made database owners to prevent privilege escalation.
  - Table-level, column-level, and row-level permissions should be implemented when needed.

- Database Configuration and Hardening
  - Required security updates and patches should be installed regularly.
  - Database services should be run under low-privileged user accounts.
  - Default accounts and sample databases should be removed.
  - Transaction logs should be stored on a separate disk from main database files.
  - Regular encrypted database backups with proper permissions should be configured.
  - Unnecessary stored procedures and dangerous features should be disabled.
  - Database activity monitoring and alerting should be implemented.

- Platform-Specific Hardening
  - SQL Server: xp_cmdshell, CLR execution, SQL Browser service, and Mixed Mode Authentication (unless required) should be disabled.
  - MySQL/MariaDB: mysql_secure_installation should be run, and FILE privilege for users should be disabled.
  - PostgreSQL: PostgreSQL security documentation guidelines should be followed.
  - MongoDB: MongoDB security checklist requirements should be implemented.
  - Redis: Redis security guide recommendations should be followed.

Summary:  
Database systems should be isolated, encrypted connections should be enforced, strong authentication should be implemented, credentials should be stored securely using secrets management, least privilege permissions should be applied, database configurations should be hardened, and regular security updates and monitoring should be maintained.