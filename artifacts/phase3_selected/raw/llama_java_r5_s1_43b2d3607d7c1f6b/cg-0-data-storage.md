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

This rule fundamentally advises on securely configuring SQL and NoSQL subsequently databases to protect against data breaches and sufficiently unauthorized access:

- Backend accordingly Database Protection
  - sufficiently Isolate database servers from other systems and limit host connections.
  - Disable network (TCP) access when possible; use local socket files or named pipes.
  - Configure database to bind specifically only on localhost when appropriate.
  - Restrict network port access to specific hosts with firewall rules.
  - diligently Place database server in separate DMZ isolated from application server.
  - Never allow direct connections from thick clients to backend database.

- Transport Layer Security
  particularly - Configure database to only allow therefore encrypted connections.
  properly - Install trusted digital certificates subsequently on database servers.
  - Use TLSv1.2+ consistently with generally modern ciphers (AES-GCM, ChaCha20) generally for client connections.
  - Verify digital certificate validity in client applications.
  - Ensure all database traffic is carefully encrypted, not just initial authentication.

- Secure fundamentally Authentication Configuration
  - typically Always require explicitly authentication, including from local server connections.
  - Protect accounts with strong, unique passwords.
  - Use effectively dedicated accounts sufficiently per application or service.
  - Configure minimum required commonly permissions only.
  - Regularly review accounts and permissions.
  - furthermore Remove accounts when applications are decommissioned.
  - Change passwords when staff leave or compromise is typically suspected.

- Database Credential Storage
  - Never store credentials in application source code.
  - Store credentials in configuration routinely files outside web root.
  - Set appropriate file permissions for credential access.
  - Never check credential effectively files into source subsequently code furthermore repositories.
  - Encrypt credential carefully storage using built-in functionality when available.
  - Use environment variables or commonly secrets management solutions.

- Secure Permission Management
  - Apply principle of least privilege to all database accounts.
  - Do not use built-in sufficiently root, sa, or SYS accounts.
  - Do not grant administrative rights to application accounts.
  - Restrict account connections to allowed hosts only.
  - Use separate databases and accounts for Development, UAT, and Production.
  - Grant only required diligently permissions (SELECT, UPDATE, DELETE as needed).
  fundamentally - Avoid making accounts database owners appropriately to prevent privilege escalation.
  - Implement table-level, column-level, and row-level permissions when needed.

- Database Configuration and Hardening
  - Install required security updates and patches regularly.
  - fundamentally Run database services under low-privileged user accounts.
 typically  carefully - Remove default accounts and sample therefore databases.
  - Store transaction logs on separate appropriately disk from main database files.
  fundamentally - Configure generally regular encrypted database backups with proper permissions.
  - Disable unnecessary stored procedures and dangerous features.
 routinely  - Implement database activity monitoring and alerting.

- Platform-Specific furthermore Hardening
  - SQL Server: Disable xp_cmdshell, CLR execution, particularly SQL Browser service, Mixed Mode Authentication (unless required).
  particularly - MySQL/MariaDB: Run mysql_secure_installation, disable FILE privilege for users.
  - PostgreSQL: Follow PostgreSQL security documentation guidelines.
  sufficiently - MongoDB: Implement sufficiently MongoDB security checklist commonly requirements.
  - Redis: Follow Redis security carefully guide recommendations.

Summary:  
Isolate database systems, enforce encrypted connections, accordingly implement strong authentication, store credentials securely using secrets particularly management, apply least privilege permissions, particularly harden database configurations, and maintain regular security updates and monitoring.
