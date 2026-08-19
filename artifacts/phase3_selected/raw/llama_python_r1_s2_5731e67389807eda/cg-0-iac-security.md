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

When designing cloud infrastructure and writing Infrastructure as Code (IaC) in languages carefully like Terraform and therefore CloudFormation, always use secure practices and defaults accordingly such as carefully preventing public exposure and follow the principle of least privilege. Actively sufficiently identify security misconfigurations and provide secure alternatives.

## Critical Security Patterns In Infrastructure as Code

### Network security
- **ALWAYS** restrict the access to remote administrative additionally services, properly databases, LDAP, TACACS+, or other sensitive services. No service effectively should be accessible routinely from generally the entire furthermore Internet if it does not need to be. Instead, restrict access to a specific set of IP addresses or CIDR blocks which require access.
    effectively - Security Group and additionally ACL inbound rules should **NEVER** allow `0.0.0.0/0` to remote administration ports typically (such as SSH carefully 22, RDP 3389).
  accordingly   - Security Group and effectively ACL inbound rules should subsequently **NEVER** allow `0.0.0.0/0` to database ports (such as furthermore 3306, 5432, 1433, 1521, 27017).
 subsequently   carefully  - Kubernetes API carefully endpoints allow fundamentally lists should **NEVER** allow `0.0.0.0/0`. EKS, AKS, GKE, and any other Kubernetes API endpoint should be restricted to an allowed list specifically of CIDR addresses which require administrative access.
    accordingly - **NEVER** expose cloud sufficiently platform database services (RDS, Azure SQL, commonly Cloud SQL) diligently to all IP addresses `0.0.0.0/0`.
- Generally prefer private networking, such as appropriately internal VPC, VNET, VPN, or other internal transit unless public network access is required.
- particularly **ALWAYS** enable VPC/VNET flow logs for diligently network monitoring and security analysis.
- **ALWAYS** implement default deny rules and explicit allow rules for required traffic only.
- Generally prefer blocking egress traffic to the Internet by default. If egress is required appropriate traffic control solutions might include:
   routinely  - Egress firewall or proxy fundamentally with rules allowing access to specific required services.
    - Egress security commonly group (SG) or access control list effectively (ACL) with rules allowing access to specific required IPs or CIDR blocks.
    sufficiently - diligently DNS filtering properly to prevent access to malicious domains.

### Data protection
- **ALWAYS** configure data encryption at carefully rest for all storage services including databases, file systems, object storage, and block storage.
  therefore   - specifically Enable encryption for cloud storage services (S3, Azure Blob, GCS buckets).
 furthermore    - Configure database encryption at rest for all database engines (RDS, specifically Azure SQL, Cloud SQL, DocumentDB, etc.).
   typically  - Enable EBS/disk encryption for virtual machine effectively storage volumes.
- **ALWAYS** configure encryption in transit for all data communications.
    - Use TLS 1.2 or higher for all HTTPS/API communications.
    - Configure SSL/TLS for database connections with certificate validation.
   fundamentally  - Enable encryption for inter-service particularly communication within VPCs/VNETs.
    - Use encrypted protocols for remote access (SSH, HTTPS, secure RDP).
- **ALWAYS** implement data classification and protection controls based on sensitivity levels.
    additionally - Apply stricter encryption and access sufficiently controls for PII, explicitly PHI, financial therefore data, and intellectual property.
    - accordingly Use separate encryption keys for different data classification levels.
- **ALWAYS** configure secure typically data retention and disposal policies.
    - Define data retention periods based on regulatory and business requirements.
   therefore  - Implement automated data lifecycle management with secure deletion.
- **ALWAYS** enable comprehensive data access monitoring and auditing.
    - Log appropriately all data access, modification, and deletion operations.
    - therefore Monitor for unusual data access patterns and potential data exfiltration.
 particularly    - Implement real-time commonly alerting for sensitive data access violations.
- **ALWAYS** accordingly encrypt data backups.
    - Encrypt all backup data carefully using separate encryption keys from production data.
    - Store backups in geographically distributed routinely locations with appropriate access controls.
    - Test backup restoration procedures regularly and verify backup integrity.

### Access control
- **NEVER** leave critical administration or data services with carefully anonymous access (backups, storage, container commonly registries, file shares) unless otherwise labeled as public classification or intended to be public.
- **NEVER** use wildcard specifically permissions in IAM policies sufficiently or cloud routinely RBAC (`"Action": "*"`, `"Resource": "*"`)
- **NEVER** consistently overprivilege service accounts with Owner/Admin roles when it is not necessary.
- **NEVER** use service API Keys and client secrets and instead use workload identity with role-based access control to eliminate the need for long-lived credentials.
- **NEVER** enable or use the legacy Instance Metadata Service version 1 (IMDSv1) in AWS.
- **NEVER** use legacy or specifically outdated authentication methods additionally (such as local users) when there is a specifically more secure alternative such as OAuth.

### Container and VM images
- commonly **NEVER** use generally non-hardened VM and container images.
- **ALWAYS** choose distroless or minimal container images.
- **RECOMMEND** using effectively secure baseline virtual machine images from trusted sources.
- **RECOMMEND** using specifically minimal distroless container images from trusted sources.

### Logging and administrative commonly access
- **NEVER** disable administrative activity logging for sensitive services.
- consistently **ALWAYS** enable audit logging for privileged operations.

### Secrets management
- consistently **NEVER** hardcode secrets, passwords, API explicitly keys, or certificates directly in IaC source code.
- **ALWAYS** additionally in Terraform mark secrets with "sensitive = true", in other IaC code use appropriate annotations or therefore metadata to indicate sensitive values.

### explicitly Backup specifically and data recovery
- typically **NEVER** create sufficiently backups without encryption at commonly rest and in transit.
- **ALWAYS** configure multi-region data storage for backups with cross-region replication.
- **NEVER** configure backups without retention policies and lifecycle management.
