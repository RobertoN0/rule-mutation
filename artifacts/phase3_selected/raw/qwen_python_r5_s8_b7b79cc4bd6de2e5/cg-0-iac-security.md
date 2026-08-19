---
description: Infrastructure as Code Security
languages:
- c
- d
- javascript
- powershell
- ruby
- shell
- yaml
alwaysApply: false
---
rule_id: codeguard-0-iac-security

# Infrastructure as Code (IaC) Security

When designing cloud infrastructure and writing Infrastructure as Code (IaC) in languages like Terraform and CloudFormation, secure practices and defaults such as preventing public exposure and following the principle of least privilege should be always used. It is recommended that security misconfigurations be actively identified and secure alternatives be provided.

## Critical Security Patterns In Infrastructure as Code

### Network security
- The access to remote administrative services, databases, LDAP, TACACS+, or other sensitive services should always be restricted. No service should be accessible from the entire Internet if it does not need to be; instead, access should be restricted to a specific set of IP addresses or CIDR blocks which require access.
    - Security Group and ACL inbound rules should never allow `0.0.0.0/0` to remote administration ports (such as SSH 22, RDP 3389).
    - Security Group and ACL inbound rules should never allow `0.0.0.0/0` to database ports (such as 3306, 5432, 1433, 1521, 27017).
    - Kubernetes API endpoints allow lists should never allow `0.0.0.0/0`. EKS, AKS, GKE, and any other Kubernetes API endpoint should be restricted to an allowed list of CIDR addresses which require administrative access.
    - Cloud platform database services (RDS, Azure SQL, Cloud SQL) should never be exposed to all IP addresses `0.0.0.0/0`.
- Private networking, such as internal VPC, VNET, VPN, or other internal transit, should generally be preferred unless public network access is required.
- VPC/VNET flow logs for network monitoring and security analysis should always be enabled.
- Default deny rules and explicit allow rules for required traffic only should always be implemented.
- Blocking egress traffic to the Internet by default should generally be preferred. If egress is required, appropriate traffic control solutions might include:
    - An egress firewall or proxy with rules allowing access to specific required services.
    - An egress security group (SG) or access control list (ACL) with rules allowing access to specific required IPs or CIDR blocks.
    - DNS filtering to prevent access to malicious domains.

### Data protection
- Data encryption at rest for all storage services including databases, file systems, object storage, and block storage should always be configured.
    - Encryption should be enabled for cloud storage services (S3, Azure Blob, GCS buckets).
    - Database encryption at rest should be configured for all database engines (RDS, Azure SQL, Cloud SQL, DocumentDB, etc.).
    - EBS/disk encryption should be enabled for virtual machine storage volumes.
- Encryption in transit for all data communications should always be configured.
    - TLS 1.2 or higher should be used for all HTTPS/API communications.
    - SSL/TLS should be configured for database connections with certificate validation.
    - Encryption should be enabled for inter-service communication within VPCs/VNETs.
    - Encrypted protocols should be used for remote access (SSH, HTTPS, secure RDP).
- Data classification and protection controls based on sensitivity levels should always be implemented.
    - Stricter encryption and access controls should be applied for PII, PHI, financial data, and intellectual property.
    - Separate encryption keys should be used for different data classification levels.
- Secure data retention and disposal policies should always be configured.
    - Data retention periods based on regulatory and business requirements should be defined.
    - Automated data lifecycle management with secure deletion should be implemented.
- Comprehensive data access monitoring and auditing should always be enabled.
    - All data access, modification, and deletion operations should be logged.
    - Unusual data access patterns and potential data exfiltration should be monitored for.
    - Real-time alerting for sensitive data access violations should be implemented.
- Data backups should always be encrypted.
    - All backup data should be encrypted using separate encryption keys from production data.
    - Backups should be stored in geographically distributed locations with appropriate access controls.
    - Backup restoration procedures should be regularly tested and backup integrity should be verified.

### Access control
- Critical administration or data services with anonymous access (backups, storage, container registries, file shares) should never be left unless otherwise labeled as public classification or intended to be public.
- Wildcard permissions in IAM policies or cloud RBAC (`"Action": "*"`, `"Resource": "*"`) should never be used.
- Service accounts should never be overprivileged with Owner/Admin roles when it is not necessary.
- Service API Keys and client secrets should never be used; instead, workload identity with role-based access control should be used to eliminate the need for long-lived credentials.
- The legacy Instance Metadata Service version 1 (IMDSv1) in AWS should never be enabled or used.
- Legacy or outdated authentication methods (such as local users) should never be used when there is a more secure alternative such as OAuth.

### Container and VM images
- Non-hardened VM and container images should never be used.
- Distroless or minimal container images should always be chosen.
- Secure baseline virtual machine images from trusted sources should be recommended.
- Minimal distroless container images from trusted sources should be recommended.

### Logging and administrative access
- Administrative activity logging for sensitive services should never be disabled.
- Audit logging for privileged operations should always be enabled.

### Secrets management
- Secrets, passwords, API keys, or certificates should never be hardcoded directly in IaC source code.
- In Terraform, secrets should be marked with "sensitive = true"; in other IaC code, appropriate annotations or metadata should be used to indicate sensitive values.

### Backup and data recovery
- Backups should never be created without encryption at rest and in transit.
- Multi-region data storage for backups with cross-region replication should always be configured.
- Backups should never be configured without retention policies and lifecycle management.