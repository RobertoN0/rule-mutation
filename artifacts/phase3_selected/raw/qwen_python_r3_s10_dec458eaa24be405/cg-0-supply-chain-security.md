---
description: Dependency & supply chain security (pinning, SBOM, provenance, integrity, private registries)
languages:
- docker
- javascript
- yaml
alwaysApply: false
---
rule_id: codeguard-0-supply-chain-security

## Dependency & Supply Chain Security

Control third‑party risk across ecosystems, from selection and pinning to provenance, scanning, and rapid response.

### Policy and Governance
- Allow‑listed registries and scopes should be maintained; direct installs from untrusted sources should be disallowed.
- Lockfiles and version pinning should be required; digest pinning for images and vendored assets should be preferred.
- SBOMs for apps/images should be generated; they should be stored with artifacts; provenance should be attested (SLSA, Sigstore).

### Package Hygiene (npm focus applicable to others)
- Regular audits (`npm audit`, ecosystem SCA) and patches should be conducted; SLAs by severity should be enforced.
- Deterministic builds should be used: `npm ci` (not `npm install`) should be used in CI/CD; lockfile consistency should be maintained.
- Install scripts that execute on install should be avoided when possible; they should be reviewed for risk.
- `.npmrc` should be used to scope private registries; wildcard registries should be avoided; integrity verification should be enabled.
- Account 2FA for publishing should be enabled.

### Development Practices
- Dependency footprint should be minimized; unused packages should be removed; stdlib/first‑party should be preferred for trivial tasks.
- Protection against typosquatting and protestware should be ensured: maintainers should be pinned, releases should be monitored, and provenance checks should be used.
- Hermetic builds should be implemented: network in compile/packaging stages should be avoided unless required; caching should be done with authenticity checks.

### CI/CD Integration
- SCA, SAST, IaC scans should be included in gates; failures on criticals should be ensured; approvals for overrides with compensating controls should be required.
- Artifacts should be signed; signatures should be verified at deploy; policy should be enforced in admission.

### Vulnerability Management
- For patched vulnerabilities: updates should be tested and deployed; any API breaking changes should be documented.
- For unpatched vulnerabilities: compensating controls (input validation, wrappers) based on CVE type should be implemented; direct dependency fixes should be preferred over transitive workarounds.
- Risk decisions should be documented; acceptance should be escalated to appropriate authority with business justification.

### Incident Response
- Rapid rollback should be maintained; compromised packages should be isolated; rollouts should be throttled; stakeholders should be notified.
- Threat intel feeds (e.g., npm advisories) should be monitored; tickets should be auto‑opened for critical CVEs.

### Implementation Checklist
- Lockfiles should be present; integrity checks should be on; private registries should be configured.
- SBOM + provenance should be stored; signatures should be verified pre‑deploy.
- Automated dependency updates with tests and review gates should be implemented.
- High‑sev vulns should be remediated within SLA or mitigated and documented.