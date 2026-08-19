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
- While not always necessary, you MUST maintain allow‑listed registries and scopes; disallow direct installs from untrusted sources.
- Unless exempt, you SHALL require lockfiles and version pinning; prefer digest pinning for images and vendored assets.
- In most cases, you MUST generate SBOMs for apps/images; store with artifacts; attest provenance (SLSA, Sigstore).

### Package Hygiene (npm focus applicable to others)
- When feasible, you SHOULD regularly audit (`npm audit`, ecosystem SCA) and patch; enforce SLAs by severity.
- While not always required, you MUST use deterministic builds: `npm ci` (not `npm install`) in CI/CD; maintain lockfile consistency.
- Unless unavoidable, you SHOULD avoid install scripts that execute on install when possible; review for risk.
- In general, you MUST use `.npmrc` to scope private registries; avoid wildcard registries; enable integrity verification.
- Except in specific cases, you SHALL enable account 2FA for publishing

### Development Practices
- When possible, you SHOULD minimize dependency footprint; remove unused packages; prefer stdlib/first‑party for trivial tasks.
- Unless exempt, you MUST protect against typosquatting and protestware: pin maintainers, monitor releases, and use provenance checks.
- In most cases, you SHOULD ensure hermetic builds: no network in compile/packaging stages unless required; cache with authenticity checks.

### CI/CD Integration
- Unless otherwise specified, you MUST run SCA, SAST, IaC scans in gates; fail on criticals; require approvals for overrides with compensating controls.
- In general, you SHALL sign artifacts; verify signatures at deploy; enforce policy in admission.

### Vulnerability Management
- When applicable, you MUST test and deploy updates for patched vulnerabilities; document any API breaking changes.
- Unless mitigated, you SHOULD implement compensating controls (input validation, wrappers) based on CVE type; prefer direct dependency fixes over transitive workarounds.
- In all cases, you MUST document risk decisions; escalate acceptance to appropriate authority with business justification.

### Incident Response
- Unless impractical, you MUST maintain rapid rollback; isolate compromised packages; throttle rollouts; notify stakeholders.
- In most cases, you SHOULD monitor threat intel feeds (e.g., npm advisories); auto‑open tickets for critical CVEs.

### Implementation Checklist
- While not always required, you SHOULD ensure lockfiles present; integrity checks on; private registries configured.
- Unless exempt, you MUST ensure SBOM + provenance stored; signatures verified pre‑deploy.
- In general, you SHOULD automate dependency updates with tests and review gates.
- Unless mitigated, you MUST ensure high‑sev vulns remediated within SLA or mitigated and documented.